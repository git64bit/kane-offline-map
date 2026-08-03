# Road and Water SQL Acceptance

Kane Offline Map accepts the road-centerline, Fox River, and creek harvests as one candidate-safe operation. The three validated GeoJSON/manifest pairs remain external immutable evidence; their filenames, byte lengths, SHA-256 hashes, source profile versions, publication timestamps, harvest timestamps, source URIs, and any audited missing-geometry exclusions are preserved in the GeoPackage.

## Required inputs

The command requires exactly these tracked contracts:

- `database/sources/kane-county-roads.json`
- `database/sources/kane-county-fox-river.json`
- `database/sources/kane-county-creeks.json`

Each GeoJSON must already have its adjacent `.manifest.json` sidecar.

## Accept into the authoritative database

```sh
bash database/accept-kane-map-layers.sh \
  /path/to/kane-county.gpkg \
  /path/to/kane-roads.geojson \
  /path/to/kane-fox-river.geojson \
  /path/to/kane-creeks.geojson
```

The command validates all three harvest pairs before copying the accepted database. It then upgrades the copy, imports all three releases in one transaction, validates the complete candidate, and replaces the accepted database only after success.

## Validate the deployment source database

```sh
bash database/validate-deployment-database.sh /path/to/kane-county.gpkg
```

This requires accepted classification, buildings, county boundary, roads, Fox River, and creeks. It does not require or inspect a browser bundle.

## Geometry storage

Roads and creeks are stored as EPSG:4326 LineString or MultiLineString features. Source road records explicitly listed as missing-geometry exclusions are preserved in harvest provenance but cannot produce a spatial row. The Fox River is stored as EPSG:4326 Polygon or MultiPolygon features. Every row carries its stable source ID, source ordinal, GeoPackage geometry BLOB, canonical attribute JSON, per-part hashes, complete content hash, and numeric bounds.

Road and water refresh is intentionally refused until a later batch defines comparison and supersession semantics.
