#!/usr/bin/env bash
# Deploy scouting address tool to live server and rebuild Docker (required — files are baked into the image).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-root@178.128.161.215}"
REMOTE="/opt/port-vale-analysis"
KEY="${HOME}/.ssh/portvale_analysis"
SSH=(ssh)
RSYNC=(rsync)
if [[ -f "$KEY" ]]; then
  SSH+=( -i "$KEY" -o IdentitiesOnly=yes )
  RSYNC+=( -e "ssh -i $KEY -o IdentitiesOnly=yes" )
elif [[ -f "${HOME}/.ssh/id_ed25519" ]]; then
  KEY="${HOME}/.ssh/id_ed25519"
  SSH+=( -i "$KEY" -o IdentitiesOnly=yes )
  RSYNC+=( -e "ssh -i $KEY -o IdentitiesOnly=yes" )
fi

echo "Building scouting-address.html…"
python3 "$ROOT/scripts/build-scouting-address-html.py"

echo "Syncing scouting files → ${TARGET}:${REMOTE}"
"${RSYNC[@]}" -av \
  "$ROOT/standalone/scouting-address.html" \
  "$ROOT/standalone/scouting-address.js" \
  "$ROOT/standalone/scouting-address.css" \
  "$ROOT/standalone/stadiums.json" \
  "$TARGET:$REMOTE/standalone/"

echo "Rebuilding hub container (standalone files are copied at build time)…"
"${SSH[@]}" "$TARGET" "cd '$REMOTE' && docker compose -f deploy/docker-compose.ip.yml build hub && docker compose -f deploy/docker-compose.ip.yml up -d hub"

echo ""
echo "✓ Scouting address tool deployed."
echo "  Open: http://178.128.161.215/scouting-address"
echo "  Check footer shows: Build: webpage-v8"
