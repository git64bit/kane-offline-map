# Kane Offline Map Database

This directory contains the migration-driven SQL and GeoPackage tools for Kane Offline Map.

The completed 16-sector JSON ledger is retained only as an immutable migration source. The generated GeoPackage is the working SQL classification store. Batch 008 imports immutable building GeoJSON as native GeoPackage geometry. Batch 009 compares later releases and preserves the complete supersession history. Batch 010 calibrates the browser grid in EPSG:4326, indexes exact building-cell intersections, and creates muted-cell review triggers. Batch 011 adds the authoritative-source acquisition boundary: a deterministic ArcGIS harvest creates canonical GeoJSON and a provenance manifest before any database import is considered. Batch 012 validates that pair as one immutable source release and derives the SQL release identity and provenance without manual metadata entry. Batch 013 adds the corresponding deterministic harvest and offline pair-validation contract for the official county-boundary layer. Batch 014 stores that pair as an immutable GeoPackage release, links it to grid calibration, and constructs the authoritative building-cell index through candidate promotion. Batch 015 provides a read-only canonical GeoJSON export of open building-triggered review cells. Batch 016 splits the same validated review layer into a deterministic 16-sector bundle for active-sector loading. Batch 021 atomically accepts the validated road-centerline, Fox River, and creek harvest pairs into native GeoPackage geometry with immutable provenance. Batch 022 records source road records with absent geometry as explicit hashed exclusions while continuing to reject malformed non-null geometry.

## Development environment

Database development and validation are Linux-only.

Requirements:

- Linux
- Python 3.9 or newer
- No third-party Python packages

Python supplies the SQLite engine, GeoPackage geometry encoder, migration upgrader, release comparison tools, and ArcGIS HTTP client. A live harvest needs outbound HTTPS access, but the complete verification suite is offline and deterministic. Later reprojection or source-format adapters may use GDAL as an external Linux tool, but the database contract does not depend on it.

Shell scripts are invoked through `bash`; executable permission bits are not required.

## Validate and harvest official county sources

Validate the tracked source profile without network access:

```sh
bash database/validate-source-profile.sh
```

Create canonical GeoJSON releases and their `.manifest.json` provenance sidecars:

```sh
bash database/harvest-kane-buildings.sh /path/to/kane-buildings.geojson
bash database/harvest-kane-boundary.sh /path/to/kane-boundary.geojson
```

The harvester first retrieves the complete ArcGIS object-ID set, then queries exact bounded ID groups as EPSG:4326 GeoJSON. Building snapshots use `FPId` as the stable feature identity. The boundary profile requires exactly one polygon feature and uses its `OBJECTID` as the snapshot identity. Missing, duplicate, or unexpected identities reject the whole candidate. Live harvests are deliberately not part of `verify-linux.sh`. See `docs/ARCGIS_HARVEST.md`.

Validate a completed harvest pair without changing a database:

```sh
bash database/validate-kane-building-harvest.sh /path/to/kane-buildings.geojson
bash database/validate-kane-boundary-harvest.sh /path/to/kane-boundary.geojson
```

Accept the validated boundary into an existing authoritative building database:

```sh
bash database/accept-kane-boundary.sh \
  /path/to/kane-county.gpkg \
  /path/to/kane-boundary.geojson

bash database/validate-authoritative-database.sh /path/to/kane-county.gpkg
```

Accept the validated road and water harvests together:

```sh
bash database/accept-kane-map-layers.sh \
  /path/to/kane-county.gpkg \
  /path/to/kane-roads.geojson \
  /path/to/kane-fox-river.geojson \
  /path/to/kane-creeks.geojson

bash database/validate-deployment-database.sh /path/to/kane-county.gpkg
```

The three releases are imported into one candidate and promoted only after complete validation. See `docs/MAP_LAYER_ACCEPTANCE.md`.

The accepted database is copied to a temporary candidate, upgraded, calibrated, spatially indexed, validated, and only then replaced. The source GeoJSON and manifest remain external immutable evidence; their hashes and normalized boundary geometry are preserved in SQL.

Build the first accepted database directly from the completed ledger and a validated official harvest:

