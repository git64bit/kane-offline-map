# Batch 013 — Authoritative County-Boundary Harvest

## Accepted parent

```text
1930d49145e70a93e47591a7d117131dd707a0a0
```

## Scope

- Adds a tracked ArcGIS profile for the official Kane County boundary layer.
- Requires exactly one Polygon or MultiPolygon feature.
- Adds live harvest and offline pair-validation wrappers.
- Extends generic source profiles with an optional positive expected feature count.
- Derives release keys from each profile's dataset key while preserving the existing building key format.
- Keeps all normal Linux verification offline.
- Adds six tests, increasing the suite from 46 to 52 tests.

## Exclusions

- No live county-boundary data is committed.
- No accepted database is calibrated in this batch.
- No database schema or TrivialHTTP behavior changes.
