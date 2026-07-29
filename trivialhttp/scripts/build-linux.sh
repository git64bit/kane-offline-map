#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p build
cc -std=c11 -O2 -Wall -Wextra -Werror src/trivialhttp.c src/platform.c src/http.c src/sector_storage.c -o build/trivialhttp
printf 'Wrote trivialhttp/build/trivialhttp\n'
