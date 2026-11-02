#!/usr/bin/env bash
# Shared local tool discovery; never changes system configuration.
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_ROOT="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies"
if ! command -v node >/dev/null 2>&1 && [ -x "$RUNTIME_ROOT/node/bin/node" ]; then
  export PATH="$RUNTIME_ROOT/node/bin:$PATH"
fi
if command -v pnpm >/dev/null 2>&1; then
  LUT_PNPM="$(command -v pnpm)"
elif [ -x "$RUNTIME_ROOT/bin/fallback/pnpm" ]; then
  LUT_PNPM="$RUNTIME_ROOT/bin/fallback/pnpm"
else
  LUT_PNPM="pnpm"
fi
export PROJECT_ROOT LUT_PNPM
