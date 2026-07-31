#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DATABASE=${1:?Usage: bash database/refresh-kane-harvest-database.sh DATABASE.gpkg HARVEST.geojson}
GEOJSON=${2:?Usage: bash database/refresh-kane-harvest-database.sh DATABASE.gpkg HARVEST.geojson}
PYTHONDONTWRITEBYTECODE=1 exec python3 "$SCRIPT_DIR/tools/county_db.py" refresh-harvested-buildings \
  "$DATABASE" \
  --profile "$SCRIPT_DIR/sources/kane-county-buildings.json" \
  --geojson "$GEOJSON"
