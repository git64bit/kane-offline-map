#!/bin/sh
set -eu

if [ "$#" -ne 4 ]; then
  printf 'Usage: bash database/accept-kane-map-layers.sh DATABASE ROADS.geojson FOX-RIVER.geojson CREEKS.geojson\n' >&2
  exit 2
fi

DATABASE=$1
ROADS=$2
FOX_RIVER=$3
CREEKS=$4
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHONDONTWRITEBYTECODE=1 exec python3 "$SCRIPT_DIR/tools/county_db.py" \
  accept-harvested-map-layers "$DATABASE" \
  --road-profile "$SCRIPT_DIR/sources/kane-county-roads.json" \
  --roads "$ROADS" \
  --river-profile "$SCRIPT_DIR/sources/kane-county-fox-river.json" \
  --fox-river "$FOX_RIVER" \
  --creek-profile "$SCRIPT_DIR/sources/kane-county-creeks.json" \
  --creeks "$CREEKS"
