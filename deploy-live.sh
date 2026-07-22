#!/usr/bin/env bash
# ONE deploy path for Port Vale Analysis Hub.
# Live site: http://178.128.161.215/
#
# What this does:
#   1. Push current main to GitHub (source of truth)
#   2. Rsync this Mac → droplet (immediate update)
#   3. Rebuild/restart the hub container
#
# Usage (from anywhere):
#   bash ~/impect-football-dashboard/deploy-live.sh
# Or double-click: Deploy to Website.command
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

SERVER="root@178.128.161.215"
REMOTE="/opt/port-vale-analysis"
SSH_KEY="${PORTVALE_SSH_KEY:-}"
for candidate in "$HOME/.ssh/portvale_deploy" "$HOME/.ssh/portvale_analysis" "$HOME/.ssh/id_ed25519"; do
  if [[ -z "$SSH_KEY" && -f "$candidate" ]]; then
    SSH_KEY="$candidate"
  fi
done
SSH_OPTS=()
if [[ -n "$SSH_KEY" && -f "$SSH_KEY" ]]; then
  SSH_OPTS=(-i "$SSH_KEY" -o IdentitiesOnly=yes -o StrictHostKeyChecking=no)
fi

echo "=============================================="
echo " Ship to live → http://178.128.161.215/"
echo " Repo: $ROOT"
echo "=============================================="

# Keep GitHub in sync so Actions / console updates can't overwrite with older code.
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  branch="$(git branch --show-current 2>/dev/null || echo main)"
  if [[ "$branch" != "main" ]]; then
    echo "WARNING: on branch '$branch' (expected main). Continuing anyway."
  fi
  if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "NOTE: you have uncommitted changes — they WILL go live via rsync,"
    echo "      but they are NOT on GitHub until you commit + push."
  fi
  echo ""
  echo "1/3 Pushing main to GitHub…"
  if git push origin main; then
    echo "   ✓ GitHub updated"
  else
    echo "   ⚠ Git push failed — continuing with rsync so live still updates."
    echo "     Fix GitHub auth later so deploys can't drift."
  fi
else
  echo "WARNING: not a git repo — skipping push"
fi

echo ""
echo "2/3 Syncing files to droplet…"
# Do NOT --delete photo/cache dirs that may only exist on the server.
RSYNC_EXCLUDES=(
  --exclude '.venv'
  --exclude '__pycache__'
  --exclude '.git'
  --exclude 'data'
  --exclude '.env'
  --exclude '.env.auth'
  --exclude 'static/player-photos/'
  --exclude 'static/handout-badges/'
  --exclude '*.bak*'
)
if [[ ${#SSH_OPTS[@]} -gt 0 ]]; then
  rsync -avz "${RSYNC_EXCLUDES[@]}" -e "ssh ${SSH_OPTS[*]}" "$ROOT/" "$SERVER:$REMOTE/"
else
  rsync -avz "${RSYNC_EXCLUDES[@]}" -e "ssh -o StrictHostKeyChecking=no" "$ROOT/" "$SERVER:$REMOTE/"
fi

echo ""
echo "3/3 Rebuilding hub on server…"
if [[ ${#SSH_OPTS[@]} -gt 0 ]]; then
  ssh "${SSH_OPTS[@]}" "$SERVER" "cd $REMOTE && bash deploy/deploy-ip.sh"
else
  ssh -o StrictHostKeyChecking=no "$SERVER" "cd $REMOTE && bash deploy/deploy-ip.sh"
fi

echo ""
echo "✓ Live site updated: http://178.128.161.215/"
echo "  Scouting address:  http://178.128.161.215/scouting-address"
echo "  Hard refresh: Cmd+Shift+R"
echo ""
echo "Expect footer: Build: webpage-v12 (or newer)"
