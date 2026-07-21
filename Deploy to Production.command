#!/usr/bin/env bash
# Double-click to push pre-match updates to the live hub at 178.128.161.215
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
KEY="${HOME}/.ssh/id_ed25519"
TARGET="root@178.128.161.215"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)
[[ -f "$KEY" ]] && SSH_OPTS+=(-i "$KEY" -o IdentitiesOnly=yes)

echo "=============================================="
echo " Port Vale — Deploy to Production"
echo " Target: $TARGET"
echo "=============================================="
echo ""

if ! ssh "${SSH_OPTS[@]}" "$TARGET" 'echo ok' >/dev/null 2>&1; then
  echo "Cannot SSH to the server yet."
  echo ""
  echo "One-time fix — paste this ONE line in the DigitalOcean Web Console:"
  echo ""
  PUB=""
  [[ -f "${KEY}.pub" ]] && PUB="$(cat "${KEY}.pub")"
  if [[ -z "$PUB" ]]; then
    ssh-keygen -t ed25519 -N "" -f "$KEY"
    PUB="$(cat "${KEY}.pub")"
  fi
  FIX="sed -i '/PASTE_YOUR_KEY_HERE/d' ~/.ssh/authorized_keys 2>/dev/null; mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo \"$PUB\" >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && echo SSH key added"
  echo "$FIX"
  echo ""
  echo "$FIX" | pbcopy 2>/dev/null && echo "(Copied to clipboard — paste in Web Console, press Enter, then double-click this file again.)"
  read -r -p "Press Enter to close…"
  exit 1
fi

bash "$ROOT/deploy/push-production.sh" "$TARGET"
echo ""
echo "Done. Open http://178.128.161.215 → Analysis → Pre-Match"
echo "Toolbar badge should show 4625423f (not v138)."
read -r -p "Press Enter to close…"
