# Batch 023 — Complete prepared bundle and deployment archive pipeline

Accepted base repository commit: `ab826e9c7c5af4d02cb21c0d06530581e42e7d2a`

Batch 023 completes the browser-data export from the accepted deployment-source GeoPackage. The deterministic export now contains `county_boundary.json`, `roads.json`, `water.json`, `buildings.json`, and `core-manifest.json`. The manifest records all five accepted source releases, exact output hashes and byte lengths, feature counts, and the authoritative database hash. It is marked complete only after deployment-source validation requires accepted classification, buildings, boundary, roads, Fox River, and creeks.

The geometry decoder now supports LineString, MultiLineString, Polygon, and MultiPolygon GeoPackage values. Road attributes are retained for browser styling. Fox River polygons and creek lines are combined into one deterministic `water.json`; the browser renders creek lines separately in the water color.

The portable archive builder now requires and verifies the complete prepared manifest. A partial or tampered prepared directory cannot be packaged. `deployment/build-deployment-archive.sh` exports a disk-backed candidate beside the requested ZIP, validates it, builds the deterministic application archive, and removes the temporary prepared directory.

The generated ZIP still excludes `data/reviews/current/` and platform-specific TrivialHTTP runtime files by contract. Those remain the two manual additions previously agreed.
