# Batch 011 — Authoritative ArcGIS Building Harvest Contract

Accepted base repository commit: `470b71e310cb46920efe68920e8739376aca5271`

## Scope

- Adds a tracked source profile for the public Kane County GIS building-footprint FeatureServer layer.
- Adds a standard-library ArcGIS REST harvester with no third-party package requirement.
- Retrieves the complete object-ID set first, then downloads exact bounded object-ID groups as EPSG:4326 GeoJSON.
- Uses `OBJECTID` only for complete snapshot retrieval and `FPId` for long-term stable building identity.
- Rejects missing or duplicate stable IDs instead of silently falling back to a system-maintained object ID.
- Validates current layer type, geometry type, fields, GeoJSON support, object-ID field, and record limit before retrieval.
- Writes deterministic GeoJSON plus a provenance manifest containing layer metadata, request contract, counts, hashes, and source edit timestamps.
- Builds output and manifest candidates before promotion and preserves an existing pair when retrieval or validation fails.
- Adds offline source-profile validation to the complete Linux verifier.
- Expands the database suite from 29 to 38 tests.

## Deliberate limits

- No live Kane County data is bundled or downloaded by verification.
- The first live harvest remains a separate operator action and must be inspected before database acceptance.
- The harvester does not infer a replacement identity when `FPId` is absent.
- Database schema, accepted classification, building history, spatial index, TrivialHTTP, and browser behavior are unchanged.
- Boundary, roads, water, parcel, and address harvesting remain outside this batch.

## Verify on Linux

```sh
bash verify-linux.sh
```

Verification validates the official source profile offline, exercises ArcGIS metadata and object-ID paging with deterministic synthetic responses, then runs the existing complete SQL and spatial fixture workflow. It does not contact ArcGIS and does not compile TrivialHTTP.