```sh
bash database/build-kane-harvest-database.sh \
  /path/to/kane-buildings.geojson \
  /path/to/kane-county.gpkg
```

Refresh a later accepted release:

```sh
bash database/refresh-kane-harvest-database.sh \
  /path/to/kane-county.gpkg \
  /path/to/new-kane-buildings.geojson
```

Both database commands validate the GeoJSON and `.manifest.json` pair before candidate construction. See `docs/HARVEST_ACCEPTANCE.md`.

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


## Calibrate the practical-cell spatial grid

The completed classification grid must be calibrated from the same `county_boundary.json` used by the browser:

```sh
bash database/calibrate-spatial-database.sh /path/to/county_boundary.json
bash database/validate-spatial-database.sh
```

Calibration reproduces the browser's 1400 × 900 fitted projection, including its 35-unit padding and six-column reference grid. The accepted 512 × 512 practical grid is exposed through the SQL view `classification_cell_spatial` in EPSG:4326. Building Polygon and MultiPolygon geometry is intersected exactly against those cell rectangles.

The first calibration indexes the current accepted building release. Later building refreshes automatically index the new accepted release. Added, geometry-changed, and fully modified buildings that intersect muted or undiscovered cells create open rows in `classification_review`; unchanged and attribute-only changes do not.

Calibration and indexing use a temporary candidate database. A failed or conflicting calibration leaves the accepted database unchanged.

## Refresh the accepted building release

After an accepted building database exists:

```sh
bash database/refresh-building-database.sh /path/to/new-buildings.geojson NEW_RELEASE_KEY
bash database/validate-building-database.sh
```

The refresh command copies the accepted GeoPackage to a temporary candidate, applies pending migrations to that copy, imports the new source release, compares stable source IDs, validates the complete database, and atomically replaces the accepted path only after success. The previous building release and all of its feature rows remain in the database with `superseded` status.

The comparison records added, removed, unchanged, geometry-only, attribute-only, and combined modifications. A failed import or validation leaves the accepted file byte-for-byte unchanged.

## Export open review cells

After authoritative boundary acceptance and spatial indexing:

```sh
bash database/export-open-reviews.sh \
  /path/to/kane-county.gpkg \
  /path/to/kane-open-review-cells.geojson
```

The exporter validates the authoritative database, opens it read-only, groups open building-triggered reviews by practical cell, and writes canonical EPSG:4326 GeoJSON through a validated temporary candidate. It does not modify reviews or any source release. See `docs/REVIEW_EXPORT.md`.

For active-sector consumers, export a directory bundle containing `index.json` and exactly 16 sector files:

```sh
bash database/export-open-review-bundle.sh \
  /path/to/kane-county.gpkg \
  /path/to/kane-open-review-bundle
```

The bundle is built and validated in a temporary directory before promotion. Existing output is preserved unless `--force` is explicit. See `docs/REVIEW_BUNDLE.md`.

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
PYTHONDONTWRITEBYTECODE=1 python3 database/tools/county_db.py validate-source-profile \
  database/sources/kane-county-buildings.json

PYTHONDONTWRITEBYTECODE=1 python3 database/tools/county_db.py harvest-arcgis \
  --profile database/sources/kane-county-buildings.json \
  --output /path/to/kane-buildings.geojson

PYTHONDONTWRITEBYTECODE=1 python3 database/tools/county_db.py build-ledger \
  --archive database/input/sectors.zip \
  --output project-data/database/kane-county-build.gpkg \
  --force

PYTHONDONTWRITEBYTECODE=1 python3 database/tools/county_db.py calibrate-grid \
  project-data/database/kane-county-build.gpkg \
  --boundary /path/to/county_boundary.json

PYTHONDONTWRITEBYTECODE=1 python3 database/tools/county_db.py refresh-buildings \
  project-data/database/kane-county-build.gpkg \
  --geojson /path/to/new-buildings.geojson \
  --release-key NEW_RELEASE_KEY

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

## Prepared browser core

Export the accepted county boundary and buildings without modifying the database:

```sh
bash database/export-prepared-core.sh /path/to/kane-county.gpkg /path/to/prepared-core
```

The resulting directory is explicitly incomplete until roads and water are added.
