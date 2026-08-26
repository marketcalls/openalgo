#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
LEAN_ROOT="${LEAN_ROOT:-$APP_ROOT/../Lean}"
STRATEGY_PATH="${1:?strategy path is required}"
ALGORITHM_TYPE_NAME="${2:-$(basename "$STRATEGY_PATH" .py)}"
RUNNER="${STRATEGY_RUNNER:-$APP_ROOT/scripts/run-live-openalgo.sh}"
[[ -x "$RUNNER" ]] || { echo "remote-run: runner is not executable: $RUNNER" >&2; exit 1; }
LEAN_REPO="$LEAN_ROOT" LEAN_LAUNCHER_DIR="${LEAN_LAUNCHER_DIR:-$LEAN_ROOT/Launcher/bin/Debug}" \
  "$RUNNER" "$STRATEGY_PATH" "$ALGORITHM_TYPE_NAME"
