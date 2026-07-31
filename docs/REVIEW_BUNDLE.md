# Sectorized Open Review Bundle

Batch 016 converts the authoritative open-review layer into a directory that can be consumed one county sector at a time. It is a read-only derivative of the accepted GeoPackage and does not resolve, dismiss, or alter a review.

## Command

```sh
bash database/export-open-review-bundle.sh \
  /path/to/kane-county.gpkg \
  /path/to/kane-open-review-bundle
```

An existing bundle is not replaced unless `--force` is explicit.

## Directory contract

```text
kane-open-review-bundle/
  index.json
  sectors/
    N11-E06.geojson
    ...
    N14-E09.geojson
```

All 16 sector files are always present, including empty sectors. The index records each relative path, byte length, SHA-256 digest, review count, and review-cell count. It also preserves the accepted classification, building, boundary, calibration, and source-database identities.

Each sector file is canonical UTF-8 GeoJSON containing only review cells from that sector. The feature properties remain identical to the single-file Batch 015 export, including practical-cell identity, current classification, review identifiers, triggering building identifiers, detection time, and source release identifiers.

The exporter validates the authoritative database first, reads it without write access, creates a complete temporary directory, validates every file and cross-file count, and promotes the directory only after success. A failed candidate leaves an existing accepted bundle unchanged.
