#!/usr/bin/env bash
# ONE deploy path for Port Vale Live.
# Product: Port Vale Live — http://178.128.161.215/
#
# What this does:
#   1. Push current main to GitHub (source of truth)
#   2. Rsync this Mac → droplet (immediate update)
#   3. Rebuild/restart the Live hub container
#
# Usage (from anywhere):
#   bash ~/impect-football-dashboard/deploy-live.sh
# Or double-click: Deploy to Website.command
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
echo " Ship to PORT VALE LIVE → http://178.128.161.215/"
echo " Repo: $ROOT"
echo "=============================================="

# Never ship from a second copy of the repo — that caused "old version" / missing nav.
case "$ROOT" in
  */Desktop/*|*/Downloads/*)
    echo "ERROR: refusing to deploy from $ROOT"
    echo "Use ~/impect-football-dashboard only (Desktop copy drifts from live)."
    exit 1
    ;;
esac

# Guard: never ship the staff.split crash (GitHub Actions used to restore it).
bash "$ROOT/deploy/check-fixture-planner.sh"

# Keep GitHub in sync so Actions / console updates can't overwrite with older code.
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  branch="$(git branch --show-current 2>/dev/null || echo main)"
  if [[ "$branch" != "main" ]]; then
    echo "WARNING: on branch '$branch' (expected main). Continuing anyway."
  fi
  # Uncommitted Fixture Planner files get wiped the next time Actions deploys main.
  PLANNER_FILES=(
    static/fixture-planner.js
    static/fixture-planner.css
    standalone/fixture-planner.html
    standalone/played-fixtures.html
    app/fixture_planner.py
  )
  dirty_planner="$(git diff --name-only -- "${PLANNER_FILES[@]}" ; git diff --cached --name-only -- "${PLANNER_FILES[@]}")"
  if [[ -n "${dirty_planner}" ]]; then
    echo "ERROR: Fixture Planner changes are not committed:"
    echo "$dirty_planner"
    echo "Commit + push these first. GitHub Actions deploys main and will overwrite live."
    exit 1
  fi
  # The rsync below copies the working tree, not the commit — so anything sitting
  # unfinished in the tree goes to Live too. On 4 Sep that shipped a half-built
  # transfer report that nobody had asked for. A warning was not enough; refuse.
  #
  # Staging deliberately does not do this: shipping work in progress there is the
  # whole point of it.
  dirty="$(git status --porcelain --untracked-files=all)"
  if [[ -n "$dirty" ]]; then
    if [[ "${ALLOW_DIRTY_DEPLOY:-}" == "1" ]]; then
      echo "WARNING: ALLOW_DIRTY_DEPLOY=1 — shipping an uncommitted tree to LIVE:"
      echo "$dirty" | sed 's/^/    /'
      echo ""
    else
      echo "ERROR: refusing to deploy Live from an uncommitted tree."
      echo ""
      echo "$dirty" | sed 's/^/    /'
      echo ""
      echo "Live rsyncs these files as they are, so unfinished work reaches staff."
      echo "Then the next GitHub Actions run deploys main and silently reverts it."
      echo ""
      echo "  Ship it:     git add -A && git commit -m '…' && git push"
      echo "  Shelve it:   git stash push -u -m 'wip'"
      echo "  Override:    ALLOW_DIRTY_DEPLOY=1 bash deploy-live.sh"
      exit 1
    fi
  fi
  echo ""
  echo "1/3 Pushing main to GitHub…"
  if git push origin main; then
    echo "   ✓ GitHub updated"
  else
    echo "ERROR: GitHub push failed. Refusing to rsync."
    echo "Rsync-without-push is how the old staff.split crash came back on live."
    exit 1
  fi
else
  echo "ERROR: not a git repo — refusing to deploy"
  exit 1
fi

echo ""
echo "2/3 Syncing files to droplet…"
# Do NOT --delete photo/cache dirs that may only exist on the server.
RSYNC_EXCLUDES=(
  --exclude '.venv'
  --exclude '__pycache__'
  --exclude '.git'
  --include 'data/home-standouts-cache.json'
  --include 'data/home-recruitment-cache.json'
  --include 'data/home-strategy-cache.json'
  --include 'data/squad-planner.json'
  --include 'data/'
  --exclude 'data/*'
  --exclude '.env'
  --exclude '.env.auth'
  --exclude 'static/player-photos/'
  --exclude 'static/handout-badges/'
  --exclude '*.bak*'
  --exclude '.tmp-*'
)
if [[ ${#SSH_OPTS[@]} -gt 0 ]]; then
  rsync -avz "${RSYNC_EXCLUDES[@]}" -e "ssh ${SSH_OPTS[*]}" "$ROOT/" "$SERVER:$REMOTE/"
else
  rsync -avz "${RSYNC_EXCLUDES[@]}" -e "ssh -o StrictHostKeyChecking=no" "$ROOT/" "$SERVER:$REMOTE/"
fi

echo ""
echo "3/3 Rebuilding Port Vale Live on server…"
if [[ ${#SSH_OPTS[@]} -gt 0 ]]; then
  ssh "${SSH_OPTS[@]}" "$SERVER" "cd $REMOTE && bash deploy/deploy-ip.sh"
else
  ssh -o StrictHostKeyChecking=no "$SERVER" "cd $REMOTE && bash deploy/deploy-ip.sh"
fi

echo ""
echo "4/4 Smoke check (would the owner see a broken hub?)…"
if bash "$ROOT/deploy/smoke-live.sh" "http://178.128.161.215"; then
  echo ""
  echo "✓ Port Vale Live updated and verified: http://178.128.161.215/"
  echo "  Safe for staff / owner login."
else
  echo ""
  echo "✗ Deploy finished but SMOKE FAILED — fix before telling anyone to use Port Vale Live."
  exit 1
fi
