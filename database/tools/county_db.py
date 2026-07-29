#!/usr/bin/env python3
"""Create, import, and validate the Kane Offline Map GeoPackage."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import county_buildings
import county_ledger

APP_ID = 0x47504B47
USER_VERSION = 10400
TOOL_VERSION = "batch-008.0"
REQUIRED_TABLES = {
    "schema_migration",
    "gpkg_spatial_ref_sys",
    "gpkg_contents",
    "gpkg_geometry_columns",
    "gpkg_extensions",
    "project_setting",
    "county",
    "source_agency",
    "dataset",
    "source_release",
    "source_file",
    "harvest_run",
    "classification_release",
    "classification_sector",
    "classification_cell",
    "classification_review",
    "refresh_issue",
    "release_promotion",
    "source_building",
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def migrations_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "migrations"


def migration_files() -> list[Path]:
    files = sorted(migrations_dir().glob("*.sql"))
    if not files:
        raise RuntimeError("No SQL migration files were found.")
    return files


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def apply_migration(connection: sqlite3.Connection, path: Path, migration_id: int) -> None:
    raw = path.read_bytes()
    sql = raw.decode("utf-8")
    checksum = sha256_bytes(raw)
    applied_at = utc_now()
    record = (
        "INSERT INTO schema_migration "
        "(migration_id, filename, sha256, applied_at) VALUES ("
        f"{migration_id}, {sql_literal(path.name)}, {sql_literal(checksum)}, "
        f"{sql_literal(applied_at)});"
    )
    connection.executescript(f"BEGIN IMMEDIATE;\n{sql}\n{record}\nCOMMIT;")


def initialize_database(output: Path, force: bool) -> None:
    if output.exists():
        if not force:
            raise RuntimeError(f"Output already exists: {output}")
        output.unlink()
    output.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(output)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA application_id = {APP_ID}")
        connection.execute(f"PRAGMA user_version = {USER_VERSION}")
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA synchronous = FULL")
        for migration_id, path in enumerate(migration_files(), start=1):
            apply_migration(connection, path, migration_id)

        now = utc_now()
        with connection:
            connection.executemany(
                "INSERT INTO project_setting(setting_key, setting_value, updated_at) VALUES (?, ?, ?)",
                [
                    ("project", "kane-offline-map", now),
                    ("database_contract", "county-field-geopackage", now),
                    ("schema_version", str(len(migration_files())), now),
                    ("tool_version", TOOL_VERSION, now),
                    ("refresh_policy", "candidate-build-then-promote", now),
                ],
            )
            connection.execute(
                """
                INSERT INTO county(
                    county_name, state_name, state_code, fips_code,
                    canonical_srs_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("Kane County", "Illinois", "IL", "17089", None, now),
            )
    finally:
        connection.close()

    errors = validate_database(output)
    if errors:
        output.unlink(missing_ok=True)
        raise RuntimeError("Created database failed validation:\n- " + "\n- ".join(errors))


def build_ledger_database(
    output: Path,
    archive: Path,
    force: bool,
    release_key: str | None,
) -> dict[str, object]:
    if output.exists() and not force:
        raise RuntimeError(f"Output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".candidate", dir=output.parent
    )
    os.close(handle)
    temporary = Path(temporary_name)
    temporary.unlink()
    try:
        initialize_database(temporary, force=False)
        county_ledger.import_ledger(temporary, archive, release_key)
        errors = validate_ledger_database(temporary)
        if errors:
            raise RuntimeError("Candidate ledger database failed validation:\n- " + "\n- ".join(errors))
        os.replace(temporary, output)
        return database_info(output)
    finally:
        temporary.unlink(missing_ok=True)


def build_building_database(
    output: Path,
    archive: Path,
    geojson: Path,
    force: bool,
    ledger_release_key: str | None,
    building_release_key: str | None,
    source_uri: str | None,
    published_at: str | None,
    id_property: str | None,
) -> dict[str, object]:
    if output.exists() and not force:
        raise RuntimeError(f"Output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".candidate", dir=output.parent
    )
    os.close(handle)
    temporary = Path(temporary_name)
    temporary.unlink()
    try:
        initialize_database(temporary, force=False)
        county_ledger.import_ledger(temporary, archive, ledger_release_key)
        county_buildings.import_buildings(
            temporary, geojson, building_release_key, source_uri, published_at, id_property
        )
        errors = validate_building_database(temporary)
        if errors:
            raise RuntimeError("Candidate building database failed validation:\n- " + "\n- ".join(errors))
        os.replace(temporary, output)
        return database_info(output)
    finally:
        temporary.unlink(missing_ok=True)


