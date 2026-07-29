#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"
if ! command -v python3 >/dev/null 2>&1; then
  printf '%s\n' 'Python 3 is required.' >&2
  exit 1
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 tools/county_db.py validate-ledger \
  ../project-data/database/kane-county-build.gpkg "$@"
