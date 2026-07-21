#!/usr/bin/env bash
# Double-click after making changes — sends code to GitHub (Step A).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "=============================================="
echo " Port Vale — Push to GitHub"
echo "=============================================="
echo ""

if [[ ! -d .git ]]; then
  echo "Git not set up — ask in chat for help."
  read -r -p "Press Enter to close…"
  exit 1
fi

git add -A
git reset HEAD .env .env.* 2>/dev/null || true

if git diff --cached --quiet; then
  echo "No changes to push (already up to date)."
else
  git commit -m "Hub update $(date '+%Y-%m-%d %H:%M')"
fi

echo "Pushing to GitHub…"
git push origin main

echo ""
echo "✓ Pushed to GitHub OK"
echo ""
echo "Next: open DigitalOcean Web Console and run:"
echo "  bash /opt/port-vale-analysis/deploy/update-live.sh"
echo ""
read -r -p "Press Enter to close…"
