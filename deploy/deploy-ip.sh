#!/usr/bin/env bash
# Deploy without DNS — in-app login at http://DROPLET_IP/login
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Missing .env — copy your local .env to the server first."
  exit 1
fi

env_val() {
  grep -E "^${1}=" .env 2>/dev/null | cut -d= -f2- | sed 's/^"\(.*\)"$/\1/' || true
}

TEAM_USERNAME="$(env_val TEAM_USERNAME)"
TEAM_PASSWORD="$(env_val TEAM_PASSWORD)"
HUB_AUTH_SECRET="$(env_val HUB_AUTH_SECRET)"

if [[ -z "$TEAM_PASSWORD" ]]; then
  echo "Setting team login credentials…"
  TEAM_USERNAME="${TEAM_USERNAME:-PortVale}"
  TEAM_PASSWORD="${TEAM_PASSWORD:-JoyPortVale123!}"
  HUB_AUTH_SECRET="${HUB_AUTH_SECRET:-$(openssl rand -hex 32)}"
  grep -v '^TEAM_USERNAME=' .env | grep -v '^TEAM_PASSWORD=' | grep -v '^HUB_AUTH_SECRET=' \
    | grep -v '^BASIC_AUTH_USER=' | grep -v '^BASIC_AUTH_HASH=' > .env.tmp || true
  cat .env.tmp > .env
  rm -f .env.tmp
  {
    echo "TEAM_USERNAME=${TEAM_USERNAME}"
    echo "TEAM_PASSWORD=${TEAM_PASSWORD}"
    echo "HUB_AUTH_SECRET=${HUB_AUTH_SECRET}"
  } >> .env
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  Team login for the analysis hub"
  echo "  URL:      http://YOUR_SERVER_IP/login"
  echo "  Username: ${TEAM_USERNAME}"
  echo "  Password: ${TEAM_PASSWORD}"
  echo "  (saved in .env as TEAM_PASSWORD — share securely)"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""
fi

if [[ -z "$HUB_AUTH_SECRET" ]]; then
  HUB_AUTH_SECRET="$(openssl rand -hex 32)"
  echo "HUB_AUTH_SECRET=${HUB_AUTH_SECRET}" >> .env
fi

echo "Deploying (in-app login, IP-only)…"
docker compose --project-directory "$ROOT" -f deploy/docker-compose.ip.yml build
docker compose --project-directory "$ROOT" -f deploy/docker-compose.ip.yml up -d --remove-orphans

echo "Waiting for health…"
for _ in $(seq 1 30); do
  if docker compose --project-directory "$ROOT" -f deploy/docker-compose.ip.yml exec -T hub curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
    echo ""
    echo "✓ Hub is live at: http://${PUBLIC_IP}/"
    echo "  Sign in at:     http://${PUBLIC_IP}/login"
    echo "  Username:       ${TEAM_USERNAME:-PortVale}"
    if [[ -n "${TEAM_PASSWORD:-}" ]]; then
      echo "  Password:       ${TEAM_PASSWORD}"
    else
      echo "  Password:       (see TEAM_PASSWORD in .env)"
    fi
    exit 0
  fi
  sleep 2
done
docker compose --project-directory "$ROOT" -f deploy/docker-compose.ip.yml logs --tail=30 hub
exit 1
