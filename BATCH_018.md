# Batch 018 — Deterministic portable archive builder

Batch 018 establishes the packaging boundary for the new Kane Offline Map application.

The builder creates one `kane-offline-map.zip` with one top-level `kane-offline-map/` directory. It packages the browser application and an externally prepared four-file county-data bundle while excluding development files, the review bundle, and operating-system-specific TrivialHTTP runtime files.

The archive is deterministic, candidate-built, and validated before replacement. Its manifest records the exact source commit and the byte length and SHA-256 digest of every payload file.

This batch does not create the final USB archive because the authoritative prepared browser-data bundle is not yet produced by the repository workflow.
