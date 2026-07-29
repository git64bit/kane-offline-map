#!/usr/bin/env python3
"""Compare, validate, and report versioned building releases."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import struct
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

SRS_ID = 4326
DATASET_KEY = "buildings"
CHANGE_TYPES = (
    "added",
    "removed",
    "unchanged",
    "geometry_changed",
    "attributes_changed",
    "modified",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def release_features(connection: sqlite3.Connection, release_id: int) -> dict[str, tuple[Any, ...]]:
    rows = connection.execute(
        """
        SELECT source_feature_id, source_building_id, geometry_sha256,
               attributes_sha256, content_sha256
        FROM source_building WHERE release_id = ?
        """,
        (release_id,),
    )
    return {row[0]: row[1:] for row in rows}


def change_type(previous: tuple[Any, ...] | None, candidate: tuple[Any, ...] | None) -> str:
    if previous is None:
        return "added"
    if candidate is None:
        return "removed"
    if previous[3] == candidate[3]:
        return "unchanged"
    geometry_changed = previous[1] != candidate[1]
    attributes_changed = previous[2] != candidate[2]
    if geometry_changed and not attributes_changed:
        return "geometry_changed"
    if attributes_changed and not geometry_changed:
        return "attributes_changed"
    return "modified"


def compare_releases(
    connection: sqlite3.Connection,
    run_id: int,
    previous_release_id: int,
    candidate_release_id: int,
    compared_at: str,
) -> dict[str, int]:
    previous = release_features(connection, previous_release_id)
    candidate = release_features(connection, candidate_release_id)
    counts: Counter[str] = Counter()
    rows: list[tuple[Any, ...]] = []
    for source_id in sorted(set(previous) | set(candidate)):
        old = previous.get(source_id)
        new = candidate.get(source_id)
        kind = change_type(old, new)
        counts[kind] += 1
        rows.append(
            (
                source_id,
                kind,
                old[0] if old else None,
                new[0] if new else None,
                old[3] if old else None,
                new[3] if new else None,
            )
        )
    cursor = connection.execute(
        """
        INSERT INTO building_release_comparison(
            run_id, previous_release_id, candidate_release_id, compared_at,
            previous_feature_count, candidate_feature_count, added_count,
            removed_count, unchanged_count, geometry_changed_count,
            attributes_changed_count, modified_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            previous_release_id,
            candidate_release_id,
            compared_at,
            len(previous),
            len(candidate),
            counts["added"],
            counts["removed"],
            counts["unchanged"],
            counts["geometry_changed"],
            counts["attributes_changed"],
            counts["modified"],
        ),
    )
    comparison_id = cursor.lastrowid
    connection.executemany(
        """
        INSERT INTO building_feature_change(
            comparison_id, source_feature_id, change_type,
            previous_source_building_id, candidate_source_building_id,
            previous_content_sha256, candidate_content_sha256
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [(comparison_id, *row) for row in rows],
    )
    return {kind: counts[kind] for kind in CHANGE_TYPES}


def migration_prefix_errors(connection: sqlite3.Connection, migration_files: list[Path]) -> list[str]:
    errors: list[str] = []
    try:
        rows = connection.execute(
            "SELECT migration_id, filename, sha256 FROM schema_migration ORDER BY migration_id"
        ).fetchall()
    except sqlite3.Error as exc:
        return [f"Cannot read schema_migration: {exc}"]
    if not rows:
        return ["Database has no applied migrations."]
    if len(rows) > len(migration_files):
        return [f"Database has {len(rows)} migrations; this tool knows {len(migration_files)}."]
    for expected_id, row in enumerate(rows, start=1):
        migration_id, filename, checksum = row
        path = migration_files[expected_id - 1]
        if migration_id != expected_id or filename != path.name:
            errors.append(f"Migration {expected_id} identity is unexpected.")
            continue
        if checksum != sha256_bytes(path.read_bytes()):
            errors.append(f"Migration checksum mismatch: {filename}.")
    return errors


def upgrade_candidate(database: Path) -> None:
    import county_db

    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        migrations = county_db.migration_files()
        errors = migration_prefix_errors(connection, migrations)
        if errors:
            raise RuntimeError("Candidate cannot be upgraded:\n- " + "\n- ".join(errors))
        applied = connection.execute("SELECT COUNT(*) FROM schema_migration").fetchone()[0]
        for migration_id, path in enumerate(migrations[applied:], start=applied + 1):
            county_db.apply_migration(connection, path, migration_id)
        now = county_db.utc_now()
        with connection:
            connection.execute(f"PRAGMA user_version = {county_db.USER_VERSION}")
            connection.execute(
                "UPDATE project_setting SET setting_value = ?, updated_at = ? WHERE setting_key = 'schema_version'",
                (str(len(migrations)), now),
            )
            connection.execute(
                "UPDATE project_setting SET setting_value = ?, updated_at = ? WHERE setting_key = 'tool_version'",
                (county_db.TOOL_VERSION, now),
            )
    finally:
        connection.close()


def refresh_building_database(
    database: Path,
    geojson: Path,
    release_key: str | None,
    source_uri: str | None,
    published_at: str | None,
    id_property: str | None,
) -> dict[str, object]:
    import county_buildings
    import county_db

    if not database.is_file():
        raise RuntimeError(f"Accepted database does not exist: {database}")
    database.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(
        prefix=f".{database.name}.", suffix=".refresh-candidate", dir=database.parent
    )
    os.close(handle)
    candidate = Path(name)
    try:
        shutil.copy2(database, candidate)
        upgrade_candidate(candidate)
        county_buildings.import_buildings(
            candidate, geojson, release_key, source_uri, published_at, id_property
        )
        errors = county_db.validate_building_database(candidate)
        if errors:
            raise RuntimeError("Refreshed candidate failed validation:\n- " + "\n- ".join(errors))
        os.replace(candidate, database)
        return county_db.database_info(database)
    finally:
        candidate.unlink(missing_ok=True)


def geometry_blob_error(blob: bytes) -> str | None:
    if len(blob) < 45:
        return "geometry BLOB is shorter than the GeoPackage header and WKB type"
    if blob[:2] != b"GP" or blob[2] != 0 or blob[3] != 3:
        return "geometry BLOB has an invalid GeoPackage header"
    if struct.unpack("<i", blob[4:8])[0] != SRS_ID:
        return "geometry BLOB uses an unexpected SRS"
    if blob[40] != 1 or struct.unpack("<I", blob[41:45])[0] not in (3, 6):
        return "geometry WKB is not little-endian Polygon or MultiPolygon"
    return None


def release_content_errors(connection: sqlite3.Connection, release_id: int, release_key: str) -> list[str]:
    errors: list[str] = []
    release_hash = connection.execute(
        "SELECT content_sha256 FROM source_release WHERE release_id = ?", (release_id,)
    ).fetchone()[0]
    source_files = connection.execute(
        "SELECT sha256 FROM source_file WHERE release_id = ?", (release_id,)
    ).fetchall()
    if source_files != [(release_hash,)]:
        errors.append(f"Building release {release_key} source file hash is inconsistent.")
    rows = connection.execute(
        """
        SELECT source_feature_id, geometry, geometry_sha256, attributes_json,
               attributes_sha256, content_sha256
        FROM source_building WHERE release_id = ? ORDER BY source_ordinal
        """,
        (release_id,),
    ).fetchall()
    if not rows:
        errors.append(f"Building release {release_key} contains no features.")
    for source_id, blob, geometry_hash, attributes_json, attributes_hash, content_hash in rows:
        blob_error = geometry_blob_error(blob)
        if blob_error:
            errors.append(f"Building {source_id} {blob_error}.")
            continue
        if geometry_hash != sha256_bytes(blob[40:]):
            errors.append(f"Building {source_id} geometry hash is inconsistent.")
        try:
            parsed = json.loads(attributes_json)
            expected_attributes = sha256_bytes(canonical_json(parsed).encode("utf-8"))
        except (json.JSONDecodeError, TypeError, ValueError):
            errors.append(f"Building {source_id} attributes JSON is invalid.")
            continue
        if attributes_hash != expected_attributes:
            errors.append(f"Building {source_id} attributes hash is inconsistent.")
        expected_content = sha256_bytes(
            canonical_json(
                {
                    "source_feature_id": source_id,
                    "geometry_sha256": geometry_hash,
                    "attributes_sha256": attributes_hash,
                }
            ).encode("utf-8")
        )
        if content_hash != expected_content:
            errors.append(f"Building {source_id} content hash is inconsistent.")
    return errors


def comparison_errors(connection: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    comparisons = connection.execute(
        """
        SELECT comparison_id, run_id, previous_release_id, candidate_release_id,
               previous_feature_count, candidate_feature_count, added_count,
               removed_count, unchanged_count, geometry_changed_count,
               attributes_changed_count, modified_count
        FROM building_release_comparison ORDER BY comparison_id
        """
    ).fetchall()
    for row in comparisons:
        comparison_id, run_id, previous_id, candidate_id, *stored = row
        run = connection.execute(
            "SELECT previous_release_id, candidate_release_id FROM harvest_run WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if run != (previous_id, candidate_id):
            errors.append(f"Building comparison {comparison_id} does not match its harvest run.")
        actual = Counter(
            item[0] for item in connection.execute(
                "SELECT change_type FROM building_feature_change WHERE comparison_id = ?",
                (comparison_id,),
            )
        )
        previous_count = connection.execute(
            "SELECT COUNT(*) FROM source_building WHERE release_id = ?", (previous_id,)
        ).fetchone()[0]
        candidate_count = connection.execute(
            "SELECT COUNT(*) FROM source_building WHERE release_id = ?", (candidate_id,)
        ).fetchone()[0]
        expected = [
            previous_count,
            candidate_count,
            actual["added"],
            actual["removed"],
            actual["unchanged"],
            actual["geometry_changed"],
            actual["attributes_changed"],
            actual["modified"],
        ]
        if stored != expected:
            errors.append(f"Building comparison {comparison_id} summary counts are inconsistent.")
        previous_features = release_features(connection, previous_id)
        candidate_features = release_features(connection, candidate_id)
        feature_rows = connection.execute(
            """
            SELECT source_feature_id, change_type, previous_source_building_id,
                   candidate_source_building_id
            FROM building_feature_change WHERE comparison_id = ?
            """,
            (comparison_id,),
        ).fetchall()
        if {row[0] for row in feature_rows} != set(previous_features) | set(candidate_features):
            errors.append(f"Building comparison {comparison_id} feature coverage is incomplete.")
        for source_id, kind, previous_building_id, candidate_building_id in feature_rows:
            expected_kind = change_type(
                previous_features.get(source_id), candidate_features.get(source_id)
            )
            if kind != expected_kind:
                errors.append(
                    f"Building comparison {comparison_id} classifies {source_id} as {kind}; "
                    f"expected {expected_kind}."
                )
            old = connection.execute(
                "SELECT release_id, source_feature_id FROM source_building WHERE source_building_id = ?",
                (previous_building_id,),
            ).fetchone() if previous_building_id else None
            new = connection.execute(
                "SELECT release_id, source_feature_id FROM source_building WHERE source_building_id = ?",
                (candidate_building_id,),
            ).fetchone() if candidate_building_id else None
            if old and old != (previous_id, source_id):
                errors.append(f"Building comparison {comparison_id} has an invalid previous pointer.")
            if new and new != (candidate_id, source_id):
                errors.append(f"Building comparison {comparison_id} has an invalid candidate pointer.")
            if kind == "added" and old is not None:
                errors.append(f"Added building {source_id} unexpectedly has a previous row.")
            if kind == "removed" and new is not None:
                errors.append(f"Removed building {source_id} unexpectedly has a candidate row.")
    return errors


def building_errors(connection: sqlite3.Connection, require_accepted: bool) -> list[str]:
    errors: list[str] = []
    contents = connection.execute(
        "SELECT data_type, srs_id FROM gpkg_contents WHERE table_name = 'source_building'"
    ).fetchall()
    if contents != [("features", SRS_ID)]:
        errors.append("source_building is not correctly registered in gpkg_contents.")
    columns = connection.execute(
        """
        SELECT column_name, geometry_type_name, srs_id, z, m
        FROM gpkg_geometry_columns WHERE table_name = 'source_building'
        """
    ).fetchall()
    if columns != [("geometry", "GEOMETRY", SRS_ID, 0, 0)]:
        errors.append("source_building is not correctly registered in gpkg_geometry_columns.")
    releases = connection.execute(
        """
        SELECT r.release_id, r.release_key, r.status, r.superseded_at
        FROM source_release r JOIN dataset d ON d.dataset_id = r.dataset_id
        WHERE d.dataset_key = ? AND r.status IN ('accepted', 'superseded')
        ORDER BY r.release_id
        """,
        (DATASET_KEY,),
    ).fetchall()
    accepted = [row for row in releases if row[2] == "accepted"]
    if require_accepted and len(accepted) != 1:
        errors.append(f"Accepted building release count is {len(accepted)}; expected 1.")
    for release_id, release_key, status, superseded_at in releases:
        if status == "superseded" and not superseded_at:
            errors.append(f"Superseded building release {release_key} lacks superseded_at.")
        if status == "accepted" and superseded_at:
            errors.append(f"Accepted building release {release_key} has superseded_at.")
        errors.extend(release_content_errors(connection, release_id, release_key))
    errors.extend(comparison_errors(connection))
    if releases:
        expected_comparisons = max(0, len(releases) - 1)
        actual_comparisons = connection.execute(
            "SELECT COUNT(*) FROM building_release_comparison"
        ).fetchone()[0]
        if actual_comparisons != expected_comparisons:
            errors.append(
                f"Building comparison count is {actual_comparisons}; expected {expected_comparisons}."
            )
    return errors


def building_info(path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = connection.execute(
            """
            SELECT r.release_id, r.release_key, r.source_published_at, r.harvested_at,
                   r.accepted_at, r.source_uri, r.content_sha256,
                   COUNT(b.source_building_id), MIN(b.min_x), MIN(b.min_y),
                   MAX(b.max_x), MAX(b.max_y)
            FROM source_release r JOIN dataset d ON d.dataset_id = r.dataset_id
            LEFT JOIN source_building b ON b.release_id = r.release_id
            WHERE d.dataset_key = ? AND r.status = 'accepted'
            GROUP BY r.release_id
            """,
            (DATASET_KEY,),
        ).fetchone()
        if row is None:
            return {}
        comparison = connection.execute(
            """
            SELECT p.release_key, c.added_count, c.removed_count, c.unchanged_count,
                   c.geometry_changed_count, c.attributes_changed_count, c.modified_count
            FROM building_release_comparison c
            JOIN source_release p ON p.release_id = c.previous_release_id
            WHERE c.candidate_release_id = ?
            """,
            (row[0],),
        ).fetchone()
        accepted: dict[str, Any] = {
            "release_key": row[1],
            "source_published_at": row[2],
            "harvested_at": row[3],
            "accepted_at": row[4],
            "source_uri": row[5],
            "content_sha256": row[6],
            "feature_count": row[7],
            "bounds": {"min_x": row[8], "min_y": row[9], "max_x": row[10], "max_y": row[11]},
            "srs_id": SRS_ID,
        }
        if comparison:
            accepted["comparison"] = {
                "previous_release_key": comparison[0],
                "added": comparison[1],
                "removed": comparison[2],
                "unchanged": comparison[3],
                "geometry_changed": comparison[4],
                "attributes_changed": comparison[5],
                "modified": comparison[6],
            }
        accepted["release_history_count"] = connection.execute(
            """
            SELECT COUNT(*) FROM source_release r JOIN dataset d ON d.dataset_id = r.dataset_id
            WHERE d.dataset_key = ? AND r.status IN ('accepted', 'superseded')
            """,
            (DATASET_KEY,),
        ).fetchone()[0]
        return {"accepted_buildings": accepted}
    finally:
        connection.close()
