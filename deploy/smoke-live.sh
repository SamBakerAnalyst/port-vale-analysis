#!/usr/bin/env bash
# Post-deploy smoke check for the live hub.
# Exits non-zero if the site would look broken to a staff visitor.
set -euo pipefail

BASE_URL="${1:-http://178.128.161.215}"
USER="${TEAM_USERNAME:-PortVale}"
PASS="${TEAM_PASSWORD:-JoyPortVale123!}"
COOKIE_JAR="$(mktemp)"
trap 'rm -f "$COOKIE_JAR"' EXIT

fail=0
pass() { echo "  ✓ $1"; }
bad()  { echo "  ✗ $1"; fail=1; }

echo "Smoke check → $BASE_URL"

code="$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "$BASE_URL/health" || echo 000)"
if [[ "$code" == "200" ]]; then pass "health 200"; else bad "health returned $code"; fi

login="$(curl -s -c "$COOKIE_JAR" -o /tmp/pv-smoke-login.json -w "%{http_code}" --max-time 15 \
  -X POST "$BASE_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$USER\",\"password\":\"$PASS\"}" || echo 000)"
if [[ "$login" == "200" ]]; then pass "login 200"; else bad "login returned $login"; fi

html="$(curl -s -b "$COOKIE_JAR" --max-time 20 "$BASE_URL/" || true)"
if echo "$html" | grep -q 'hub-home.js'; then pass "hub HTML serves"; else bad "hub HTML missing hub-home.js"; fi
if echo "$html" | grep -q 'homeDashboard\|homeKpiOverviewPos\|homeTodaySchedule'; then pass "hub HTML body"; else bad "hub HTML looks empty/wrong"; fi

# Sidebar source of truth is GET /api/apps (from app/apps_manifest.py).
curl -s -b "$COOKIE_JAR" --max-time 15 "$BASE_URL/api/apps" -o /tmp/pv-smoke-apps.json || true
apps_file=/tmp/pv-smoke-apps.json
if [[ ! -s "$apps_file" ]] || ! grep -q '"apps"' "$apps_file"; then
  bad "/api/apps missing or empty — hub left rail cannot load"
else
  pass "/api/apps returns registry"
fi

# Prefer titles embedded in the API payload; fall back to the known full list.
REQUIRED_APPS=()
while IFS= read -r title; do
  [[ -n "$title" ]] && REQUIRED_APPS+=("$title")
done < <(python3 - <<'PY' 2>/dev/null || true
import json, sys
try:
    data = json.load(open("/tmp/pv-smoke-apps.json"))
    titles = data.get("titles") or [a.get("title") for a in data.get("apps") or []]
    for t in titles:
        if t:
            print(t)
except Exception:
    sys.exit(1)
PY
)
if [[ "${#REQUIRED_APPS[@]}" -eq 0 ]]; then
  REQUIRED_APPS=(
    "Pre-Match Handout"
    "Pre-Match Report"
    "Set Piece Pre-Match"
    "Player Cards"
    "xG Chance Analysis"
    "Post-Match Report"
    "Blocks Analysis"
    "Schedule"
    "Player Comparison Tool"
    "Who To Scout"
    "Player Search Dashboard"
    "Squad Balance"
    "Squad Planner"
    "Fixture Planner"
    "Played Fixtures"
    "Scouting Address Tool"
    "Generate Scout Summary"
    "Scout Summary"
    "Scouts Calendar"
    "Squad Comparison"
    "Squad Availability"
    "Club Strategy"
    "League Two Strategy Report"
    "Players Strategy Report"
    "League Two Progress Report"
  )
fi

MIN_SIDEBAR=20
if [[ "${#REQUIRED_APPS[@]}" -lt "$MIN_SIDEBAR" ]]; then
  bad "sidebar title count ${#REQUIRED_APPS[@]} < $MIN_SIDEBAR — registry incomplete"
else
  pass "sidebar title count ${#REQUIRED_APPS[@]}"
fi

for need in "${REQUIRED_APPS[@]}"; do
  if grep -Fq "\"$need\"" "$apps_file" || grep -Fq "$need" "$apps_file"; then
    pass "sidebar: $need"
  else
    bad "sidebar MISSING: $need — left rail incomplete"
  fi
done
if grep -Fq '"comingSoon": true' "$apps_file" || grep -Fq 'comingSoon: true' "$apps_file"; then
  bad "/api/apps still has comingSoon tools — Progress Report must be live"
else
  pass "no comingSoon stubs in sidebar registry"
fi

curl -s --max-time 15 "$BASE_URL/standalone/hub-home.js" -o /tmp/pv-smoke-home.js || true
if grep -Fq "Promise.allSettled" /tmp/pv-smoke-home.js; then pass "hub-home paints widgets independently"; else bad "hub-home missing paint fix — Loading… can stick"; fi
if grep -Fq 'const COMPETITION = "League Two"' /tmp/pv-smoke-home.js; then pass "hub-home is League Two"; else bad "hub-home still League One — stale season"; fi

for path in \
  "/api/home/fixtures" \
  "/api/schedule?owner=team" \
  "/api/home/activity?limit=10" \
  "/api/home/changelog?limit=5"
do
  code="$(curl -s -o /tmp/pv-smoke-body -w "%{http_code}" -b "$COOKIE_JAR" --max-time 45 "$BASE_URL$path" || echo 000)"
  bytes="$(wc -c </tmp/pv-smoke-body | tr -d ' ')"
  if [[ "$code" == "200" && "$bytes" -gt 20 ]]; then
    pass "$path ($code, ${bytes}b)"
  else
    bad "$path → $code (${bytes}b) — home widgets will stick on Loading"
  fi
done

# Key tool pages must open (not 404/502) after a sidebar restore.
for path in \
  "/set-piece-pre-match" \
  "/player-cards" \
  "/blocks-analysis" \
  "/schedule" \
  "/strategy-tracker" \
  "/players-strategy" \
  "/pre-match-handout"
do
  code="$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" --max-time 30 "$BASE_URL$path" || echo 000)"
  if [[ "$code" == "200" ]]; then
    pass "page $path"
  else
    bad "page $path → $code — link in sidebar but tool broken"
  fi
done

if [[ "$fail" -ne 0 ]]; then
  echo ""
  echo "SMOKE FAILED — do not tell staff the site is ready."
  echo "Fix and re-run: bash deploy/smoke-live.sh"
  exit 1
fi

echo ""
echo "SMOKE PASSED — safe for staff / owner login."
exit 0
