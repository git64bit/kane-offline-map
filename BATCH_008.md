# Batch 008 — Building Source Import Foundation

Accepted base repository commit: `21ebf479bf30398262169d12a5a6f28fecf94e97`

## Scope

- Adds migration `0005_source_buildings.sql`.
- Registers `source_building` as a native GeoPackage feature table.
- Imports Polygon and MultiPolygon GeoJSON into standard GeoPackage geometry BLOBs.
- Preserves source-file, release, dataset, agency, and harvest-run provenance.
- Requires stable source feature identifiers and rejects duplicate identities.
- Stores canonical attributes and independent geometry, attribute, and content hashes.
- Builds a complete temporary candidate and replaces the named database only after validation.
- Refuses a second accepted building release until refresh comparison is implemented.
- Adds a synthetic three-feature fixture for Linux verification only.
- Expands the database suite from 10 to 16 tests.

## Deliberate limits

- No county building source is bundled or harvested.
- Input geometry is limited to two-dimensional EPSG:4326 Polygon and MultiPolygon features.
- No spatial index, feature-to-cell assignment, release diff, or supersession is performed yet.
- TrivialHTTP and the browser application are unchanged.

## Verify on Linux

```sh
bash verify-linux.sh
```

The verification run builds and validates a fixture-backed candidate database, then runs all 16 tests. No compiler is used.
