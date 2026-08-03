# Prepared core export

The authoritative GeoPackage now supplies the two accepted polygon datasets needed by the browser:

- `county_boundary.json`
- `buildings.json`

Create the deterministic partial browser-data directory with:

```sh
bash database/export-prepared-core.sh \
  /path/to/kane-county.gpkg \
  /path/to/prepared-core
```

The directory also contains `core-manifest.json`, recording the exact accepted release keys, source content hashes, output hashes, feature counts, and source-database hash.

This is not yet a deployable browser bundle. The manifest explicitly records:

```text
complete_browser_bundle: false
remaining_datasets: roads, water
```

The portable ZIP builder must not be pointed at this partial directory. A later bounded batch will add authoritative roads and water and promote the four-file prepared bundle.
