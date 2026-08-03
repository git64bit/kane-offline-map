# Authoritative ArcGIS Harvest

## Purpose

The ArcGIS acquisition layer creates immutable GeoJSON snapshots before any source can enter the offline SQL workflow. Each successful harvest produces canonical GeoJSON plus a hashed provenance manifest. Offline validation treats the pair as one source release.

Tracked source profiles:

```text
database/sources/kane-county-buildings.json
database/sources/kane-county-boundary.json
database/sources/kane-county-roads.json
database/sources/kane-county-fox-river.json
database/sources/kane-county-creeks.json
```

The tracked services provide building polygons, one county-boundary polygon, road-centerline polylines, Fox River polygons, and creek polylines. All harvests request EPSG:4326 GeoJSON.

## Identity policy

Building snapshots use the system-maintained `OBJECTID` for complete ordered retrieval and the county `FPId` field as the stable release-to-release identity.

The county boundary, roads, Fox River, and creek profiles use the service-maintained `OBJECTID` as snapshot identity. These datasets are accepted as immutable source releases; later release comparison is based on their exact harvested content and provenance.

A candidate is rejected for missing or duplicate identities, unsupported or malformed geometry, an object-ID mismatch, a schema mismatch, or a feature count that violates the tracked profile. Missing geometry is also rejected unless the tracked profile explicitly selects the audited `exclude` policy and uses the ArcGIS object ID as its stable identity.

## Geometry policy

The harvester accepts only geometry matching the profile:

```text
esriGeometryPolygon  -> Polygon or MultiPolygon
esriGeometryPolyline -> LineString or MultiLineString
```

Polygon rings must be closed and contain at least four coordinate pairs. Line paths must contain at least two finite coordinate pairs.

The road-centerline profile uses `missing_geometry_policy: exclude` because the live service contains at least one source record without geometry. Only a null or absent geometry is excludable. Every excluded object ID is sorted, counted, and hashed in both output files. An empty object, malformed path, degenerate path, nonfinite coordinate, or wrong geometry type still rejects the candidate.

## Retrieval method

The standard-library harvester:

1. requests current layer metadata;
2. retrieves and sorts the complete object-ID inventory with `returnIdsOnly=true`;
3. verifies any tracked expected feature count;
4. requests exact bounded ID groups as GeoJSON with `outSR=4326`; and
5. writes canonical GeoJSON and a canonical manifest through candidate files.

Explicit object-ID groups avoid dependence on offset pagination. Every returned page must exactly match the requested IDs.

## Commands

Validate all tracked profiles without network access:

```sh
bash database/validate-source-profile.sh
```

Harvest and validate each source:

```sh
bash database/harvest-kane-buildings.sh /absolute/path/kane-buildings.geojson
bash database/validate-kane-building-harvest.sh /absolute/path/kane-buildings.geojson

bash database/harvest-kane-boundary.sh /absolute/path/kane-boundary.geojson
bash database/validate-kane-boundary-harvest.sh /absolute/path/kane-boundary.geojson

bash database/harvest-kane-roads.sh /absolute/path/kane-roads.geojson
bash database/validate-kane-road-harvest.sh /absolute/path/kane-roads.geojson

bash database/harvest-kane-fox-river.sh /absolute/path/kane-fox-river.geojson
bash database/validate-kane-fox-river-harvest.sh /absolute/path/kane-fox-river.geojson

bash database/harvest-kane-creeks.sh /absolute/path/kane-creeks.geojson
bash database/validate-kane-creek-harvest.sh /absolute/path/kane-creeks.geojson
```

Add `--force` only when deliberately replacing an existing output pair.

The commands use Python's standard library. No compiler, GDAL installation, or third-party Python package is required.

## Manifest contents

Each sidecar records the source-profile hash, complete layer metadata and hash, source edit timestamps, query contract, complete source object-ID inventory hash, page and spatial-feature counts, output byte length and SHA-256, and harvest timestamp. When the tracked policy permits missing-geometry exclusion, both the GeoJSON and manifest also record the exact excluded object IDs, count, reason, and hash.

The output and manifest are promoted only after the complete candidate succeeds. Network, schema, identity, geometry, and count failures leave an existing pair unchanged.

## Deliberate limits

Batch 020 establishes authoritative acquisition contracts for roads and water but does not accept them into SQL or merge the Fox River and creek releases into the browser `water.json` file. Those steps remain candidate-built and separate from live harvesting.
