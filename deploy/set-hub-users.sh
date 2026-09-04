#!/usr/bin/env bash
# Provision personal staff logins (HUB_USERS) on the droplet.
#
#   bash deploy/set-hub-users.sh ~/portvale-accounts.json
#
# Accounts file shape (keep it OUTSIDE this repo — it holds passwords):
#   [
#     {"username":"jsmith","password":"...","role":"scouts","display_name":"Joe Smith"}
#   ]
#
# Roles: admin (everything) | scouts (recruitment + scouts) | analysis (analysis only).
# display_name is what lands in added_by / moved_by / note authors.
#
# Live and Staging both read /opt/port-vale-analysis/.env, and .env is excluded
# from deploy rsync, so accounts survive future deploys. The admin login
# (TEAM_USERNAME / TEAM_PASSWORD) is untouched by this script.
set -euo pipefail

ACCOUNTS_FILE="${1:-}"
if [[ -z "$ACCOUNTS_FILE" || ! -f "$ACCOUNTS_FILE" ]]; then
  echo "Usage: bash deploy/set-hub-users.sh /path/to/accounts.json"
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVER="root@178.128.161.215"
REMOTE="/opt/port-vale-analysis"

SSH_KEY="${PORTVALE_SSH_KEY:-}"
for candidate in "$HOME/.ssh/portvale_deploy" "$HOME/.ssh/portvale_analysis" "$HOME/.ssh/id_ed25519"; do
  if [[ -z "$SSH_KEY" && -f "$candidate" ]]; then SSH_KEY="$candidate"; fi
done
SSH_OPTS=(-o StrictHostKeyChecking=no)
if [[ -n "$SSH_KEY" && -f "$SSH_KEY" ]]; then
  SSH_OPTS=(-i "$SSH_KEY" -o IdentitiesOnly=yes -o StrictHostKeyChecking=no)
fi

PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || PY=python3

# Validate before touching the server — a malformed HUB_USERS silently drops
# every personal login and leaves only the admin account working.
COMPACT="$("$PY" - "$ACCOUNTS_FILE" <<'PYEOF'
import json, sys

path = sys.argv[1]
try:
    rows = json.load(open(path, encoding="utf-8"))
except json.JSONDecodeError as exc:
    sys.exit(f"accounts file is not valid JSON: {exc}")

if not isinstance(rows, list) or not rows:
    sys.exit("accounts file must be a non-empty JSON list")

allowed_roles = {"admin", "scouts", "analysis"}
seen: set[str] = set()
clean = []
for i, row in enumerate(rows, 1):
    if not isinstance(row, dict):
        sys.exit(f"entry {i} is not an object")
    username = str(row.get("username") or "").strip()
    password = str(row.get("password") or "")
    role = str(row.get("role") or "").strip().lower()
    display = str(row.get("display_name") or username).strip()
    if not username:
        sys.exit(f"entry {i} has no username")
    if username.casefold() in seen:
        sys.exit(f"duplicate username: {username}")
    seen.add(username.casefold())
    if len(password) < 8:
        sys.exit(f"{username}: password must be at least 8 characters")
    if "'" in password or "'" in username:
        sys.exit(f"{username}: single quotes break .env quoting — use another character")
    if role not in allowed_roles:
        sys.exit(f"{username}: role must be one of {sorted(allowed_roles)}, got {role!r}")
    clean.append(
        {"username": username, "password": password, "role": role, "display_name": display}
    )

print(json.dumps(clean, separators=(",", ":"), ensure_ascii=False))
for row in clean:
    print(f"  {row['display_name']} ({row['username']}) -> {row['role']}", file=sys.stderr)
PYEOF
)"

echo "Accounts validated. Writing HUB_USERS to $SERVER:$REMOTE/.env"

PAYLOAD="$(printf '%s' "$COMPACT" | base64 | tr -d '\n')"

ssh "${SSH_OPTS[@]}" "$SERVER" "HUB_USERS_B64='$PAYLOAD' bash -s" <<'REMOTEEOF'
set -euo pipefail
cd /opt/port-vale-analysis

backup=".env.backup-$(date +%Y%m%d-%H%M%S)"
cp .env "$backup"
echo "  .env backed up to $backup"

json="$(printf '%s' "$HUB_USERS_B64" | base64 -d)"
grep -v '^HUB_USERS=' .env > .env.next || true
printf "HUB_USERS='%s'\n" "$json" >> .env.next
mv .env.next .env
echo "  HUB_USERS written ($(printf '%s' "$json" | wc -c | tr -d ' ') bytes)"

echo "  restarting Live…"
docker compose --project-directory /opt/port-vale-analysis \
  -f deploy/docker-compose.ip.yml up -d >/dev/null
echo "  restarting Staging…"
docker compose --project-directory /opt/port-vale-analysis \
  -f deploy/docker-compose.staging.yml up -d >/dev/null
REMOTEEOF

echo "Waiting for both environments to come back…"
for base in "http://178.128.161.215" "http://178.128.161.215:8080"; do
  for _ in $(seq 1 30); do
    code="$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$base/health" || echo 000)"
    [[ "$code" == "200" ]] && break
    sleep 2
  done
  echo "  $base/health -> ${code:-000}"
done

# Confirm each account can actually sign in, without echoing passwords.
echo "Login check (Live):"
"$PY" - "$ACCOUNTS_FILE" <<'PYEOF'
import json, sys, urllib.error, urllib.request

rows = json.load(open(sys.argv[1], encoding="utf-8"))
base = "http://178.128.161.215"
failed = 0
for row in rows:
    body = json.dumps(
        {"username": row["username"], "password": row["password"]}
    ).encode()
    req = urllib.request.Request(
        f"{base}/api/auth/login",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            got = json.loads(res.read()).get("role")
        want = row.get("role")
        ok = got == want
        print(f"  {'ok ' if ok else '!! '}{row['username']:14s} role={got} (want {want})")
        failed += 0 if ok else 1
    except urllib.error.HTTPError as exc:
        print(f"  !! {row['username']:14s} login failed: HTTP {exc.code}")
        failed += 1
    except Exception as exc:  # noqa: BLE001 - report and keep going
        print(f"  !! {row['username']:14s} login error: {exc}")
        failed += 1
sys.exit(1 if failed else 0)
PYEOF

echo ""
echo "✓ Personal logins live. Sign in at http://178.128.161.215/login"
echo "  Staging uses the same accounts: http://178.128.161.215:8080/login"
