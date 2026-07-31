# Batch 014 — Authoritative County-Boundary Acceptance

## Accepted parent

```text
64dbb183df80e0ba8b5b7d89c7d675cc947d6383
```

## Scope

- Adds `source_county_boundary` as a native GeoPackage feature table.
- Preserves the validated boundary GeoJSON and manifest as one immutable source release.
- Links grid calibration to the exact accepted boundary release, file hash, byte length, and extent.
- Sets Kane County's canonical spatial reference to EPSG:4326.
- Rebuilds exact building-to-practical-cell relations for the accepted building release.
- Opens review records where accepted buildings intersect muted or undiscovered cells.
- Uses a copied candidate database and promotes it only after authoritative validation succeeds.
- Adds a dedicated authoritative-database validator and command wrappers.
- Adds seven tests, increasing the suite from 52 to 59 tests.

## Exclusions

- No live county data or generated GeoPackage is committed.
- Boundary release refresh and supersession are not implemented in this batch.
- TrivialHTTP behavior is unchanged.
