#!/usr/bin/env bash
# Fail the deploy if Fixture Planner JS would crash staff lists again.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
JS="$ROOT/static/fixture-planner.js"
HTML="$ROOT/standalone/fixture-planner.html"

fail=0
if [[ ! -f "$JS" ]]; then
  echo "ERROR: missing $JS"
  exit 1
fi
if grep -Fq 'assignment.staff.split' "$JS"; then
  echo "ERROR: $JS still calls assignment.staff.split — this is the red banner crash."
  fail=1
fi
if ! grep -Fq 'function staffNames' "$JS"; then
  echo "ERROR: $JS is missing staffNames() — old JS, do not ship."
  fail=1
fi
if [[ -f "$HTML" ]] && ! grep -Fq 'fp-comp-scope' "$HTML"; then
  echo "ERROR: $HTML is missing Leagues/Cups tabs — stale Fixture Planner page."
  fail=1
fi
if [[ "$fail" -ne 0 ]]; then
  echo "Refusing to deploy Fixture Planner."
  exit 1
fi
echo "✓ Fixture Planner JS/HTML guard passed"
