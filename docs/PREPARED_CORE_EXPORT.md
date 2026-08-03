# Complete prepared browser bundle

Batch 023 exports the complete accepted browser-data bundle directly from the deployment-source GeoPackage. The database must contain accepted classification, buildings, county boundary, roads, Fox River, and creeks.

Create the deterministic directory with:

```sh
bash database/export-prepared-core.sh \
  /path/to/kane-county.gpkg \
  /path/to/prepared-browser-data
```

The output contains:

```text
prepared-browser-data/
├── core-manifest.json
├── county_boundary.json
├── roads.json
├── water.json
└── buildings.json
```

`water.json` combines accepted Fox River polygons and creek centerlines while retaining each feature's source dataset identity. Road attributes are preserved for browser styling. Every geometry is decoded from the accepted GeoPackage rather than copied from a harvest file.

The canonical manifest records the authoritative database SHA-256 and byte length, accepted release identities, source-content hashes, output hashes, output byte lengths, and feature counts. A valid export records:

```text
complete_browser_bundle: true
remaining_datasets: []
```

The export is candidate-built and validated before promotion. Existing output is refused unless `--force` is supplied, and the authoritative GeoPackage is opened read-only and remains byte-for-byte unchanged.
