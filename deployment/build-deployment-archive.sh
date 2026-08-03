#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  printf 'Usage: bash deployment/build-deployment-archive.sh DATABASE OUTPUT_ZIP [--force]\n' >&2
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
OUTPUT_DIR=$(dirname -- "$OUTPUT")
mkdir -p "$OUTPUT_DIR"
if [ -e "$OUTPUT" ] && [ "$FORCE" != "--force" ]; then
  printf 'Output already exists; use --force to replace it: %s\n' "$OUTPUT" >&2
  exit 2
fi
WORK=$(mktemp -d "$OUTPUT_DIR/.kane-offline-map-build.XXXXXX")
trap 'rm -rf "$WORK"' EXIT HUP INT TERM
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT/database/tools/county_cli.py" \
  export-prepared-core "$DATABASE" --output "$WORK/prepared"
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT/deployment/tools/portable_archive.py" \
  --root "$ROOT" "$WORK/prepared" "$OUTPUT" ${FORCE:+--force}
