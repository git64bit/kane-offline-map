# ArcGIS Harvest Acceptance

## Purpose

Harvesting and SQL acceptance are separate operations.

The harvest command contacts the configured ArcGIS layer and creates two immutable files:

```text
kane-buildings.geojson
kane-buildings.geojson.manifest.json
```

Batch 012 adds the acceptance boundary between those files and the canonical GeoPackage. The database tools do not trust operator-entered release metadata for an ArcGIS harvest. They derive provenance only after the GeoJSON and manifest pair passes offline validation. Batch 013 applies the same immutable-pair validation to the county-boundary harvest. Batch 014 preserves the accepted boundary release and its two source-file records in SQL, links calibration to that exact release, and promotes only a fully validated candidate database.

## Validation contract

The acceptance validator requires:

- the tracked source-profile filename, profile key, and SHA-256;
- current layer metadata compatible with the profile;
- the layer-metadata SHA-256;
- an exact source summary derived from the profile and layer metadata;
- canonical UTF-8 JSON serialization for both files;
- the GeoJSON filename, byte length, SHA-256, and feature count;
- the complete sorted ArcGIS object-ID inventory and its SHA-256;
- exact page count from the recorded page size;
- unique object IDs and unique profile-defined stable IDs;
- `feature.id` equal to the stable ID (`FPId` for buildings, `OBJECTID` for the boundary);
- Polygon or MultiPolygon geometry only; and
- feature order matching ascending ArcGIS object ID.

Changing either file after harvest invalidates the pair. Equivalent but reserialized JSON is also rejected because the preserved source hash must identify exact bytes.

## Validate a completed live harvest

From the repository root:

```sh
bash database/validate-kane-building-harvest.sh \
  /absolute/path/kane-buildings.geojson
```

The manifest is found automatically beside the GeoJSON file.

A successful result prints derived acceptance metadata, including the deterministic release key. No database is changed. The county-boundary pair is validated with `database/validate-kane-boundary-harvest.sh` in the same manner.

## Build the first authoritative database

After inspection and validation:

```sh
bash database/build-kane-harvest-database.sh \
  /absolute/path/kane-buildings.geojson \
  /absolute/path/kane-county.gpkg
```

The command:

1. validates the harvest pair;
2. builds a separate candidate GeoPackage;
3. imports the completed field ledger;
4. imports the validated building release;
5. preserves both harvested files as source-file provenance;
6. validates the complete candidate; and
7. promotes the candidate only after success.

An existing output is refused unless `--force` is supplied deliberately.

## Accept the authoritative county boundary

After the building database and boundary pair have both validated:

```sh
bash database/accept-kane-boundary.sh \
  /absolute/path/kane-county.gpkg \
  /absolute/path/kane-boundary.geojson
```

The command copies the accepted database, applies pending migrations, preserves the boundary release and both source-file records, stores normalized boundary geometry, links grid calibration to that exact release, indexes the accepted buildings against the practical cells, validates the authoritative candidate, and atomically promotes it. A failure leaves the existing database unchanged.

```sh
bash database/validate-authoritative-database.sh \
  /absolute/path/kane-county.gpkg
```

Boundary refresh and supersession are intentionally outside Batch 014.

## Refresh a later authoritative release

Harvest a new pair to a new filename, inspect it, then run:

```sh
bash database/refresh-kane-harvest-database.sh \
  /absolute/path/kane-county.gpkg \
  /absolute/path/kane-buildings-NEW.geojson
```

The refresh validates the new pair before copying or changing the accepted database. It then uses the existing candidate-safe comparison and supersession workflow. A failed pair or failed candidate leaves the accepted GeoPackage byte-for-byte unchanged.

## SQL provenance

For an accepted ArcGIS building release:

- `source_release.release_key` is derived from source edit date and GeoJSON hash;
- `source_release.source_version` stores `arcgis-profile-sha256:` followed by the tracked profile SHA-256;
- `source_release.source_published_at` comes from the ArcGIS data edit timestamp when available;
- `source_release.harvested_at` comes from the harvest manifest;
- `source_release.source_uri` comes from the source profile;
- one `source_file` row preserves the GeoJSON metadata and hash; and
- one `source_file` row preserves the manifest metadata and hash.

The source files remain external immutable evidence. The database stores their identities and normalized feature content; it does not embed the original file bytes.

## Offline verification

`bash verify-linux.sh` does not contact ArcGIS. Unit tests create deterministic synthetic harvest pairs through the same harvester, validate them, import the first pair, refresh with a second pair, and confirm provenance and failure isolation.
