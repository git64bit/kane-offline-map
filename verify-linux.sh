#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"

required_files='
index.html
portable_config.js
src/app.js
src/constants.js
src/dataLoader.js
src/grid.js
src/renderer.js
src/stateStore.js
styles/app.css
trivialhttp/src/trivialhttp.c
trivialhttp/src/trivialhttp.h
trivialhttp/src/platform.c
trivialhttp/src/http.c
trivialhttp/src/sector_storage.c
database/input/sectors.zip
database/fixtures/buildings-sample.geojson
database/fixtures/buildings-refresh-v2.geojson
database/fixtures/county-boundary-sample.geojson
database/sources/kane-county-buildings.json
database/sources/kane-county-boundary.json
database/harvest-kane-buildings.sh
database/harvest-kane-boundary.sh
database/validate-kane-building-harvest.sh
database/validate-kane-boundary-harvest.sh
database/build-kane-harvest-database.sh
database/refresh-kane-harvest-database.sh
database/validate-source-profile.sh
database/accept-kane-boundary.sh
database/validate-authoritative-database.sh
database/export-open-reviews.sh
database/migrations/0005_source_buildings.sql
database/migrations/0006_building_refresh.sql
database/migrations/0007_spatial_cell_index.sql
database/migrations/0008_county_boundary.sql
database/calibrate-spatial-database.sh
database/refresh-building-database.sh
database/tools/county_db.py
database/tools/county_boundary.py
database/tools/county_cli.py
database/tools/county_arcgis.py
database/tools/county_geometry.py
database/tools/county_grid.py
database/tools/county_harvest.py
database/tools/county_buildings.py
database/tools/county_building_refresh.py
database/tools/county_ledger.py
database/tools/county_review_export.py
database/tools/county_spatial.py
database/tests/test_database.py
database/tests/test_buildings.py
database/tests/test_spatial.py
database/tests/test_arcgis.py
database/tests/test_harvest_acceptance.py
database/tests/test_boundary_harvest.py
database/tests/test_boundary_acceptance.py
database/tests/test_review_export.py
docs/ARCGIS_HARVEST.md
docs/HARVEST_ACCEPTANCE.md
docs/REVIEW_EXPORT.md'

printf '%s\n' 'Checking tracked source checksums...'
sha256sum -c CHECKSUMS.sha256

printf '%s\n' 'Checking complete application tree...'
for path in $required_files; do
  if [ ! -f "$path" ]; then
    printf 'Missing required file: %s\n' "$path" >&2
    exit 1
  fi
done

if ! command -v python3 >/dev/null 2>&1; then
  printf '%s\n' 'Python 3 is required.' >&2
  exit 1
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 9):
    raise SystemExit("Python 3.9 or newer is required")
print(f"Python {sys.version.split()[0]}")
PY

printf '%s\n' 'Validating official Kane County ArcGIS source profiles offline...'
bash database/validate-source-profile.sh

printf '%s\n' 'Building ledger and fixture building candidate...'
bash database/build-building-database.sh \
  database/fixtures/buildings-sample.geojson \
  fixture-buildings-v1

printf '%s\n' 'Calibrating the practical-cell grid from the fixture boundary...'
bash database/calibrate-spatial-database.sh \
  database/fixtures/county-boundary-sample.geojson

printf '%s\n' 'Refreshing fixture building release with comparison and spatial indexing...'
bash database/refresh-building-database.sh \
  database/fixtures/buildings-refresh-v2.geojson \
  fixture-buildings-v2

printf '%s\n' 'Validating accepted ledger candidate...'
bash database/validate-ledger-database.sh

printf '%s\n' 'Validating accepted building candidate...'
bash database/validate-building-database.sh

printf '%s\n' 'Validating practical-cell spatial index and review triggers...'
bash database/validate-spatial-database.sh

printf '%s\n' 'Running database tests...'
bash database/run-tests.sh

printf '%s\n' 'Complete Linux database verification passed.'
printf '%s\n' 'The official building and boundary harvest, SQL-acceptance, and review-export contracts were validated offline; no live source was contacted.'
printf '%s\n' 'The boundary and both building releases used above are synthetic fixtures, not county source data.'
printf '%s\n' 'TrivialHTTP source was checked for presence but was not compiled.'
