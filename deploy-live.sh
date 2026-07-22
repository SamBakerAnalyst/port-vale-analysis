#!/usr/bin/env bash
# Push this repo to the live website — run after EVERY agent change.
# Live site: http://178.128.161.215/
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

if [[ ${#SSH_OPTS[@]} -eq 0 ]]; then
  echo "WARNING: No SSH key found — trying ssh-agent keys…"
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
