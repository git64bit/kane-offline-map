#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  printf 'Usage: bash database/export-prepared-core.sh DATABASE OUTPUT_DIRECTORY [--force]\n' >&2
  exit 2
fi
DATABASE=$1
OUTPUT=$2
FORCE=${3-}
case "$FORCE" in
  "") ;;
  --force) ;;
  *) printf 'Unknown option: %s\n' "$FORCE" >&2; exit 2 ;;
esac
PYTHONDONTWRITEBYTECODE=1 exec python3 "$SCRIPT_DIR/tools/county_cli.py" \
  export-prepared-core "$DATABASE" --output "$OUTPUT" ${FORCE:+--force}
