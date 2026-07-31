# Authoritative ArcGIS Harvest

## Purpose

The ArcGIS acquisition layer creates immutable GeoJSON snapshots before any source can enter the offline SQL workflow. Each successful harvest produces canonical GeoJSON plus a hashed provenance manifest. Offline validation treats the pair as one source release.

Tracked source profiles:

```text
database/sources/kane-county-buildings.json
database/sources/kane-county-boundary.json
```

Configured official layers:

```text
https://services1.arcgis.com/oRKmdBXD6EbdmVgJ/ArcGIS/rest/services/KaneCo_IL_BuildingFootprints/FeatureServer/0
https://services1.arcgis.com/oRKmdBXD6EbdmVgJ/ArcGIS/rest/services/County_Boundary/FeatureServer/0
```

## Identity policy

Building snapshots use the system-maintained `OBJECTID` only for complete ordered retrieval. The county `FPId` field is required as the stable release-to-release building identity.

The county-boundary profile requires exactly one polygon feature. Its `OBJECTID` is sufficient as the snapshot identity because the source contract represents one county-wide geometry, not a collection of independently tracked features.

A candidate is rejected for missing or duplicate identities, unsupported geometry, an object-ID mismatch, a schema mismatch, or a feature count that violates the tracked profile.

## Retrieval method

The standard-library harvester:

1. requests current layer metadata;
2. retrieves and sorts the complete object-ID inventory with `returnIdsOnly=true`;
3. verifies any tracked expected feature count;
4. requests exact bounded ID groups as GeoJSON with `outSR=4326`; and
5. writes canonical GeoJSON and a canonical manifest through candidate files.

Explicit object-ID groups avoid dependence on offset pagination. Every returned page must exactly match the requested IDs.

## Commands

Validate both tracked profiles without network access:

```sh
bash database/validate-source-profile.sh
```

Harvest buildings:

```sh
bash database/harvest-kane-buildings.sh /absolute/path/kane-buildings.geojson
```

Harvest the county boundary:

```sh
bash database/harvest-kane-boundary.sh /absolute/path/kane-boundary.geojson
```

Add `--force` only when deliberately replacing an existing output pair.

Validate completed pairs offline:

```sh
bash database/validate-kane-building-harvest.sh /absolute/path/kane-buildings.geojson
bash database/validate-kane-boundary-harvest.sh /absolute/path/kane-boundary.geojson
```

The commands use Python's standard library. No compiler, GDAL installation, or third-party Python package is required.

## Manifest contents

Each sidecar records the source-profile hash, complete layer metadata and hash, source edit timestamps, query contract, object-ID inventory hash, page and feature counts, output byte length and SHA-256, and harvest timestamp.

The output and manifest are promoted only after the complete candidate succeeds. Network, schema, identity, geometry, and count failures leave an existing pair unchanged.

## Deliberate limits

Batch 014 accepts a validated county-boundary pair through a copied candidate database. It preserves the source release and normalized geometry, links the exact source hash to grid calibration, rebuilds the accepted building-cell index, validates the result, and promotes it atomically. Live source data and generated GeoPackages remain external to Git.
