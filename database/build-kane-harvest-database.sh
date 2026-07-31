#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
GEOJSON=${1:?Usage: bash database/build-kane-harvest-database.sh HARVEST.geojson OUTPUT.gpkg [--force]}
OUTPUT=${2:?Usage: bash database/build-kane-harvest-database.sh HARVEST.geojson OUTPUT.gpkg [--force]}
shift 2
PYTHONDONTWRITEBYTECODE=1 exec python3 "$SCRIPT_DIR/tools/county_db.py" build-harvested-buildings \
  --archive "$SCRIPT_DIR/input/sectors.zip" \
  --profile "$SCRIPT_DIR/sources/kane-county-buildings.json" \
  --geojson "$GEOJSON" \
  --output "$OUTPUT" "$@"
