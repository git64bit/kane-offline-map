#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  printf 'Usage: bash database/export-open-review-bundle.sh DATABASE.gpkg OUTPUT_DIRECTORY [--force]\n' >&2
  exit 2
fi
if [ "$#" -eq 3 ]; then
  if [ "$3" != "--force" ]; then
    printf 'Only --force is accepted as the third argument.\n' >&2
    exit 2
  fi
  PYTHONDONTWRITEBYTECODE=1 exec python3 "$SCRIPT_DIR/tools/county_cli.py" \
    export-open-review-bundle "$1" --output "$2" --force
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 "$SCRIPT_DIR/tools/county_cli.py" \
  export-open-review-bundle "$1" --output "$2"
