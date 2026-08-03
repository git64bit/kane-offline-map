#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
for profile in \
  "$SCRIPT_DIR/sources/kane-county-buildings.json" \
  "$SCRIPT_DIR/sources/kane-county-boundary.json" \
  "$SCRIPT_DIR/sources/kane-county-roads.json" \
  "$SCRIPT_DIR/sources/kane-county-fox-river.json" \
  "$SCRIPT_DIR/sources/kane-county-creeks.json"
do
  PYTHONDONTWRITEBYTECODE=1 python3 "$SCRIPT_DIR/tools/county_db.py" \
    validate-source-profile "$profile"
done
