#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

load_env
resolve_lean_paths

ALGORITHM_TYPE_NAME="${1:-}"
if [[ -z "$ALGORITHM_TYPE_NAME" ]]; then
  echo "Usage: $0 <AlgorithmTypeName>"
  echo "Example: $0 MesSimpleBuySellTestStrategy"
  exit 1
fi

RUN_ID="$(python3 "$REPO_ROOT/tools/visualizer/server.py" ingest \
  --launcher-dir "$LEAN_LAUNCHER_DIR" \
  --algorithm-type "$ALGORITHM_TYPE_NAME" \
  --results-dir "$REPO_ROOT/results")"

echo "Archived run: $RUN_ID"

VISUALIZER_PORT="${VISUALIZER_PORT:-3000}"
VISUALIZER_RUN_ID="$RUN_ID" VISUALIZER_PORT="$VISUALIZER_PORT" "$REPO_ROOT/scripts/run-visualizer.sh"
