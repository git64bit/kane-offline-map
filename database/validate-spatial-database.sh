#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHONDONTWRITEBYTECODE=1 exec python3 "$ROOT/database/tools/county_db.py" \
  validate-spatial "$ROOT/project-data/database/kane-county-build.gpkg"
