#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$PROJECT_ROOT"
if [ ! -x .venv/bin/python ] || [ ! -f frontend/dist/index.html ]; then
  echo '请先执行 bash scripts/setup.sh 完成环境与前端构建。'
  exit 1
fi
exec .venv/bin/python scripts/serve.py
