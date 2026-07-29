# Batch 005 — Spatial SQL Foundation

Base repository commit: `3ce4561052df26460d1c2b2bbc4f98faa4cc7b42`

This batch begins the migration from the completed JSON classification ledger to a versioned GeoPackage database.

## Scope

- Adds a migration-driven GeoPackage/SQLite schema.
- Adds county, source-release, harvest-run, classification-release, and review tables.
- Adds a standard-library Python administration tool.
- Adds Linux/macOS and Windows command wrappers.
- Adds validation tests.
- Does not change the County Field Map browser application.
- Does not import the completed sector files yet.
- Does not add spatial feature geometry yet.

## Design boundary

SQL migration files are the schema source of truth. Generated `.gpkg` files are build products and must be recreated or promoted through a controlled release process.

Accepted databases are never refreshed in place. A refresh builds a candidate database, validates it, and only then promotes it.

## Local test

Linux/macOS:

```sh
cd database
./init-database.sh
./validate-database.sh
./run-tests.sh
```

Windows:

```bat
cd database
init-database.cmd
validate-database.cmd
run-tests.cmd
```

The generated test database is:

```text
project-data/database/kane-county-build.gpkg
```

The browser application remains unchanged in this batch.
