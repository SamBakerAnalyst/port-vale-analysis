#!/usr/bin/env bash
# Build and start (or update) the production stack.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.example and fill in Impect credentials + SITE_DOMAIN"
  exit 1
fi

# shellcheck disable=SC1091
set -a
source .env
set +a

if [[ -z "${SITE_DOMAIN:-}" ]]; then
  echo "Set SITE_DOMAIN in .env (e.g. analysis.port-vale.co.uk)"
  exit 1
fi

echo "Deploying Port Vale Analysis Hub → https://${SITE_DOMAIN}"

# Use plain Caddyfile (login handled inside the app)
cp deploy/Caddyfile deploy/Caddyfile.active
echo "Login: in-app at /login (set TEAM_PASSWORD in .env)"

docker compose -f docker-compose.prod.yml build --pull
docker compose -f docker-compose.prod.yml up -d --remove-orphans

echo ""
echo "Waiting for health check…"
for _ in $(seq 1 30); do
  if docker compose -f docker-compose.prod.yml exec -T hub curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    echo "✓ Hub is healthy"
    echo "✓ Live at: https://${SITE_DOMAIN}"
    docker compose -f docker-compose.prod.yml ps
    exit 0
  fi
  sleep 2
done

echo "Hub did not become healthy in time. Logs:"
docker compose -f docker-compose.prod.yml logs --tail=50 hub
exit 1
