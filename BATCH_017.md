# Batch 017 — Active-Sector Browser Review Layer

## Accepted parent

```text
1e385c56b8a543bf983b9f6fab3536609d11764f
```

## Scope

- Loads the accepted review-bundle index once.
- Loads and retains only the active sector review file.
- Verifies sector byte length and SHA-256 before parsing.
- Verifies classification identity and county-boundary calibration before displaying reviews.
- Displays review density at county, inspection, and practical-cell levels.
- Adds county, sector, and inspection review counts to the interface.
- Treats a missing or invalid review bundle as nonfatal.
- Adds seven browser-contract tests, increasing the suite from 74 to 81 tests.

## Exclusions

- No review status is modified.
- No GeoPackage write or TrivialHTTP SQL endpoint is added.
- No live county data or generated review bundle is committed.
- No prepared roads, water, or building source is changed.
- No Windows build or runtime packaging is performed.
