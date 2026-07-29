#!/bin/sh
set -eu

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
  printf 'Usage: bash database/build-building-database.sh BUILDINGS.geojson [RELEASE_KEY]\n' >&2
  exit 2
fi

INPUT_ARG=$1
RELEASE_KEY=${2-}
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
case "$INPUT_ARG" in
  /*) GEOJSON=$INPUT_ARG ;;
  *) GEOJSON=$(pwd)/$INPUT_ARG ;;
esac

set -- \
  build-buildings \
  --archive "$ROOT/database/input/sectors.zip" \
  --geojson "$GEOJSON" \
  --output "$ROOT/project-data/database/kane-county-build.gpkg" \
  --force

if [ -n "$RELEASE_KEY" ]; then
  set -- "$@" --release-key "$RELEASE_KEY"
fi

PYTHONDONTWRITEBYTECODE=1 exec python3 "$ROOT/database/tools/county_db.py" "$@"
