# Batch 012 — Authoritative Harvest Acceptance Boundary

Accepted base repository commit: `14700f6338246086dfe83567d12e7119da556a0e`

## Scope

- Adds offline validation of a harvested GeoJSON release together with its ArcGIS provenance manifest.
- Requires exact profile, layer metadata, source summary, output hash, byte length, feature count, object-ID inventory, stable IDs, feature order, page count, and canonical serialization.
- Derives the SQL release key, source URI, source publication timestamp, harvest timestamp, stable-ID property, and source-profile hash from the validated manifest rather than operator-entered values.
- Adds candidate-safe commands for building the first authoritative building database and refreshing later authoritative building releases.
- Preserves both the GeoJSON release and its manifest as immutable `source_file` provenance rows.
- Keeps the existing generic fixture import commands for deterministic testing and non-ArcGIS adapters.
- Expands the database test suite from 38 to 46 tests.

## Deliberate limits

- No live Kane County data is bundled, downloaded, or imported by verification.
- The operator still performs the first live harvest as a separate network action.
- County-boundary acceptance remains separate because the current building FeatureServer does not define the classification-grid boundary.
- Roads, water, parcels, addresses, browser SQL access, and TrivialHTTP database endpoints remain outside this batch.
- No SQL migration is required; Batch 012 uses the existing source-release, source-file, and harvest-run schema.

## Verify on Linux

```sh
bash verify-linux.sh
```

Verification remains offline. It validates the official source profile, exercises synthetic harvested GeoJSON/manifest acceptance, preserves both source files in SQL, tests a second accepted harvest refresh, and runs the existing ledger, building, spatial, and ArcGIS suites.
