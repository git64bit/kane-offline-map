# Kane Offline Map Database

This directory contains the migration-driven SQL and GeoPackage tools for Kane Offline Map.

The completed 16-sector JSON ledger is retained only as an immutable migration source. The generated GeoPackage is the working SQL classification store. Batch 008 also imports one immutable building GeoJSON release as native GeoPackage geometry.

## Development environment

Database development and validation are Linux-only.

Requirements:

- Linux
- Python 3.9 or newer
- No third-party Python packages

Python supplies the SQLite engine and the Batch 008 GeoPackage geometry encoder. Later reprojection or source-format adapters may use GDAL as an external Linux tool, but the database contract does not depend on it.

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

## Build a candidate with buildings

```sh
bash database/build-building-database.sh /path/to/buildings.geojson RELEASE_KEY
bash database/validate-building-database.sh
```

The input must contain two-dimensional EPSG:4326 Polygon or MultiPolygon features with stable source identifiers. A synthetic fixture is available only for verification:

```sh
bash database/build-building-database.sh database/fixtures/buildings-sample.geojson fixture-buildings-v1
```

The fixture is not authoritative county data. See `docs/BUILDING_SOURCE_IMPORT.md`.

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

PYTHONDONTWRITEBYTECODE=1 python3 database/tools/county_db.py build-buildings \
  --archive database/input/sectors.zip \
  --geojson /path/to/buildings.geojson \
  --output project-data/database/kane-county-build.gpkg \
  --release-key RELEASE_KEY \
  --force
```

`import-ledger` is also available for an already initialized candidate database. It refuses to import the same release key or archive hash twice.
