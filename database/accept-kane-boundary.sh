#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
  printf 'Usage: bash database/accept-kane-boundary.sh DATABASE HARVEST.geojson\n' >&2
  exit 2
fi

DATABASE=$1
GEOJSON=$2
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHONDONTWRITEBYTECODE=1 exec python3 "$SCRIPT_DIR/tools/county_db.py" \
  accept-harvested-boundary "$DATABASE" \
  --profile "$SCRIPT_DIR/sources/kane-county-boundary.json" \
  --geojson "$GEOJSON"
