#!/usr/bin/env bash
# Run this ON THE SERVER (DigitalOcean Web Console) after pushing from your Mac.
set -euo pipefail

APP="/opt/port-vale-analysis"
REPO="https://github.com/SamBakerAnalyst/port-vale-analysis.git"
TMP="/tmp/port-vale-update"

echo "=============================================="
echo " Port Vale — Update live site from GitHub"
echo "=============================================="

command -v git >/dev/null || { apt-get update -qq && apt-get install -y -qq git ca-certificates; }
command -v docker >/dev/null || { echo "Docker not found — contact support"; exit 1; }

echo "Downloading latest code from GitHub…"
rm -rf "$TMP"
git clone --depth 1 "$REPO" "$TMP"

echo "Copying updated files…"
cp "$TMP/app/"*.py "$APP/app/" 2>/dev/null || true
cp -R "$TMP/app/post_match" "$APP/app/" 2>/dev/null || true
cp "$TMP/static/"* "$APP/static/" 2>/dev/null || true
cp "$TMP/standalone/"* "$APP/standalone/" 2>/dev/null || true
cp "$TMP/deploy/update-live.sh" "$APP/deploy/" 2>/dev/null || true
cp "$TMP/templates/"* "$APP/templates/" 2>/dev/null || true

echo "Rebuilding and restarting…"
cd "$APP"
docker compose -f deploy/docker-compose.ip.yml build --no-cache hub
docker compose -f deploy/docker-compose.ip.yml up -d

echo "Checking health…"
for _ in $(seq 1 30); do
  if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    BUILD="$(curl -sf http://localhost:8000/api/pre-match/build 2>/dev/null | grep -o '"build":"[^"]*"' | cut -d'"' -f4 || echo unknown)"
    echo ""
    echo "✓ Live site updated"
    echo "  Hub:      http://178.128.161.215"
    echo "  Build:    ${BUILD:0:8}"
    exit 0
  fi
  sleep 2
done

echo "Hub did not become healthy. Run: docker compose -f deploy/docker-compose.ip.yml logs --tail=30 hub"
exit 1
