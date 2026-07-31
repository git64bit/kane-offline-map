# Batch 016 — Sectorized Open Review Bundle

## Accepted parent

```text
4cec9c2e922148873ed3bc5ed10f845608048bb0
```

## Scope

- Adds a deterministic open-review bundle for active-sector consumers.
- Writes one canonical GeoJSON file for each of the 16 county sectors.
- Writes a canonical index with exact path, byte-length, hash, and count metadata for every sector file.
- Preserves accepted classification, building, boundary, calibration, and source-database identities.
- Validates all cross-file identities, hashes, counts, feature ownership, and canonical serialization before promotion.
- Preserves an existing accepted bundle unless explicit `--force` replacement succeeds.
- Adds seven tests, increasing the suite from 66 to 73 tests.

## Exclusions

- No browser behavior is changed.
- No TrivialHTTP endpoint is added.
- No review is accepted, dismissed, deferred, or otherwise mutated.
- No authoritative GeoPackage row or source release is changed.
- No live county data, generated GeoPackage, or generated review bundle is committed.
