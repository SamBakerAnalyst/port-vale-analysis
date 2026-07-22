#!/usr/bin/env bash
# Alias — same as "Deploy to Website.command"
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
exec bash "$ROOT/Deploy to Website.command"
