#!/usr/bin/env python3
"""Command-line interface for Kane Offline Map database tools."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import county_arcgis
import county_boundary
import county_building_refresh
import county_harvest
import county_db
import county_ledger
import county_spatial


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    command = commands.add_parser("init", help="Create an empty candidate GeoPackage.")
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--force", action="store_true")

    command = commands.add_parser(
        "validate-source-profile", help="Validate an offline ArcGIS source profile."
    )
    command.add_argument("profile", type=Path)

    command = commands.add_parser(
        "harvest-arcgis", help="Harvest a deterministic GeoJSON release from ArcGIS."
    )
    command.add_argument("--profile", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--timeout", type=float, default=county_arcgis.DEFAULT_TIMEOUT)
    command.add_argument("--force", action="store_true")

    command = commands.add_parser(
        "validate-harvest", help="Validate an ArcGIS GeoJSON and manifest pair for SQL acceptance."
    )
    command.add_argument("--profile", type=Path, required=True)
    command.add_argument("--geojson", type=Path, required=True)
    command.add_argument("--manifest", type=Path)

    command = commands.add_parser(
        "build-harvested-buildings",
        help="Build a candidate ledger database from one validated ArcGIS building harvest.",
    )
    command.add_argument("--archive", type=Path, required=True)
    command.add_argument("--profile", type=Path, required=True)
    command.add_argument("--geojson", type=Path, required=True)
    command.add_argument("--manifest", type=Path)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--ledger-release-key")
    command.add_argument("--force", action="store_true")

    command = commands.add_parser(
        "refresh-harvested-buildings",
        help="Safely refresh an accepted database from a validated ArcGIS building harvest.",
    )
    command.add_argument("database", type=Path)
    command.add_argument("--profile", type=Path, required=True)
    command.add_argument("--geojson", type=Path, required=True)
    command.add_argument("--manifest", type=Path)

    command = commands.add_parser(
        "build-ledger", help="Build a candidate GeoPackage with the accepted field ledger."
    )
    command.add_argument("--archive", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--release-key")
    command.add_argument("--force", action="store_true")

    command = commands.add_parser(
        "build-buildings",
        help="Build a candidate with the accepted ledger and one building GeoJSON release.",
    )
    command.add_argument("--archive", type=Path, required=True)
    command.add_argument("--geojson", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--ledger-release-key")
    command.add_argument("--release-key")
    command.add_argument("--source-uri")
    command.add_argument("--published-at")
    command.add_argument("--id-property")
    command.add_argument("--force", action="store_true")

    command = commands.add_parser(
        "refresh-buildings",
        help="Safely compare and promote a new building release in an accepted database.",
    )
    command.add_argument("database", type=Path)
    command.add_argument("--geojson", type=Path, required=True)
    command.add_argument("--release-key")
    command.add_argument("--source-uri")
    command.add_argument("--published-at")
    command.add_argument("--id-property")

    command = commands.add_parser(
        "calibrate-grid",
        help="Safely calibrate the accepted classification grid from county boundary GeoJSON.",
    )
    command.add_argument("database", type=Path)
    command.add_argument("--boundary", type=Path, required=True)

    command = commands.add_parser(
        "accept-harvested-boundary",
        help="Accept one validated authoritative county boundary and calibrate the grid.",
    )
    command.add_argument("database", type=Path)
    command.add_argument("--profile", type=Path, required=True)
    command.add_argument("--geojson", type=Path, required=True)
    command.add_argument("--manifest", type=Path)

    command = commands.add_parser(
        "import-ledger", help="Import the completed field ledger into an existing candidate."
    )
    command.add_argument("database", type=Path)
    command.add_argument("--archive", type=Path, required=True)
    command.add_argument("--release-key")

    for name, help_text in (
        ("validate", "Validate a candidate GeoPackage."),
        ("validate-ledger", "Require and validate one accepted classification release."),
        ("validate-buildings", "Require and validate one accepted building release."),
        ("validate-spatial", "Require and validate grid calibration and building-cell relations."),
        ("validate-authoritative", "Require authoritative boundary acceptance and spatial index."),
        ("info", "Print database metadata as JSON."),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("database", type=Path)
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
            county_db.initialize_database(args.output, args.force)
            info = county_db.database_info(args.output)
        elif args.command == "validate-source-profile":
            info = county_arcgis.profile_info(args.profile)
        elif args.command == "harvest-arcgis":
            info = county_arcgis.harvest(
                args.profile, args.output, args.force, args.timeout
            )
        elif args.command == "validate-harvest":
            info = county_harvest.validate_harvest(
                args.profile, args.geojson, args.manifest
            )
        elif args.command == "build-harvested-buildings":
            harvest = county_harvest.validate_harvest(
                args.profile, args.geojson, args.manifest
            )
            info = county_db.build_building_database(
                args.output,
                args.archive,
                args.geojson,
                args.force,
                args.ledger_release_key,
                harvest["release_key"],
                harvest["source_uri"],
                harvest["published_at"],
                harvest["id_property"],
                harvest["harvested_at"],
                harvest["source_version"],
                Path(harvest["manifest"]),
            )
            info["accepted_harvest"] = harvest
        elif args.command == "refresh-harvested-buildings":
            harvest = county_harvest.validate_harvest(
                args.profile, args.geojson, args.manifest
            )
            info = county_building_refresh.refresh_building_database(
                args.database,
                args.geojson,
                harvest["release_key"],
                harvest["source_uri"],
                harvest["published_at"],
                harvest["id_property"],
                harvest["harvested_at"],
                harvest["source_version"],
                Path(harvest["manifest"]),
            )
            info["accepted_harvest"] = harvest
        elif args.command == "build-ledger":
            info = county_db.build_ledger_database(
                args.output, args.archive, args.force, args.release_key
            )
        elif args.command == "build-buildings":
            info = county_db.build_building_database(
                args.output, args.archive, args.geojson, args.force,
                args.ledger_release_key, args.release_key, args.source_uri,
                args.published_at, args.id_property,
            )
        elif args.command == "refresh-buildings":
            info = county_building_refresh.refresh_building_database(
                args.database, args.geojson, args.release_key, args.source_uri,
                args.published_at, args.id_property,
            )
        elif args.command == "calibrate-grid":
            info = county_spatial.calibrate_database(args.database, args.boundary)
        elif args.command == "accept-harvested-boundary":
            info = county_boundary.accept_harvested_boundary(
                args.database, args.profile, args.geojson, args.manifest
            )
        elif args.command == "import-ledger":
            errors = county_db.validate_database(args.database)
            if errors:
                raise RuntimeError("Target database is invalid:\n- " + "\n- ".join(errors))
            county_ledger.import_ledger(args.database, args.archive, args.release_key)
            info = county_db.database_info(args.database)
        elif args.command == "validate":
            return print_validation(
                county_db.validate_database(args.database), args.database, "database"
            )
        elif args.command == "validate-ledger":
            return print_validation(
                county_db.validate_ledger_database(args.database),
                args.database,
                "classification ledger",
            )
        elif args.command == "validate-buildings":
            return print_validation(
                county_db.validate_building_database(args.database),
                args.database,
                "building release",
            )
        elif args.command == "validate-spatial":
            return print_validation(
                county_db.validate_spatial_database(args.database),
                args.database,
                "spatial building index",
            )
        elif args.command == "validate-authoritative":
            return print_validation(
                county_db.validate_authoritative_database(args.database),
                args.database,
                "authoritative county database",
            )
        elif args.command == "info":
            info = county_db.database_info(args.database)
        else:
            return 2
        print(json.dumps(info, indent=2))
        return 0 if info.get("valid", True) else 1
    except (OSError, RuntimeError, sqlite3.Error, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
