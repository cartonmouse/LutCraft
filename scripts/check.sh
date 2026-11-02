#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$PROJECT_ROOT/backend"
../.venv/bin/python -m pytest -q
cd "$PROJECT_ROOT/frontend"
"$LUT_PNPM" test
"$LUT_PNPM" run build

cd "$PROJECT_ROOT/integrations/openclaw/plugin"
node --experimental-strip-types --test test/*.test.mjs
