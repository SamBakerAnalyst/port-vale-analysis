#!/usr/bin/env bash
# Push current Mac tree to the droplet and rebuild PORT VALE STAGING only.
# Does not restart Port Vale Live staff traffic.
#
# Usage:
#   bash ~/impect-football-dashboard/deploy-staging.sh
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
echo " Ship to PORT VALE STAGING → http://178.128.161.215:8080/"
echo " (Port Vale Live is left alone)"
echo " Repo: $ROOT"
echo "=============================================="

case "$ROOT" in
  */Desktop/*|*/Downloads/*)
    echo "ERROR: refusing to deploy from $ROOT"
    echo "Use ~/impect-football-dashboard only."
    exit 1
    ;;
esac

RSYNC_EXCLUDES=(
  --exclude '.venv'
  --exclude '__pycache__'
  --exclude '.git'
  # Derived caches (home-standouts / home-recruitment / home-strategy) are
  # deliberately NOT shipped. They are rebuilt on the server, and copying a
  # developer's copy up only risks overwriting good data with a local stub.
  --include 'data/squad-planner.json'
  --include 'data/efl-transfer-report-2026.json'
  --include 'data/'
  --exclude 'data/*'
  --exclude '.env'
  --exclude '.env.auth'
  --exclude 'static/player-photos/'
  --exclude 'static/handout-badges/'
  --exclude '*.bak*'
  --exclude '.tmp-*'
)

echo ""
echo "1/2 Syncing files to droplet…"
if [[ ${#SSH_OPTS[@]} -gt 0 ]]; then
  rsync -avz "${RSYNC_EXCLUDES[@]}" -e "ssh ${SSH_OPTS[*]}" "$ROOT/" "$SERVER:$REMOTE/"
else
  rsync -avz "${RSYNC_EXCLUDES[@]}" -e "ssh -o StrictHostKeyChecking=no" "$ROOT/" "$SERVER:$REMOTE/"
fi

echo ""
echo "2/2 Rebuilding Port Vale Staging on server…"
REMOTE_CMD=$(cat <<'EOF'
set -euo pipefail
cd /opt/port-vale-analysis
# Allow staff Macs to reach staging (idempotent).
if command -v ufw >/dev/null 2>&1; then
  ufw allow 8080/tcp comment 'port-vale staging' >/dev/null 2>&1 || true
fi
docker compose --project-directory /opt/port-vale-analysis \
  -f deploy/docker-compose.staging.yml \
  -p port-vale-staging \
  up -d --build --remove-orphans
echo "Waiting for Port Vale Staging health…"
for _ in $(seq 1 40); do
  if curl -sf http://127.0.0.1:8080/health >/dev/null 2>&1; then
    echo ""
    echo "✓ Port Vale Staging ready: http://178.128.161.215:8080/"
    echo "  Port Vale Live unchanged: http://178.128.161.215/"
    exit 0
  fi
  sleep 2
done
docker compose -p port-vale-staging -f deploy/docker-compose.staging.yml logs --tail=40 hub || true
exit 1
EOF
)

if [[ ${#SSH_OPTS[@]} -gt 0 ]]; then
  ssh "${SSH_OPTS[@]}" "$SERVER" "$REMOTE_CMD"
else
  ssh -o StrictHostKeyChecking=no "$SERVER" "$REMOTE_CMD"
fi
