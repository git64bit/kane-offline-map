# Batch 007 — Project Identity and Git-Native Delivery

Accepted base repository commit: `7a7ce01279dcdf526982c3a74c262d59ccca1fc1`

## Scope

- Renames the active project and browser interface to **Kane Offline Map**.
- Updates TrivialHTTP messages and current documentation to the new identity.
- Retains the existing storage formats, local browser keys, and HTTP endpoints for backward compatibility.
- Changes the database project identity to `kane-offline-map` and validates it.
- Adds a regression test for project-identity tampering.
- Repairs the tracked source checksum manifest and validates it in `verify-linux.sh`.
- Establishes Git format-patch as the standard Linux delivery mechanism.

No classification data, geometry, storage format, endpoint path, or database schema is changed.

## Apply on Linux

The working tree must be clean and at the accepted base commit.

```sh
git status --short
git rev-parse HEAD
git am --3way /path/to/kane-offline-map-batch-007.patch
```

If application fails:

```sh
git am --abort
```

## Verify and publish

```sh
bash verify-linux.sh
git status --short
git push origin main
```

The verification run creates ignored local database and Python cache artifacts. They are not committed.
