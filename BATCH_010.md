# Batch 010 — Practical-Cell Spatial Index and Review Triggers

Accepted base repository commit: `806be4f195e47be945214315a8998c5eac88b15f`

## Scope

- Adds migration `0007_spatial_cell_index.sql`.
- Calibrates the completed classification grid from the same county-boundary extent and fitted projection used by the browser.
- Exposes all 262,144 practical-cell rectangles in EPSG:4326 through `classification_cell_spatial` without duplicating the classification ledger.
- Decodes the project-generated GeoPackage Polygon and MultiPolygon geometry in pure Python.
- Uses bounding boxes only to select candidate cells, then records exact geometry/rectangle intersections in `building_cell_relation`.
- Respects Polygon holes when calculating intersections.
- Indexes the current accepted building release when the grid is first calibrated.
- Automatically indexes every later accepted building release during refresh.
- Creates open `classification_review` rows when initial, added, geometry-changed, or fully modified buildings intersect muted or undiscovered cells.
- Does not create spatial reviews for removed, unchanged, or attribute-only changes.
- Builds calibration in a temporary candidate and preserves the accepted database if calibration or validation fails.
- Expands the database suite from 22 to 29 tests.

## Deliberate limits

- No authoritative Kane County boundary or building source is bundled or harvested.
- The included boundary and building GeoJSON files are synthetic verification fixtures only.
- Calibration requires EPSG:4326 Polygon or MultiPolygon county-boundary GeoJSON.
- Review rows are requests for classification review; this batch does not automatically change the accepted field ledger.
- Building clustering, road graph construction, and browser SQL endpoints remain outside this batch.
- TrivialHTTP and the browser application are unchanged.

## Verify on Linux

```sh
bash verify-linux.sh
```

Verification builds the completed ledger, imports the synthetic first building release, calibrates the practical grid, refreshes to the synthetic second release, validates the exact spatial index and review triggers, and runs all 29 tests. No compiler is used.
