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
database/tools/county_db.py
database/tools/county_ledger.py
database/tests/test_database.py'

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

printf '%s\n' 'Building accepted ledger candidate...'
bash database/build-ledger-database.sh

printf '%s\n' 'Validating accepted ledger candidate...'
bash database/validate-ledger-database.sh

printf '%s\n' 'Running database tests...'
bash database/run-tests.sh

printf '%s\n' 'Complete Linux database verification passed.'
printf '%s\n' 'TrivialHTTP source was checked for presence but was not compiled.'
