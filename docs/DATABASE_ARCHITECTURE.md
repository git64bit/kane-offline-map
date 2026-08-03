# Kane Offline Map Database Architecture

## Canonical model

The project has one canonical working store: a versioned GeoPackage database.

```text
Immutable source releases
          |
          v
Temporary candidate GeoPackage
          |
   validation and diff
          |
          v
Accepted GeoPackage release
          |
          v
Queries, reports, indexes, and application exports
```

JSON is retained only as immutable input evidence or as a generated interchange export. It is not the continuing source of truth.

GeoPackage combines portable SQLite SQL storage with standards-based spatial tables in one file. The database remains usable without TrivialHTTP. TrivialHTTP may later expose narrowly controlled read and refresh operations to the browser.

## Current data layers

### Administration

Records county identity, schema migrations, source agencies, datasets, harvest runs, source releases, and source files. Batch 012 preserves an accepted ArcGIS GeoJSON and its manifest as two hashed source-file records and stores the source-profile hash as the release source version.

### Classification

Records immutable Kane Offline Map releases, sector source hashes, normalized practical-cell classifications, and review requests caused by later development. Batch 010 creates review rows only for added or spatially changed buildings that intersect muted or undiscovered cells; attribute-only changes do not alter spatial classification.

Batch 006 imports the completed field ledger as the first accepted classification release.

### Source geometry

Batch 008 adds `source_building` as the first native GeoPackage feature table. Each immutable building release preserves source identity, attributes, Polygon or MultiPolygon geometry, content hashes, bounds, and source-file provenance. Batch 014 adds `source_county_boundary` for the single accepted authoritative county geometry and its harvest provenance. Batch 021 adds `source_map_feature` for accepted road-centerline, Fox River, and creek releases, supporting LineString, MultiLineString, Polygon, and MultiPolygon geometry. Future migrations may add parcels and addresses.

### Derived data

Batch 010 adds `classification_grid_calibration`, the `classification_cell_spatial` SQL view, and `building_cell_relation`. Calibration reproduces the browser's exact fitted projection from the authoritative county-boundary extent. Batch 014 links that calibration row to the accepted boundary release and sets the county canonical SRS to EPSG:4326. The view exposes all 262,144 practical-cell rectangles in EPSG:4326 without duplicating the classification table.

Each immutable building row is related to every practical cell its Polygon or MultiPolygon geometry actually intersects. The relation is release-specific through `source_building_id` and classification-release-specific through the grid key. Batch 015 emits the current open building-triggered review cells as a read-only canonical GeoJSON application export. Later migrations will add building clusters, road graphs, summaries, and additional application exports.

### Change history

Batch 009 adds `building_release_comparison` and `building_feature_change`. A refresh compares exact stable source IDs and records added, removed, unchanged, geometry-only, attribute-only, and combined modifications. The former accepted release becomes `superseded`; its source file and every `source_building` row remain unchanged. Exactly one building release remains accepted.

## Candidate-build contract

1. Preserve each source release unchanged.
2. Build a separate temporary GeoPackage.
3. Validate schema, integrity, foreign keys, migration hashes, source hashes, counts, and normalized identities.
4. Replace the accepted GeoPackage path only after the candidate validates.
5. Never mutate historical source feature rows.
6. Preserve prior releases inside the accepted database as superseded history.
7. Link derived calibration and indexes to the exact accepted source releases that produced them.

A failed build or refresh leaves the existing candidate and accepted databases unchanged.

## Stable identity

Source identifiers are retained but are not assumed to be permanent. Project-level feature identities will be assigned independently. Later refresh logic may match features using source IDs, geometry overlap, parcel identity, address, feature type, and content hashes.

## TrivialHTTP boundary

TrivialHTTP may later provide:

- read-only prepared queries;
- spatial lookup endpoints;
- database status and version information;
- controlled candidate-build and validation commands;
- export generation.

It must not expose unrestricted SQL to the browser. Command-line tools and TrivialHTTP must operate against the same database contract.
