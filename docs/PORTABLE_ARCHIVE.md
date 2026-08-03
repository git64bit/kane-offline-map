# Portable application archive

The portable archive is a deterministic ZIP with one root directory:

```text
kane-offline-map.zip
└── kane-offline-map/
```

Build directly from the accepted deployment-source GeoPackage:

```sh
bash deployment/build-deployment-archive.sh \
  /path/to/kane-county.gpkg \
  /path/to/kane-offline-map.zip
```

The pipeline creates a temporary prepared bundle beside the requested ZIP, validates all accepted datasets and output hashes, builds a candidate archive, validates every archived payload, promotes the ZIP, and removes the temporary directory.

The archive contains the browser runtime and complete prepared data:

```text
data/kane-county/
├── core-manifest.json
├── county_boundary.json
├── roads.json
├── water.json
└── buildings.json
```

The archive manifest records the exact source Git commit, every payload path, byte length, and SHA-256. Identical source and accepted database content produce identical prepared files; identical prepared files and source commit produce identical ZIP bytes.

The archive deliberately excludes two manual additions:

```text
data/reviews/current/
TrivialHTTP runtime files
```

It also excludes Git metadata, database tooling, tests, harvest files, GeoPackages, and development outputs. Existing ZIP output is refused unless `--force` is supplied; forced replacement occurs only after candidate validation.
