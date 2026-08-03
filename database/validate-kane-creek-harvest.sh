#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
GEOJSON=${1:?Usage: bash database/validate-kane-creek-harvest.sh HARVEST.geojson}
PYTHONDONTWRITEBYTECODE=1 exec python3 "$SCRIPT_DIR/tools/county_db.py" validate-harvest \
  --profile "$SCRIPT_DIR/sources/kane-county-creeks.json" \
  --geojson "$GEOJSON"
