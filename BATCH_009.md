# Batch 009 — Building Release Refresh and Supersession

Accepted base repository commit: `d9e0b05493a1e100f57fb465fb81240437404a2c`

## Scope

- Adds migration `0006_building_refresh.sql`.
- Adds candidate-safe building refresh against an existing accepted GeoPackage.
- Upgrades a Batch 008 database copy before comparison; the accepted file is not altered unless the refresh validates.
- Compares releases by stable source feature ID.
- Classifies each identity as added, removed, unchanged, geometry changed, attributes changed, or modified in both respects.
- Stores complete comparison rows and summary counts.
- Marks the prior accepted source release as superseded and accepts the candidate atomically.
- Preserves all prior building feature rows and source provenance unchanged.
- Reports the latest comparison through database `info` output.
- Adds a synthetic second-release fixture for verification only.
- Expands the database suite from 16 to 22 tests.

## Deliberate limits

- No authoritative county building source is bundled or harvested.
- Matching is limited to exact stable source feature IDs.
- No geometry-overlap identity recovery is attempted when a source changes identifiers.
- No feature-to-classification-cell assignment, spatial index, or muted-cell review is performed yet.
- TrivialHTTP and the browser application are unchanged.

## Verify on Linux

```sh
bash verify-linux.sh
```

Verification builds the synthetic first release, refreshes it with a synthetic second release, validates the retained history and accepted candidate, and runs all 22 tests. No compiler is used.
