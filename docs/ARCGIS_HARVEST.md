# Authoritative ArcGIS Building Harvest

## Purpose

Batch 011 adds a repeatable acquisition boundary between the public Kane County GIS service and the local, offline SQL workflow. Harvesting is a separate operation from importing. A successful harvest creates an immutable GeoJSON release plus a provenance manifest. Batch 012 requires the pair to pass a separate offline acceptance contract before either file can become SQL provenance.

The configured source is the Kane County GIS building-footprint FeatureServer layer:

```text
https://services1.arcgis.com/oRKmdBXD6EbdmVgJ/ArcGIS/rest/services/KaneCo_IL_BuildingFootprints/FeatureServer/0
```

The source profile is tracked at:

```text
database/sources/kane-county-buildings.json
```

## Identity policy

The ArcGIS layer advertises `OBJECTID` as its system-maintained object ID and does not advertise a GlobalID. System-maintained object IDs are used only to retrieve one complete, ordered snapshot. Long-term feature identity uses the county field `FPId`.

The harvester rejects the complete candidate when any feature has:

- a missing or empty `FPId`;
- a duplicate `FPId`;
- an invalid or duplicate `OBJECTID`;
- an unsupported geometry type; or
- an object-ID mismatch between the requested page and returned page.

It does not silently replace `FPId` with `OBJECTID`. A live source that violates the identity contract must be examined before it can enter the refresh history.

## Retrieval method

The harvester uses the ArcGIS REST query operation in two stages:

1. `returnIdsOnly=true` retrieves and sorts the complete object-ID set.
2. The IDs are divided into bounded groups and queried as GeoJSON with `outSR=4326`.

Using explicit object-ID groups avoids depending on changing page offsets. Every returned group must exactly match the requested object IDs. The profile page size is also capped by the layer's current `maxRecordCount` metadata.

The output is canonical UTF-8 GeoJSON. Features are ordered by `OBJECTID`, and each GeoJSON `feature.id` is set to the stable `FPId` string. This lets the existing building importer use the stable identity without rewriting source attributes.

## Harvest command

The harvest is intentionally not part of `verify-linux.sh`, because source access may be unavailable and verification must remain deterministic.

From the repository root:

```sh
bash database/harvest-kane-buildings.sh /absolute/path/kane-buildings.geojson
```

To deliberately replace an existing candidate pair:

```sh
bash database/harvest-kane-buildings.sh /absolute/path/kane-buildings.geojson --force
```

The command requires network access only during the harvest. It uses Python's standard library and does not require GDAL, a compiler, or third-party Python packages.

## Produced files

For an output named:

```text
kane-buildings.geojson
```

the harvester also creates:

```text
kane-buildings.geojson.manifest.json
```

The manifest records:

- the source-profile hash;
- complete ArcGIS layer metadata and its hash;
- source edit timestamps when advertised;
- query filter and output fields;
- complete object-ID set hash;
- page and feature counts;
- output byte length and SHA-256; and
- harvest timestamp.

The output and manifest are built as temporary candidates. Network, schema, identity, and geometry failures occur before promotion and leave an existing output pair unchanged.

## Offline profile validation

The tracked profile can be validated without contacting ArcGIS:

```sh
bash database/validate-source-profile.sh
```

This confirms the repository contract only. The live harvest separately verifies current layer metadata before downloading features, so incompatible source-schema changes are rejected rather than accepted silently.

## Acceptance after harvest

After inspecting the two output files, validate them together:

```sh
bash database/validate-kane-building-harvest.sh /absolute/path/kane-buildings.geojson
```

Then build the first authoritative database or refresh a later one using the commands in `docs/HARVEST_ACCEPTANCE.md`. The acceptance tools derive release metadata from the manifest; they do not ask the operator to retype source URI, publication time, stable-ID field, or release key.

## Deliberate limits

Batch 011 does not:

- bundle a live Kane County building harvest;
- import a harvested release into the GeoPackage automatically;
- infer an alternate stable identity when `FPId` is missing;
- harvest the county boundary, roads, water, parcels, or addresses; or
- add network behavior to TrivialHTTP or the browser application.
