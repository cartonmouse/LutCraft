#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$PROJECT_ROOT"
if [ ! -x .venv/bin/python ]; then
  if [ -x "$RUNTIME_ROOT/python/bin/python3" ]; then
    "$RUNTIME_ROOT/python/bin/python3" -m venv .venv
  else
    python3 -m venv .venv
  fi
fi
.venv/bin/python -m pip install -r backend/requirements.lock
if [ ! -f .env ]; then cp .env.example .env; chmod 600 .env; fi
cd frontend
"$LUT_PNPM" install --frozen-lockfile
"$LUT_PNPM" run build
