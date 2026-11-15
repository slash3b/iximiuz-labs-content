#!/usr/bin/env bash
# Rebuilds the page and serves it on localhost only.
set -euo pipefail
cd "$(dirname "$0")"
./build.py
echo "http://127.0.0.1:8642/"
exec python3 -m http.server 8642 --bind 127.0.0.1 --directory site
