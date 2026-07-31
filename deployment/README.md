# Portable archive builder

The deployment builder creates a deterministic `kane-offline-map.zip` whose only top-level directory is `kane-offline-map/`.

It accepts a prepared browser-data directory containing:

- `county_boundary.json`
- `roads.json`
- `water.json`
- `buildings.json`

The archive includes the browser application and those four prepared files. It deliberately excludes the external `data/reviews/current/` bundle and operating-system-specific TrivialHTTP runtime files.

```sh
bash deployment/build-portable-archive.sh \
  /path/to/prepared-data \
  /path/to/kane-offline-map.zip
```

The builder refuses to overwrite an existing archive unless `--force` is supplied. Replacement is candidate-built and validated before promotion.

The ZIP is deterministic for an unchanged source commit and unchanged prepared data. `PORTABLE_MANIFEST.json` records the source commit and the exact byte length and SHA-256 digest of every packaged payload file.
