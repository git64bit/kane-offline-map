# Batch 015 — Open Review GeoJSON Export

## Accepted parent

```text
3450f8f8999f30c6cd8d2a1b13f0ebdbc61b556b
```

## Scope

- Adds a read-only export for open building-triggered classification reviews.
- Groups review rows by practical cell and emits one EPSG:4326 polygon feature per cell.
- Preserves exact accepted classification, building, county-boundary, calibration, and database hashes in the export metadata.
- Includes the triggering building identifiers and review identifiers for each cell.
- Produces canonical JSON through a temporary candidate and promotes it only after validation.
- Refuses to replace an existing export unless `--force` is explicit.
- Adds seven tests, increasing the suite from 59 to 66 tests.

## Exclusions

- No classification review is accepted, dismissed, deferred, or otherwise mutated.
- No authoritative source release or GeoPackage row is changed.
- No browser or TrivialHTTP behavior is changed.
- No live county data or generated review export is committed.
