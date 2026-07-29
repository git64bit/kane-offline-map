# Kane Offline Map Database

This directory contains the migration-driven SQL and GeoPackage tools for Kane Offline Map.

The completed 16-sector JSON ledger is retained only as an immutable migration source. The generated GeoPackage is the working SQL classification store.

## Development environment

Database development and validation are Linux-only.

Requirements:

- Linux
- Python 3.9 or newer
- No third-party Python packages

Python supplies the SQLite engine used by this batch. Future geometry imports may use GDAL as an external Linux tool, but the database contract does not depend on it.

Shell scripts are invoked through `bash`; executable permission bits are not required.

## Build the completed ledger database

From the repository root:

```sh
bash database/build-ledger-database.sh
```

Or from this directory:

```sh
bash build-ledger-database.sh
```

The build command:

1. reads `input/sectors.zip`;
2. validates all 16 sector documents and 262,144 practical cells;
3. creates a separate temporary candidate database;
4. imports one accepted classification release;
5. validates the candidate; and
6. atomically replaces `../project-data/database/kane-county-build.gpkg` only after success.

A failed rebuild leaves the existing candidate database unchanged.

## Validate the imported ledger

```sh
bash database/validate-ledger-database.sh
```

Generic schema validation remains available through:

```sh
bash database/validate-database.sh
```

## Run tests

```sh
bash database/run-tests.sh
```

The supplied scripts set `PYTHONDONTWRITEBYTECODE=1`. They do not require or create tracked Python cache files.

## Direct command use

```sh
PYTHONDONTWRITEBYTECODE=1 python3 database/tools/county_db.py build-ledger \
  --archive database/input/sectors.zip \
  --output project-data/database/kane-county-build.gpkg \
  --force

PYTHONDONTWRITEBYTECODE=1 python3 database/tools/county_db.py validate-ledger \
  project-data/database/kane-county-build.gpkg

PYTHONDONTWRITEBYTECODE=1 python3 database/tools/county_db.py info \
  project-data/database/kane-county-build.gpkg
```

`import-ledger` is also available for an already initialized candidate database. It refuses to import the same release key or archive hash twice.
