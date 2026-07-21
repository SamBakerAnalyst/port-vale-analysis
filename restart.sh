#!/usr/bin/env bash
# Stop anything on port 8000, then start the analysis hub server in the background.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
LOG="${TMPDIR:-/tmp}/impect-hub-server.log"
PIDFILE="${TMPDIR:-/tmp}/impect-hub-server.pid"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

if [[ ! -d .venv ]]; then
  echo "$(date -Iseconds) missing .venv in $ROOT — run: python3 -m venv .venv && pip install -r requirements.txt" >>"$LOG"
  exit 1
fi

unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
unset GIT_HTTP_PROXY GIT_HTTPS_PROXY SOCKS_PROXY SOCKS5_PROXY socks_proxy socks5_proxy

health_ok() {
  curl -sf --max-time 2 "http://${HOST}:${PORT}/health" >/dev/null 2>&1
}

sleep 1

if command -v lsof >/dev/null 2>&1; then
  PIDS="$(lsof -ti:"${PORT}" 2>/dev/null || true)"
  if [[ -n "$PIDS" ]]; then
    kill $PIDS 2>/dev/null || true
    sleep 0.5
    PIDS="$(lsof -ti:"${PORT}" 2>/dev/null || true)"
    if [[ -n "$PIDS" ]]; then
      kill -9 $PIDS 2>/dev/null || true
    fi
  fi
fi

echo "$(date -Iseconds) starting uvicorn on :${PORT}" >>"$LOG"
nohup .venv/bin/uvicorn app.main:app --host "$HOST" --port "$PORT" >>"$LOG" 2>&1 &
UV_PID=$!
echo "$UV_PID" >"$PIDFILE"
echo "$(date -Iseconds) pid $UV_PID" >>"$LOG"
disown "$UV_PID" 2>/dev/null || true

for _ in $(seq 1 30); do
  if health_ok; then
    echo "$(date -Iseconds) listening on :${PORT}" >>"$LOG"
    exit 0
  fi
  if ! kill -0 "$UV_PID" 2>/dev/null; then
    echo "$(date -Iseconds) uvicorn exited before bind (pid $UV_PID)" >>"$LOG"
    exit 1
  fi
  sleep 0.2
done

echo "$(date -Iseconds) timeout waiting for :${PORT} (pid $UV_PID)" >>"$LOG"
exit 1
