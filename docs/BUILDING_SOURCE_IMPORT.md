# Building Source Import Contract

## Purpose

Batch 008 establishes the first repeatable source-geometry import path. It accepts one immutable countywide building GeoJSON release and stores it as a native GeoPackage feature table alongside the accepted field classification.

The import contract does not harvest a county source. Batch 009 extends it with an explicit refresh path for later authoritative harvests.

## Accepted input

The input must be either:

- a GeoJSON `FeatureCollection`; or
- an array of GeoJSON `Feature` objects.

Each feature must:

- have `Polygon` or `MultiPolygon` geometry;
- contain two-dimensional EPSG:4326 longitude/latitude coordinates;
- use closed linear rings with at least four positions; and
- have a stable source identifier.

Identifier selection is:

1. the property named by `--id-property`, when supplied;
2. `feature.id`; or
3. a recognized property such as `id`, `OBJECTID`, `FID`, or `building_id`.

Duplicate or missing identifiers reject the candidate.

## SQL and spatial representation

Every accepted feature is stored in `source_building` with:

- source release and source identifier;
- source order;
- native GeoPackage geometry BLOB;
- geometry and attributes hashes;
- complete canonical attributes JSON;
- a stable feature-content hash; and
- minimum and maximum X/Y bounds.

The table is registered in `gpkg_contents` as `features` and in `gpkg_geometry_columns` with SRS ID 4326. Polygon and MultiPolygon WKB are wrapped in the standard GeoPackage geometry header.

The source GeoJSON file is recorded in `source_file`, while `source_release` and `harvest_run` preserve release identity and import history.

## Release refresh rule

The first import creates the accepted building release. A later refresh is built against a temporary copy of the accepted GeoPackage. Pending migrations are applied to that copy before the candidate release is imported.

Features are matched by exact stable source identifier. Each identity is recorded as:

- `added`;
- `removed`;
- `unchanged`;
- `geometry_changed`;
- `attributes_changed`; or
- `modified` when geometry and attributes both changed.

The complete comparison is stored in `building_release_comparison` and `building_feature_change`. The previous release becomes `superseded`, while all prior source rows remain immutable. A failed refresh discards the temporary candidate and leaves the accepted database unchanged.

## Production command

From the repository root:

```sh
bash database/build-building-database.sh /absolute/or/relative/buildings.geojson RELEASE_KEY
bash database/refresh-building-database.sh /absolute/or/relative/new-buildings.geojson NEW_RELEASE_KEY
bash database/validate-building-database.sh
```

The initial build command creates a separate temporary candidate containing:

1. the accepted field ledger; and
2. the accepted building source release.

The named output is replaced only after complete validation succeeds.

## Test fixture

`database/fixtures/buildings-sample.geojson` is a synthetic three-feature test fixture. It is not Kane County source data and must never be represented as an authoritative release.

`verify-linux.sh` imports the first fixture and refreshes it with `buildings-refresh-v2.geojson` solely to exercise the production import, comparison, supersession, and validation paths. Neither fixture is authoritative.
