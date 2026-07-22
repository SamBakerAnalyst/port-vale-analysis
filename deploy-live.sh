#!/usr/bin/env bash
# Push this repo to the live website — run after EVERY agent change.
# Live site: http://178.128.161.215/
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

SERVER="root@178.128.161.215"
REMOTE="/opt/port-vale-analysis"
SSH_KEY="${PORTVALE_SSH_KEY:-$HOME/.ssh/portvale_analysis}"
SSH_OPTS=(-i "$SSH_KEY" -o StrictHostKeyChecking=no)

if [[ ! -f "$SSH_KEY" ]]; then
  echo "ERROR: SSH key not found at $SSH_KEY"
  echo "Set PORTVALE_SSH_KEY=/path/to/key if needed."
  exit 1
fi

echo "=============================================="
echo " Deploying to http://178.128.161.215/"
echo "=============================================="

rsync -avz --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.git' \
  --exclude 'data' \
  --exclude '.env' \
  -e "ssh ${SSH_OPTS[*]}" \
  "$ROOT/" "$SERVER:$REMOTE/"

ssh "${SSH_OPTS[@]}" "$SERVER" "cd $REMOTE && bash deploy/deploy-ip.sh"

echo ""
echo "✓ Live site updated: http://178.128.161.215/"
echo "  Hard refresh in Chrome: Cmd+Shift+R"
