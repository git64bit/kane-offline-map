# Portable archive contract

The final USB deliverable is a ZIP containing one new application directory:

```text
kane-offline-map/
```

It is independent of the existing `county-field-map/` application.

## Included by the builder

- browser runtime files;
- prepared `county_boundary.json`, `roads.json`, `water.json`, and `buildings.json`;
- writable `project-data/sectors/` location;
- `PORTABLE_MANIFEST.json` with the exact Git source identity and SHA-256 digest of each payload file;
- deployment notes and the expected browser URL.

## Deliberately external

- `data/reviews/current/`;
- operating-system-specific TrivialHTTP runtime files.

These two items are omitted by contract and are recorded in both the portable manifest and deployment README.

## Candidate promotion

The builder writes a temporary candidate ZIP, reopens it, validates every manifest path, byte length, and SHA-256 digest, and only then replaces the requested output. An existing output is preserved unless `--force` is supplied and the new candidate passes validation.

## Determinism

All paths are sorted, ZIP timestamps are fixed, permissions are normalized, JSON is canonicalized, and the source commit is explicit. Unchanged inputs produce identical ZIP bytes.
