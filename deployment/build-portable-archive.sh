#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec python3 "$ROOT/deployment/tools/portable_archive.py" --root "$ROOT" "$@"
