# Batch 021 — Authoritative road and water SQL acceptance

Accepted base repository commit: `9b80e35cb04ec257d6d56b702378ca727e7dd470`

Batch 021 adds one atomic SQL acceptance boundary for the validated Kane County road-centerline, Fox River, and creek harvest pairs.

A new native GeoPackage feature table preserves immutable LineString, MultiLineString, Polygon, and MultiPolygon geometry with exact source identity, feature order, canonical attributes, bounds, content hashes, and source-file provenance. The three source releases are accepted together through a candidate database. If any harvest, import, or validation fails, the existing authoritative database is preserved byte-for-byte.

The public acceptance command requires exactly the three tracked source contracts. A separate deployment-source validator requires accepted classification, buildings, county boundary, roads, Fox River, and creeks. Refresh and supersession for road and water releases remain outside this batch.

Normal Linux verification remains fully offline. No live road or water source data, prepared browser bundle, TrivialHTTP runtime, or final deployment ZIP is included.
