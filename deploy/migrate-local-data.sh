#!/usr/bin/env bash
# Copy local Mac caches to the production server (run from your Mac).
# Usage: bash deploy/migrate-local-data.sh user@YOUR_SERVER_IP
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: bash deploy/migrate-local-data.sh user@server-ip"
  exit 1
fi

TARGET="$1"
REMOTE_DIR="/opt/port-vale-analysis/data/cache"
LOCAL_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

mkdir -p "$LOCAL_ROOT/data/cache"

# Pull from Mac caches if present
for name in impect-fixture-planner impect-availability impect-scouting impect-club-strategy; do
  if [[ -d "$HOME/.cache/$name" ]]; then
    echo "Copying $name…"
    rsync -av "$HOME/.cache/$name/" "$LOCAL_ROOT/data/cache/$name/"
  fi
done

echo "Uploading to $TARGET:$REMOTE_DIR …"
ssh "$TARGET" "mkdir -p $REMOTE_DIR"
rsync -av "$LOCAL_ROOT/data/cache/" "$TARGET:$REMOTE_DIR/"

echo "✓ Done. Restart hub on server: cd /opt/port-vale-analysis && docker compose -f docker-compose.prod.yml restart hub"
