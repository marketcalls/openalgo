#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

load_env

VISUALIZER_PORT="${1:-${VISUALIZER_PORT:-3000}}"
VISUALIZER_OPEN="${VISUALIZER_OPEN:-true}"
VISUALIZER_RUN_ID="${VISUALIZER_RUN_ID:-}"

OPEN_ARGS=()
if [[ "$VISUALIZER_OPEN" == "true" ]]; then
  OPEN_ARGS=(--open)
fi

RUN_ID_ARGS=()
if [[ -n "$VISUALIZER_RUN_ID" ]]; then
  RUN_ID_ARGS=(--run-id "$VISUALIZER_RUN_ID")
fi

echo "Starting visualizer server"
echo "  results: $REPO_ROOT/results"
echo "  static:  $REPO_ROOT/tools/visualizer/static"
echo "  port:    $VISUALIZER_PORT"

python3 "$REPO_ROOT/tools/visualizer/server.py" serve \
  --results-dir "$REPO_ROOT/results" \
  --static-dir "$REPO_ROOT/tools/visualizer/static" \
  --port "$VISUALIZER_PORT" \
  "${OPEN_ARGS[@]+"${OPEN_ARGS[@]}"}" \
  "${RUN_ID_ARGS[@]+"${RUN_ID_ARGS[@]}"}"