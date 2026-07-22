#!/usr/bin/env bash
# Double-click to publish scouting address fix to the live site.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "=============================================="
echo " Deploy Scouting Address → Live Site"
echo "=============================================="
echo ""

python3 scripts/build-scouting-address-html.py

echo ""
echo "Step 1: Pushing to GitHub…"
git add standalone/scouting-address.html standalone/scouting-address.js standalone/scouting-address.css standalone/stadiums.json scripts/ deploy/scouting-address-live.sh app/scouting.py static/scouting-address.js 2>/dev/null || true
git diff --cached --quiet || git commit -m "Scouting address fix $(date '+%Y-%m-%d %H:%M')" || true
git push origin main

echo ""
echo "✓ GitHub push done."
echo ""
echo "Step 2: Updating live server…"
echo "Opening DigitalOcean in your browser."
open "https://cloud.digitalocean.com/login" 2>/dev/null || true

echo ""
echo "In DigitalOcean:"
echo "  1. Open your droplet (178.128.161.215)"
echo "  2. Click 'Console' (top right)"
echo "  3. Paste this ONE line and press Enter:"
echo ""
echo "  bash /opt/port-vale-analysis/deploy/update-live.sh"
echo ""
echo "When it says 'Live site updated', open:"
echo "  http://178.128.161.215/scouting-address"
echo "  (check footer says Build: webpage-v8)"
echo ""
read -r -p "Press Enter to close…"
