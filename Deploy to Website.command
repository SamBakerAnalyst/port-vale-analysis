#!/usr/bin/env bash
# Double-click this — the ONLY deploy button you need.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "=============================================="
echo " Deploy to Website"
echo "=============================================="
echo ""
echo "This will:"
echo "  • Push main → GitHub"
echo "  • Sync this Mac → live droplet"
echo "  • Restart the site"
echo ""
echo "Live URL: http://178.128.161.215/"
echo ""

bash "$ROOT/deploy-live.sh"

echo ""
read -r -p "Press Enter to close…"
