#!/usr/bin/env bash
# Push latest pre-match + hub code to the live server and redeploy.
# Usage: bash deploy/push-production.sh [user@178.128.161.215]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-root@178.128.161.215}"
REMOTE="/opt/port-vale-analysis"
KEY="${HOME}/.ssh/id_ed25519"
SSH=(ssh)
RSYNC=(rsync)
if [[ -f "$KEY" ]]; then
  SSH+=( -i "$KEY" -o IdentitiesOnly=yes )
  RSYNC+=( -e "ssh -i $KEY -o IdentitiesOnly=yes" )
fi

echo "Syncing code → ${TARGET}:${REMOTE}"

"${SSH[@]}" "$TARGET" "test -d '$REMOTE' || { echo 'Missing $REMOTE on server'; exit 1; }"

"${RSYNC[@]}" -av --delete \
  --exclude '.env' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  "$ROOT/app/" "$TARGET:$REMOTE/app/"

"${RSYNC[@]}" -av \
  "$ROOT/static/pre-match.js" \
  "$ROOT/static/pre-match.css" \
  "$ROOT/static/scouting-address.js" \
  "$ROOT/static/scouting-address.css" \
  "$ROOT/static/stadiums.json" \
  "$TARGET:$REMOTE/static/"

"${RSYNC[@]}" -av \
  "$ROOT/standalone/pre-match.html" \
  "$ROOT/standalone/pre-match.page.html" \
  "$ROOT/standalone/scouting-address.html" \
  "$ROOT/standalone/scouting-address.js" \
  "$ROOT/standalone/scouting-address.css" \
  "$ROOT/standalone/stadiums.json" \
  "$ROOT/standalone/apps.js" \
  "$TARGET:$REMOTE/standalone/"

echo "Redeploying on server (no cache)…"
"${SSH[@]}" "$TARGET" "cd '$REMOTE' && docker compose -f deploy/docker-compose.ip.yml build --no-cache hub && docker compose -f deploy/docker-compose.ip.yml up -d"

echo ""
echo "✓ Production updated. Team hub bookmark stays the same:"
echo "  http://178.128.161.215"
echo "  Hub → Analysis → Pre-Match → toolbar build badge should be 8 hex chars (not v138)."
