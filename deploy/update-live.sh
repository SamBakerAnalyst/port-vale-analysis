#!/usr/bin/env bash
# Run ON THE SERVER (DigitalOcean Console) to pull latest from GitHub.
# Prefer Mac path instead: bash ~/impect-football-dashboard/deploy-live.sh
set -euo pipefail

APP="/opt/port-vale-analysis"
REPO="https://github.com/SamBakerAnalyst/port-vale-analysis.git"
TMP="/tmp/port-vale-update"

echo "=============================================="
echo " Port Vale — Update live site from GitHub"
echo "=============================================="

command -v git >/dev/null || { apt-get update -qq && apt-get install -y -qq git ca-certificates; }
command -v docker >/dev/null || { echo "Docker not found — contact support"; exit 1; }
command -v rsync >/dev/null || { apt-get update -qq && apt-get install -y -qq rsync; }

echo "Downloading latest code from GitHub…"
rm -rf "$TMP"
git clone --depth 1 "$REPO" "$TMP"

echo "Syncing full tree (including Dockerfile)…"
# Preserve server-only runtime data / photos
rsync -a \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude 'data' \
  --exclude '.env' \
  --exclude '.env.auth' \
  --exclude 'static/player-photos/' \
  --exclude 'static/handout-badges/' \
  "$TMP/" "$APP/"

echo "Rebuilding and restarting…"
cd "$APP"
bash deploy/deploy-ip.sh

echo ""
echo "✓ Live site updated from GitHub"
echo "  Hub: http://178.128.161.215/"
