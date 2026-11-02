#!/usr/bin/env bash
set -euo pipefail
PROTO_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$PROTO_DIR/../.." && pwd)"
exec "$PROJECT_DIR/.venv/bin/python" "$PROTO_DIR/server.py"
