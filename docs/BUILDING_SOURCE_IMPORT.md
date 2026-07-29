# Building Source Import Contract

## Purpose

Batch 008 establishes the first repeatable source-geometry import path. It accepts one immutable countywide building GeoJSON release and stores it as a native GeoPackage feature table alongside the accepted field classification.

This batch does not harvest a county source and does not perform a year-to-year refresh. It defines and tests the import contract that a later harvester will call.

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

## Initial-release rule

Batch 008 permits exactly one accepted building release. A second accepted release is rejected with an explicit message because refresh comparison and supersession are not implemented yet.

This prevents an accidental overwrite from being mistaken for a refresh. The next refresh batch will compare a new candidate against the accepted release before promotion.

## Production command

From the repository root:

```sh
bash database/build-building-database.sh /absolute/or/relative/buildings.geojson RELEASE_KEY
bash database/validate-building-database.sh
```

The command always builds a separate temporary candidate containing:

1. the accepted field ledger; and
2. the accepted building source release.

The named output is replaced only after complete validation succeeds.

## Test fixture

`database/fixtures/buildings-sample.geojson` is a synthetic three-feature test fixture. It is not Kane County source data and must never be represented as an authoritative release.

`verify-linux.sh` imports the fixture solely to exercise the full production command and spatial validation path.
