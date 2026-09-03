#!/usr/bin/env bash
# Post-deploy smoke check for Port Vale Live.
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

echo "Smoke check → Port Vale Live ($BASE_URL)"

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
    "Pre-Match Report"
    "Set Piece Pre-Match"
    "Player Cards"
    "Match Day Countdown"
    "xG Chance Analysis"
    "Blocks Analysis"
    "Who To Scout"
    "Watch list"
    "Fixture Planner"
    "Played Fixtures"
    "Scouting Address Tool"
    "Scout Summary"
    "Scouts Calendar"
    "Squad Availability"
    "Presentations"
  )
fi

MIN_SIDEBAR=12
if [[ "${#REQUIRED_APPS[@]}" -lt "$MIN_SIDEBAR" ]]; then
  bad "active sidebar title count ${#REQUIRED_APPS[@]} < $MIN_SIDEBAR — essentials incomplete"
else
  pass "active sidebar title count ${#REQUIRED_APPS[@]}"
fi

for need in "${REQUIRED_APPS[@]}"; do
  if grep -Fq "\"$need\"" "$apps_file" || grep -Fq "$need" "$apps_file"; then
    pass "sidebar live: $need"
  else
    bad "sidebar MISSING live essential: $need"
  fi
done

# Essentials must not be flagged comingSoon on live.
for need in "${REQUIRED_APPS[@]}"; do
  if python3 - <<PY 2>/dev/null
import json
data = json.load(open("/tmp/pv-smoke-apps.json"))
for app in data.get("apps") or []:
    if app.get("title") == """$need""" and app.get("comingSoon"):
        raise SystemExit(1)
raise SystemExit(0)
PY
  then
    pass "essential open: $need"
  else
    bad "essential marked comingSoon: $need"
  fi
done
# Recruitment launch shape: Watch list open, Pipelines + Scoutable Teams held back
# until every scout has a personal login. Assert both halves so neither drifts.
check_launch_shape() {
  python3 - "$1" <<'PY'
import json, sys
want_open = {"Who To Scout", "Watch list"}
want_held = {"Player Pipelines", "Scoutable Teams"}
data = json.load(open("/tmp/pv-smoke-apps.json"))
by_title = {a.get("title"): a for a in data.get("apps") or []}
problems = []
for title in sorted(want_open):
    app = by_title.get(title)
    if app is None:
        problems.append(f"{title} missing from /api/apps")
    elif app.get("comingSoon"):
        problems.append(f"{title} is comingSoon but should be open")
for title in sorted(want_held):
    app = by_title.get(title)
    if app is not None and not app.get("comingSoon"):
        problems.append(f"{title} is open but should be held back")
if problems:
    print("; ".join(problems))
    raise SystemExit(1)
raise SystemExit(0)
PY
}
if shape_err="$(check_launch_shape "$apps_file")"; then
  pass "recruitment launch shape (Watch list open, Pipelines held)"
else
  bad "recruitment launch shape wrong: ${shape_err:-unknown}"
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

# Fixture planner JS must handle staff-as-list. GitHub deploys of old main
# used to restore assignment.staff.split and crash the page.
curl -s --max-time 15 "$BASE_URL/static/fixture-planner.js" -o /tmp/pv-smoke-fp.js || true
if grep -Fq 'function staffNames' /tmp/pv-smoke-fp.js; then
  pass "fixture-planner.js has staffNames"
else
  bad "fixture-planner.js missing staffNames — staff list crash will return"
fi
if grep -Fq 'assignment.staff.split' /tmp/pv-smoke-fp.js; then
  bad "fixture-planner.js still calls assignment.staff.split — red banner will show"
else
  pass "fixture-planner.js does not call assignment.staff.split"
fi
fp_page="$(curl -s -b "$COOKIE_JAR" --max-time 20 "$BASE_URL/fixture-planner" || true)"
if echo "$fp_page" | grep -q 'fp-comp-scope'; then
  pass "fixture planner has Leagues/Cups tabs"
else
  bad "fixture planner HTML missing Leagues/Cups tabs — stale page"
fi

# Key tool pages must open (not 404/502) after a sidebar restore.
for path in \
  "/post-match" \
  "/set-piece-pre-match" \
  "/player-cards" \
  "/blocks-analysis" \
  "/schedule" \
  "/strategy-tracker" \
  "/players-strategy" \
  "/who-to-scout" \
  "/watch-list" \
  "/player-pipelines"
do
  code="$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" --max-time 30 "$BASE_URL$path" || echo 000)"
  if [[ "$code" == "200" ]]; then
    pass "page $path"
  else
    bad "page $path → $code — link in sidebar but tool broken"
  fi
done

# Suggest widget must be on the hub shell (every tool page also loads it).
curl -s --max-time 15 "$BASE_URL/static/hub-feedback.js" -o /tmp/pv-smoke-feedback.js || true
if grep -Fq "/api/feedback" /tmp/pv-smoke-feedback.js; then
  pass "hub-feedback.js present"
else
  bad "hub-feedback.js missing — Suggest button will not work on tools"
fi
if echo "$html" | grep -Fq "hub-feedback.js"; then
  pass "hub HTML loads Suggest widget"
else
  bad "hub HTML missing hub-feedback.js"
fi
if grep -Fq "Pre-Match Handout" "$apps_file"; then
  bad "sidebar still lists Pre-Match Handout — retired tool returned"
else
  pass "Pre-Match Handout retired from /api/apps"
fi

if [[ "$fail" -ne 0 ]]; then
  echo ""
  echo "SMOKE FAILED — do not tell staff Port Vale Live is ready."
  echo "Fix and re-run: bash deploy/smoke-live.sh"
  exit 1
fi

echo ""
echo "SMOKE PASSED — Port Vale Live safe for staff / owner login."
exit 0
