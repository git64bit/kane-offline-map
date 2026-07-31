# Open Review GeoJSON Export

The authoritative database can contain open review rows when an accepted building footprint intersects a practical cell classified as muted or undiscovered. Batch 015 converts those SQL rows into a portable, read-only GeoJSON review layer.

## Command

```sh
bash database/export-open-reviews.sh \
  /path/to/kane-county.gpkg \
  /path/to/kane-open-review-cells.geojson
```

The command refuses to overwrite an existing output. An intentional replacement requires:

```sh
bash database/export-open-reviews.sh \
  /path/to/kane-county.gpkg \
  /path/to/kane-open-review-cells.geojson \
  --force
```

## Output contract

The output is canonical UTF-8 GeoJSON with one polygon feature per practical cell that has at least one open building-triggered review. Each feature contains:

- practical-cell and sector identity;
- global grid row and column;
- current classification;
- review count and review identifiers;
- triggering building identifiers;
- first detection timestamp; and
- source release identifiers.

Top-level metadata records the source database hash, byte length, accepted classification/building/boundary releases, calibration bounds, total open review count, unique review-cell count, and per-sector cell counts.

The exporter opens the GeoPackage read-only, validates the complete authoritative database first, writes a temporary candidate, validates canonical serialization and summary counts, and then promotes the candidate. It does not modify the database or resolve any review.
