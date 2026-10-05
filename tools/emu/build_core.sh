#!/bin/sh
# Build the tracing Genesis Plus GX libretro core used by the test harness.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$HERE/build"
cd "$HERE/build"
[ -d gpgx ] || git clone https://github.com/libretro/Genesis-Plus-GX.git gpgx
cd gpgx
git checkout -q "$(cat "$HERE/gpgx_commit.txt")"
git apply --check "$HERE/gpgx_trace.patch" 2>/dev/null && git apply "$HERE/gpgx_trace.patch"
make -f Makefile.libretro -j4
cp genesis_plus_gx_libretro.so "$HERE/build/"
