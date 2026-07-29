# Batch 006 — Completed Ledger SQL Import

Accepted base repository commit: `5026482f8e9c390f80fd8e19b67e292e2763b021`

This replacement archive is the complete County Field Map application, not a delta. It combines the accepted Batch 004 application, the accepted Batch 005 SQL foundation, and the tested Batch 006 completed-ledger import.

## Delivery contract

- The ZIP is complete and may be extracted into an empty directory.
- No prior application tree is required.
- Linux is the only development and test platform.
- Windows is a final offline runtime target only.
- Shell scripts are invoked with `bash`; executable permission bits are not assumed.
- Generated GeoPackages, compiled binaries, `.pyc` files, and `__pycache__` directories are excluded.
- The verification workflow requires Python 3.9 or newer, but no C compiler or binary build environment.
- Windows database development launchers are excluded.

## Functional scope

- Preserves `database/input/sectors.zip` as the immutable baseline source archive.
- Adds a strict legacy and current sector-state archive parser.
- Imports all 16 sectors and 262,144 practical cells into SQL.
- Records archive and per-sector SHA-256 hashes.
- Normalizes every cell to a 512 × 512 county-global grid.
- Creates one accepted classification release.
- Adds an atomic candidate builder: failed builds do not replace the existing candidate.
- Adds accepted-ledger validation and database metadata reporting.
- Expands the test suite from 4 to 9 tests.
- Does not add feature geometry.
- Does not alter the finished browser application or TrivialHTTP behavior.

## Complete database verification

From the application root:

```sh
bash verify-linux.sh
```

The verifier checks the complete source tree and exercises only the database layer. It does not compile TrivialHTTP.

Individual database commands remain available:

```sh
bash database/build-ledger-database.sh
bash database/validate-ledger-database.sh
bash database/run-tests.sh
```

The generated candidate is:

```text
project-data/database/kane-county-build.gpkg
```

Expected accepted classification totals:

```text
16 sectors
4,096 inspection cells
262,144 practical cells
72,705 discovered
189,439 muted
0 undiscovered
```

## Repository cleanup

Generated files already present in the repository are not part of this complete source archive. They may be removed during repository cleanup:

```text
database/tests/__pycache__/
database/tools/__pycache__/
project-data/database/*.gpkg
trivialhttp/build/
```
