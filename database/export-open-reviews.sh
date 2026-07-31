#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  printf 'Usage: bash database/export-open-reviews.sh DATABASE OUTPUT [--force]\n' >&2
  exit 2
fi
DATABASE=$1
OUTPUT=$2
FORCE=${3-}
if [ -n "$FORCE" ] && [ "$FORCE" != "--force" ]; then
  printf 'Unknown option: %s\n' "$FORCE" >&2
  exit 2
fi
set -- export-open-reviews "$DATABASE" --output "$OUTPUT"
if [ "$FORCE" = "--force" ]; then
  set -- "$@" --force
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 "$SCRIPT_DIR/tools/county_db.py" "$@"
