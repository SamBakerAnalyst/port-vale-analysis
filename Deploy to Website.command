#!/usr/bin/env bash
# Double-click to publish changes to the live website (existing droplet).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "=============================================="
echo " Deploy to Website (your droplet)"
echo "=============================================="
echo ""
echo "This pushes to GitHub. GitHub Actions deploys to:"
echo "  http://178.128.161.215/"
echo ""

if ! git diff --quiet || ! git diff --cached --quiet || [ -n "$(git ls-files --others --exclude-standard)" ]; then
  git add -A
  git commit -m "Deploy $(date '+%Y-%m-%d %H:%M')" || true
fi

echo "Pushing to GitHub…"
git push origin main

echo ""
echo "✓ Pushed. GitHub Actions will deploy in ~5–10 minutes."
echo ""
echo "Watch progress:"
echo "  https://github.com/SamBakerAnalyst/port-vale-analysis/actions"
echo ""
open "https://github.com/SamBakerAnalyst/port-vale-analysis/actions" 2>/dev/null || true
read -r -p "Press Enter to close…"
