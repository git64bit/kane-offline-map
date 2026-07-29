# TrivialHTTP for County Field Map

TrivialHTTP serves County Field Map from a local folder and writes only the 16 validated classification ledger files under `project-data/sectors`.

It binds to `127.0.0.1` only. The storage endpoint accepts only `N11-E06.json` through `N14-E09.json`, rejects traversal and arbitrary filenames, and replaces files atomically.

## Build

Linux:

```sh
./scripts/build-linux.sh
```

Windows cross-build from Debian or Ubuntu:

```sh
apt install gcc-mingw-w64-x86-64
./scripts/build-windows-mingw.sh
```

macOS:

```sh
./scripts/build-macos.sh
```

## Run

From the County Field Map root:

```sh
trivialhttp/build/trivialhttp --root .
```

The browser opens automatically on a free loopback port. Use `--no-open` to suppress browser launch.
