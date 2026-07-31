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

The completed field classification is preserved in `database/input/sectors.zip` as an immutable migration source. Batch 006 imports it into a GeoPackage/SQLite database for continuing SQL and spatial development. Batch 007 establishes the Kane Offline Map project identity and Git-native Linux delivery workflow. Batch 008 adds the first native source-geometry table and a repeatable building GeoJSON import contract. Batch 009 adds candidate-safe building refresh, release comparison, and supersession without overwriting prior feature history. Batch 010 calibrates the completed practical-cell grid from the same county boundary used by the browser, creates exact building-to-cell intersection rows, and opens review records when new or spatially changed buildings intersect muted cells. Batch 011 adds a deterministic ArcGIS REST harvest contract for the public Kane County GIS building-footprint layer, using `FPId` as the stable source identity and producing a hashed provenance manifest beside every harvested GeoJSON release. Batch 012 validates the building GeoJSON/manifest pair as one immutable source release, derives SQL provenance from that pair, and adds candidate-safe first-build and later-refresh commands. Batch 013 adds a separate one-feature ArcGIS harvest contract for the official county boundary. Batch 014 preserves that validated boundary pair in SQL, links the practical-grid calibration to the exact accepted release, and builds the authoritative building-to-cell index through candidate validation and promotion.

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

1. verifies tracked source checksums and the complete application tree;
2. validates the official Kane County building and county-boundary source profiles without network access;
3. validates synthetic ArcGIS GeoJSON/manifest pairs and their SQL provenance;
4. creates a candidate GeoPackage from the completed ledger and a synthetic first building release;
5. calibrates the practical-cell grid from a synthetic county boundary;
6. refreshes that database with a synthetic second building release;
7. validates release history, exact building-cell intersections, and muted-cell review triggers;
8. exercises candidate-safe authoritative boundary acceptance with synthetic inputs; and
9. runs the database, harvest-acceptance, and ArcGIS-harvest test suite.

It does not contact ArcGIS, compile TrivialHTTP, or require a C compiler.

Generated binaries, GeoPackages, and Python cache files are build products and are not part of the source archive.

## TrivialHTTP

TrivialHTTP source is included but is outside the database verification path. Build it only on a Linux host configured for C development.

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
bash database/validate-source-profile.sh
bash database/harvest-kane-buildings.sh /path/to/kane-buildings.geojson
bash database/validate-kane-building-harvest.sh /path/to/kane-buildings.geojson
bash database/harvest-kane-boundary.sh /path/to/kane-boundary.geojson
bash database/validate-kane-boundary-harvest.sh /path/to/kane-boundary.geojson
bash database/accept-kane-boundary.sh /path/to/kane-county.gpkg /path/to/kane-boundary.geojson
bash database/validate-authoritative-database.sh /path/to/kane-county.gpkg
bash database/build-kane-harvest-database.sh /path/to/kane-buildings.geojson /path/to/kane-county.gpkg
bash database/refresh-kane-harvest-database.sh /path/to/kane-county.gpkg /path/to/new-kane-buildings.geojson
bash database/build-ledger-database.sh
bash database/validate-ledger-database.sh
bash database/build-building-database.sh /path/to/buildings.geojson RELEASE_KEY
bash database/calibrate-spatial-database.sh /path/to/county_boundary.json
bash database/refresh-building-database.sh /path/to/new-buildings.geojson NEW_RELEASE_KEY
bash database/validate-building-database.sh
bash database/validate-spatial-database.sh
bash database/run-tests.sh
```

The generated candidate database is:

```text
project-data/database/kane-county-build.gpkg
```

## Batch 004 behavior

Opening an 8 × 8 practical grid changes only its still-undiscovered cells to Discovered/green. Existing muted/black cells remain muted. The grid is saved as one classification change group rather than 64 separate actions.
