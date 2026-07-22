#!/usr/bin/env bash
# Alias — same as "Deploy to Website.command" (no separate scouting path).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "Building scouting address page…"
python3 scripts/build-scouting-address-html.py
cp standalone/scouting-address.html app/scouting_address_page.html
cp standalone/scouting-address.js static/scouting-address.js
cp standalone/scouting-address.css static/scouting-address.css 2>/dev/null || true

exec bash "$ROOT/Deploy to Website.command"
