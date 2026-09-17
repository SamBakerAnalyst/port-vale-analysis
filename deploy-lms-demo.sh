#!/usr/bin/env bash
# Push current Mac tree to the droplet and rebuild LMS SPORTS AI CONSULTANCY
# (blank demo hub) only. Does not restart Port Vale Live or Staging.
#
# Usage:
#   bash ~/impect-football-dashboard/deploy-lms-demo.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

SERVER="root@178.128.161.215"
REMOTE="/opt/port-vale-analysis"
LMS_DIR="/opt/lms-sports-ai"
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
echo " Ship LMS Sports AI Consultancy demo"
echo " → https://lmsc.sportsanalysis.ai/"
echo "   (direct http://178.128.161.215:8090/ still works)"
echo " (Port Vale Live + Staging are left alone)"
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
  --include 'data/squad-planner.json'
  --include 'data/efl-transfer-report-2026.json'
  --include 'data/transfermarkt-loans-2026.json'
  --include 'data/efl-transfer-badges.json'
  --include 'data/transfer-centre-positions.json'
  --include 'data/pre-match-two-pager.json'
  --include 'data/'
  --exclude 'data/*'
  --exclude '.env'
  --exclude '.env.auth'
  --exclude '.env.lms'
  --exclude 'static/player-photos/'
  --exclude 'static/handout-badges/'
  --exclude '*.bak*'
  --exclude '.tmp-*'
)

echo ""
echo "Checking Live Caddyfile before rsync (must not put LMS on pvfc)…"
bash "$ROOT/deploy/check-live-caddy.sh"

echo ""
echo "1/2 Syncing files to droplet…"
if [[ ${#SSH_OPTS[@]} -gt 0 ]]; then
  rsync -avz "${RSYNC_EXCLUDES[@]}" -e "ssh ${SSH_OPTS[*]}" "$ROOT/" "$SERVER:$REMOTE/"
else
  rsync -avz "${RSYNC_EXCLUDES[@]}" -e "ssh -o StrictHostKeyChecking=no" "$ROOT/" "$SERVER:$REMOTE/"
fi

echo ""
echo "2/2 Rebuilding LMS demo on server…"
REMOTE_CMD=$(cat <<'EOF'
set -euo pipefail
cd /opt/port-vale-analysis
if command -v ufw >/dev/null 2>&1; then
  ufw allow 8090/tcp comment 'lms sports ai demo' >/dev/null 2>&1 || true
fi
mkdir -p /opt/lms-sports-ai
if [[ ! -f /opt/lms-sports-ai/.env ]]; then
  PASS="$(openssl rand -base64 18 | tr -d '/+=' | head -c 16)"
  SECRET="$(openssl rand -hex 32)"
  cat > /opt/lms-sports-ai/.env <<ENVEOF
HUB_PROFILE=lms
HUB_ENV=demo
TEAM_USERNAME=lms
TEAM_PASSWORD=${PASS}
HUB_AUTH_SECRET=${SECRET}
ENVEOF
  chmod 600 /opt/lms-sports-ai/.env
  printf '%s\n' "lms / ${PASS}" > /opt/lms-sports-ai/LOGIN.txt
  chmod 600 /opt/lms-sports-ai/LOGIN.txt
  echo "CREATED demo login: lms / ${PASS}"
  echo "(also written to /opt/lms-sports-ai/LOGIN.txt)"
else
  echo "Using existing /opt/lms-sports-ai/.env"
fi
# Never inherit Port Vale Impect credentials into the blank demo.
if grep -q '^IMPECT_' /opt/lms-sports-ai/.env 2>/dev/null; then
  echo "WARNING: IMPECT_* found in LMS env — blank demo should not pull club data."
fi
export LMS_ENV_FILE=/opt/lms-sports-ai/.env
docker compose --project-directory /opt/port-vale-analysis \
  -f deploy/docker-compose.lms.yml \
  -p lms-sports-ai \
  up -d --build --remove-orphans
echo "Waiting for LMS demo health…"
for _ in $(seq 1 40); do
  if curl -sf http://127.0.0.1:8090/health >/dev/null 2>&1; then
    echo ""
    echo "Reloading edge Caddy for lmsc.sportsanalysis.ai (does not restart Port Vale Live)…"
    # rsync replaces the Caddyfile inode; a running bind-mount keeps the old file,
    # so restart Caddy (not the Vale hub) to pick up the new hostname.
    if docker restart port-vale-analysis-caddy-1 >/tmp/caddy-lms-restart.log 2>&1; then
      echo "  Caddy restarted."
    else
      echo "  WARNING: Caddy restart failed — :8090 still works. Logs:"
      cat /tmp/caddy-lms-restart.log 2>/dev/null || true
    fi
    echo ""
    echo "✓ LMS Sports AI Consultancy ready"
    echo "  Public:  https://lmsc.sportsanalysis.ai/"
    echo "  Direct:  http://178.128.161.215:8090/"
    echo "  Port Vale Live unchanged:     http://178.128.161.215/"
    echo "  Port Vale Staging unchanged:  http://178.128.161.215:8080/"
    exit 0
  fi
  sleep 2
done
docker compose -p lms-sports-ai -f deploy/docker-compose.lms.yml logs --tail=40 lms || true
exit 1
EOF
)

if [[ ${#SSH_OPTS[@]} -gt 0 ]]; then
  ssh "${SSH_OPTS[@]}" "$SERVER" "$REMOTE_CMD"
else
  ssh -o StrictHostKeyChecking=no "$SERVER" "$REMOTE_CMD"
fi
