#!/bin/sh
set -eu

DATABASE=${1:?Usage: bash database/validate-deployment-database.sh DATABASE}
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHONDONTWRITEBYTECODE=1 exec python3 "$SCRIPT_DIR/tools/county_db.py" \
  validate-deployment "$DATABASE"
