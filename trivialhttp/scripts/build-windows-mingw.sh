#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p build
x86_64-w64-mingw32-gcc -std=c11 -O2 -Wall -Wextra -Werror src/trivialhttp.c src/platform.c src/http.c src/sector_storage.c -lws2_32 -lshell32 -o build/trivialhttp.exe
printf 'Wrote trivialhttp/build/trivialhttp.exe\n'