def fetch_table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    )
    return {row[0] for row in rows}


def validate_migrations(connection: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    try:
        rows = connection.execute(
            "SELECT migration_id, filename, sha256 FROM schema_migration ORDER BY migration_id"
        ).fetchall()
    except sqlite3.Error as exc:
        return [f"Cannot read schema_migration: {exc}"]

    expected = migration_files()
    if len(rows) != len(expected):
        errors.append(f"Migration count is {len(rows)}; expected {len(expected)}.")
        return errors
    for index, (migration_id, filename, checksum) in enumerate(rows, start=1):
        path = expected[index - 1]
        expected_checksum = sha256_bytes(path.read_bytes())
        if migration_id != index:
            errors.append(f"Migration id {migration_id} is out of sequence; expected {index}.")
        if filename != path.name:
            errors.append(f"Migration {index} filename is {filename}; expected {path.name}.")
        if checksum != expected_checksum:
            errors.append(f"Migration checksum mismatch: {path.name}.")
    return errors


def validate_database(path: Path) -> list[str]:
    errors: list[str] = []
    if not path.is_file():
        return [f"Database does not exist: {path}"]

    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        application_id = connection.execute("PRAGMA application_id").fetchone()[0]
        if application_id != APP_ID:
            errors.append(f"GeoPackage application_id is {application_id}; expected {APP_ID}.")
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        if user_version != USER_VERSION:
            errors.append(f"GeoPackage user_version is {user_version}; expected {USER_VERSION}.")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            errors.append(f"SQLite integrity_check failed: {integrity}")
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_keys:
            errors.append(f"Foreign-key violations: {len(foreign_keys)}")

        tables = fetch_table_names(connection)
        missing = REQUIRED_TABLES - tables
        if missing:
            errors.append("Missing tables: " + ", ".join(sorted(missing)))
        else:
            errors.extend(validate_migrations(connection))
            errors.extend(county_ledger.classification_errors(connection, require_accepted=False))
            errors.extend(county_buildings.building_errors(connection, require_accepted=False))

        srs_ids = {
            row[0] for row in connection.execute(
                "SELECT srs_id FROM gpkg_spatial_ref_sys WHERE srs_id IN (-1, 0, 4326)"
            )
        }
        if srs_ids != {-1, 0, 4326}:
            errors.append("Required GeoPackage spatial reference rows are incomplete.")
        project_rows = connection.execute(
            "SELECT setting_value FROM project_setting WHERE setting_key = 'project'"
        ).fetchall()
        if project_rows != [("kane-offline-map",)]:
            errors.append("Kane Offline Map project identity is missing or unexpected.")
        county_rows = connection.execute(
            "SELECT county_name, state_code, fips_code FROM county"
        ).fetchall()
        if county_rows != [("Kane County", "IL", "17089")]:
            errors.append("Kane County identity row is missing or unexpected.")
    except sqlite3.Error as exc:
        errors.append(f"SQLite validation error: {exc}")
    finally:
        connection.close()
    return errors


def validate_ledger_database(path: Path) -> list[str]:
    errors = validate_database(path)
    if errors or not path.is_file():
        return errors
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        errors.extend(county_ledger.classification_errors(connection, require_accepted=True))
    except sqlite3.Error as exc:
        errors.append(f"Classification validation error: {exc}")
    finally:
        connection.close()
    return errors


def validate_building_database(path: Path) -> list[str]:
    errors = validate_ledger_database(path)
    if errors or not path.is_file():
        return errors
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        errors.extend(county_buildings.building_errors(connection, require_accepted=True))
    except sqlite3.Error as exc:
        errors.append(f"Building validation error: {exc}")
    finally:
        connection.close()
    return errors


def database_info(path: Path) -> dict[str, object]:
    errors = validate_database(path)
    if errors:
        return {"valid": False, "path": str(path), "errors": errors}

    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        migrations = connection.execute(
            "SELECT migration_id, filename, sha256, applied_at FROM schema_migration ORDER BY migration_id"
        ).fetchall()
        county = connection.execute(
            "SELECT county_name, state_name, state_code, fips_code, canonical_srs_id FROM county"
        ).fetchone()
        return {
            "valid": True,
            "path": str(path),
            "byte_length": path.stat().st_size,
            "sha256": sha256_bytes(path.read_bytes()),
            "application_id": connection.execute("PRAGMA application_id").fetchone()[0],
            "user_version": connection.execute("PRAGMA user_version").fetchone()[0],
            "county": {
                "name": county[0],
                "state": county[1],
                "state_code": county[2],
                "fips_code": county[3],
                "canonical_srs_id": county[4],
            },
            "migrations": [
                {
                    "migration_id": row[0],
                    "filename": row[1],
                    "sha256": row[2],
                    "applied_at": row[3],
                }
                for row in migrations
            ],
            **county_ledger.ledger_info(path),
            **county_buildings.building_info(path),
        }
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create an empty candidate GeoPackage.")
    init_parser.add_argument("--output", type=Path, required=True)
    init_parser.add_argument("--force", action="store_true")

    build_parser = subparsers.add_parser(
        "build-ledger", help="Build a candidate GeoPackage with the accepted field ledger."
    )
    build_parser.add_argument("--archive", type=Path, required=True)
    build_parser.add_argument("--output", type=Path, required=True)
    build_parser.add_argument("--release-key")
    build_parser.add_argument("--force", action="store_true")

    buildings_parser = subparsers.add_parser(
        "build-buildings",
        help="Build a candidate with the accepted ledger and one building GeoJSON release.",
    )
    buildings_parser.add_argument("--archive", type=Path, required=True)
    buildings_parser.add_argument("--geojson", type=Path, required=True)
    buildings_parser.add_argument("--output", type=Path, required=True)
    buildings_parser.add_argument("--ledger-release-key")
    buildings_parser.add_argument("--release-key")
    buildings_parser.add_argument("--source-uri")
    buildings_parser.add_argument("--published-at")
    buildings_parser.add_argument("--id-property")
    buildings_parser.add_argument("--force", action="store_true")

    import_parser = subparsers.add_parser(
        "import-ledger", help="Import the completed field ledger into an existing candidate."
    )
    import_parser.add_argument("database", type=Path)
    import_parser.add_argument("--archive", type=Path, required=True)
    import_parser.add_argument("--release-key")

    validate_parser = subparsers.add_parser("validate", help="Validate a candidate GeoPackage.")
    validate_parser.add_argument("database", type=Path)

    validate_ledger_parser = subparsers.add_parser(
        "validate-ledger", help="Require and validate one accepted classification release."
    )
    validate_ledger_parser.add_argument("database", type=Path)

    validate_buildings_parser = subparsers.add_parser(
        "validate-buildings", help="Require and validate one accepted building release."
    )
    validate_buildings_parser.add_argument("database", type=Path)

    info_parser = subparsers.add_parser("info", help="Print database metadata as JSON.")
    info_parser.add_argument("database", type=Path)
    return parser


def print_validation(errors: list[str], path: Path, label: str) -> int:
    if errors:
        print("INVALID", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"VALID {label}: {path}")
    return 0


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "init":
            initialize_database(args.output, args.force)
            print(json.dumps(database_info(args.output), indent=2))
            return 0
        if args.command == "build-ledger":
            info = build_ledger_database(
                args.output, args.archive, args.force, args.release_key
            )
            print(json.dumps(info, indent=2))
            return 0
        if args.command == "build-buildings":
            info = build_building_database(
                args.output, args.archive, args.geojson, args.force,
                args.ledger_release_key, args.release_key, args.source_uri,
                args.published_at, args.id_property,
            )
            print(json.dumps(info, indent=2))
            return 0
        if args.command == "import-ledger":
            errors = validate_database(args.database)
            if errors:
                raise RuntimeError("Target database is invalid:\n- " + "\n- ".join(errors))
            county_ledger.import_ledger(args.database, args.archive, args.release_key)
            print(json.dumps(database_info(args.database), indent=2))
            return 0
        if args.command == "validate":
            return print_validation(validate_database(args.database), args.database, "database")
        if args.command == "validate-ledger":
            return print_validation(
                validate_ledger_database(args.database), args.database, "classification ledger"
            )
        if args.command == "validate-buildings":
            return print_validation(
                validate_building_database(args.database), args.database, "building release"
            )
        if args.command == "info":
            info = database_info(args.database)
            print(json.dumps(info, indent=2))
            return 0 if info.get("valid") else 1
    except (OSError, RuntimeError, sqlite3.Error, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
