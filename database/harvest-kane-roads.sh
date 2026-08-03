#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
OUTPUT=${1:?Usage: bash database/harvest-kane-roads.sh OUTPUT.geojson [--force]}
shift
PYTHONDONTWRITEBYTECODE=1 exec python3 "$SCRIPT_DIR/tools/county_db.py" harvest-arcgis \
  --profile "$SCRIPT_DIR/sources/kane-county-roads.json" \
  --output "$OUTPUT" "$@"
