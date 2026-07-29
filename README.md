# Kane Offline Map

Reduces the county map to roads, water and buildings.

Kane Offline Map is a single-purpose, cross-platform, offline county classification and spatial SQL application. It divides Kane County into 16 main sectors, each sector into a 16 × 16 inspection grid, and each inspection cell into an 8 × 8 practical grid.

## Classification

- Gray: undiscovered
- Green: discovered; the cell contains useful roads, water, or buildings
- Black: muted void; the cell contains no useful information

Clicking a practical cell marks it discovered. Shift-clicking marks it muted immediately. Select a cell and use **Mute selected sector** to mark it black. **Return to undiscovered** corrects a classification.

At the final 8 × 8 level, **Mute all 64 cells** marks the entire current inspection grid as muted after confirmation.

An inspection cell turns green when all 64 practical cells are classified. A main sector turns green when all 256 inspection cells are complete.

## Prepared field data

Place these read-only GeoJSON files together in one folder:

- `county_boundary.json`
- `roads.json`
- `water.json`
- `buildings.json`

The default folder is `processing/output/prepared`. The loader also checks `data/kane-county`, `data`, and `prepared`. A different folder can be supplied in the URL:

```text
?bundle=/path/to/prepared-data
```

The prepared geographic files are external harvested inputs. They are not stored in this source archive.

## Classification storage

The browser keeps a compact local safety journal. When the included TrivialHTTP server is used, the 16 sector ledgers are also written under:

```text
project-data/sectors/
```

The completed field classification is preserved in `database/input/sectors.zip` as an immutable migration source. Batch 006 imports it into a GeoPackage/SQLite database for continuing SQL and spatial development. Batch 007 establishes the Kane Offline Map project identity and Git-native Linux delivery workflow.

## Development and delivery environment

All development, database construction, validation, and packaging are performed on Linux. Development batches are delivered as Git format-patch files and applied on the Linux node with `git am`.

Windows is a final offline runtime target only. Nothing in the database development workflow is built or executed on Windows. The final Windows TrivialHTTP binary is produced separately on a properly configured Linux build host. The database development node does not need a C compiler.

Do not rely on executable permission bits surviving ZIP extraction or browser upload. Invoke shell scripts explicitly with `bash`:

```sh
bash verify-linux.sh
```

## Complete Linux database verification

From the application root:

```sh
bash verify-linux.sh
```

This command:

1. verifies that the complete application source tree is present;
2. creates the candidate GeoPackage from the completed ledger;
3. validates the accepted ledger; and
4. runs the database test suite.

It does not compile TrivialHTTP and does not require a C compiler.

Generated binaries, GeoPackages, and Python cache files are build products and are not part of the source archive.

## TrivialHTTP

TrivialHTTP source is included but is outside the Batch 006 verification path. Build it only on a Linux host configured for C development.

Linux build:

```sh
bash trivialhttp/scripts/build-linux.sh
```

Windows final-runtime cross-build from Debian or Ubuntu:

```sh
sudo apt install gcc-mingw-w64-x86-64
bash trivialhttp/scripts/build-windows-mingw.sh
```

Run the Linux executable from the application root:

```sh
trivialhttp/build/trivialhttp --root .
```

## Database commands

```sh
bash database/build-ledger-database.sh
bash database/validate-ledger-database.sh
bash database/run-tests.sh
```

The generated candidate database is:

```text
project-data/database/kane-county-build.gpkg
```

## Batch 004 behavior

Opening an 8 × 8 practical grid changes only its still-undiscovered cells to Discovered/green. Existing muted/black cells remain muted. The grid is saved as one classification change group rather than 64 separate actions.
