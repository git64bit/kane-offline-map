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
database/migrations/0005_source_buildings.sql
database/tools/county_db.py
database/tools/county_buildings.py
database/tools/county_ledger.py
database/tests/test_database.py
database/tests/test_buildings.py'

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

printf '%s\n' 'Building ledger and fixture building candidate...'
bash database/build-building-database.sh \
  database/fixtures/buildings-sample.geojson \
  fixture-buildings-v1

printf '%s\n' 'Validating accepted ledger candidate...'
bash database/validate-ledger-database.sh

printf '%s\n' 'Validating accepted building candidate...'
bash database/validate-building-database.sh

printf '%s\n' 'Running database tests...'
bash database/run-tests.sh

printf '%s\n' 'Complete Linux database verification passed.'
printf '%s\n' 'The building release used above is a synthetic fixture, not county source data.'
printf '%s\n' 'TrivialHTTP source was checked for presence but was not compiled.'
