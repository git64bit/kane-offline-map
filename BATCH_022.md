# Batch 022 — Audited missing-geometry exclusions

Accepted base repository commit: `da9770581aa92acfaa9552e297c392af66540309`

The first live road-centerline harvest reached the correct ArcGIS child layer and then failed closed at source record `OBJECTID` 25933 because the service returned that record without geometry.

Batch 022 adds a profile-controlled `missing_geometry_policy`. The default remains `reject`. The official road-centerline profile alone uses `exclude`, and that policy is permitted only when the stable source identity is the ArcGIS object ID.

A successful road harvest now preserves the complete ArcGIS object-ID inventory while excluding only records whose geometry is absent. The exact sorted excluded object IDs, count, reason, and SHA-256 are embedded in both the canonical GeoJSON and its provenance manifest. The GeoJSON hash therefore identifies the spatial features and the audited exclusion inventory together.

Malformed, degenerate, nonfinite, mismatched, or otherwise invalid non-null geometry still rejects the entire candidate. Missing identities, duplicate identities, page mismatches, and manifest tampering also remain fatal. SQL acceptance imports only spatial features while preserving the complete harvest pair and exclusion evidence as immutable source provenance.

Normal verification remains offline. No live road, Fox River, or creek release, GeoPackage change, prepared browser bundle, TrivialHTTP runtime, or deployment ZIP is included.
