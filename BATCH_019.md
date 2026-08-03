# Batch 019 — Authoritative prepared-core export

Accepted base repository commit: `480b856c3e896aed359ffe5d6cb489ea1507bed0`

Batch 019 exports the accepted county boundary and accepted building release from the authoritative GeoPackage into deterministic browser GeoJSON.

The output is a candidate-built directory containing `county_boundary.json`, `buildings.json`, and `core-manifest.json`. The manifest binds both browser files to their accepted SQL release identities and to the exact source-database hash.

The export is deliberately marked incomplete. It cannot be mistaken for the final four-file browser bundle because authoritative roads and water remain unresolved.

The exporter is read-only, refuses accidental overwrite, validates a replacement candidate before promotion, and preserves the accepted GeoPackage byte-for-byte.
