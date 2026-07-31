#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  printf 'Usage: bash database/calibrate-spatial-database.sh COUNTY_BOUNDARY.geojson\n' >&2
  exit 2
fi

INPUT_ARG=$1
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
case "$INPUT_ARG" in
  /*) BOUNDARY=$INPUT_ARG ;;
  *) BOUNDARY=$(pwd)/$INPUT_ARG ;;
esac

PYTHONDONTWRITEBYTECODE=1 exec python3 "$ROOT/database/tools/county_db.py" \
  calibrate-grid "$ROOT/project-data/database/kane-county-build.gpkg" \
  --boundary "$BOUNDARY"
