#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu 24.04 droplet (DigitalOcean, etc.)
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash deploy/setup-server.sh"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl git ufw

# Docker
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi

systemctl enable docker
systemctl start docker

# Firewall — SSH + web only
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

APP_DIR="/opt/port-vale-analysis"
mkdir -p "$APP_DIR"
echo ""
echo "✓ Server ready."
echo "  Next: copy this repo to $APP_DIR, add .env, then run:"
echo "  cd $APP_DIR && bash deploy/deploy.sh"
