#!/usr/bin/env bash
# Refuse any Caddyfile that can send Port Vale Live (pvfc / staff IP) to LMS.
# LMS once joined the Live Docker network as service name "hub"; proxying
# hub:8000 then served the demo on the staff hostname.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FILE="${1:-$ROOT/deploy/Caddyfile.ip}"

if [[ ! -f "$FILE" ]]; then
  echo "ERROR: missing $FILE"
  exit 1
fi

if grep -qE 'reverse_proxy[[:space:]]+hub:8000' "$FILE"; then
  echo "ERROR: $FILE still proxies hub:8000."
  echo "That Docker DNS name is shared. It put LMS on pvfc.sportsanalysis.ai"
  echo "and http://178.128.161.215/. Proxy the Vale container by name:"
  echo "  reverse_proxy port-vale-analysis-hub-1:8000"
  exit 1
fi

if ! grep -qE 'reverse_proxy[[:space:]]+port-vale-analysis-hub-1:8000' "$FILE"; then
  echo "ERROR: $FILE must proxy port-vale-analysis-hub-1:8000 for Port Vale Live."
  exit 1
fi

if ! grep -qE 'pvfc\.sportsanalysis\.ai' "$FILE"; then
  echo "ERROR: $FILE is missing pvfc.sportsanalysis.ai — do not ship an IP-only Caddyfile."
  exit 1
fi

if ! grep -qE 'lmsc\.sportsanalysis\.ai' "$FILE"; then
  echo "ERROR: $FILE is missing lmsc.sportsanalysis.ai — LMS must stay on its own host."
  exit 1
fi

if ! grep -qE 'reverse_proxy[[:space:]]+lms:8000' "$FILE"; then
  echo "ERROR: $FILE must proxy LMS only via lms:8000 (lmsc.sportsanalysis.ai)."
  exit 1
fi

echo "  ✓ Live Caddyfile keeps Port Vale on pvfc / :80 and LMS on lmsc only"
