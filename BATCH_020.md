# Batch 020 — Authoritative roads and water harvest contracts

Accepted base repository commit: `c75b27d0ded5b3d242c043152e96a67f974bbfe4`

Batch 020 extends the deterministic ArcGIS harvester from polygon-only releases to both polygon and polyline releases.

Tracked source profiles are added for the official Kane County road-centerline, Fox River, and creek services. Roads and creeks are harvested as LineString or MultiLineString geometry. The Fox River is harvested as Polygon or MultiPolygon geometry. Each profile uses the service-maintained `OBJECTID` as the snapshot identity and requests EPSG:4326 output.

The geometry validator rejects mismatched, degenerate, nonfinite, or structurally invalid line and polygon geometry before candidate promotion. Existing building and county-boundary contracts remain unchanged.

This batch adds only source acquisition and offline validation. It does not contact ArcGIS during normal verification, alter the authoritative GeoPackage, merge water layers, complete the prepared browser bundle, or produce the final USB ZIP.
