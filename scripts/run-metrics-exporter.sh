#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

load_env
resolve_lean_paths

ALGORITHM_TYPE_NAME="${1:-MesSimpleBuySellTestStrategy}"
EXPORTER_HOST="${EXPORTER_HOST:-127.0.0.1}"
EXPORTER_PORT="${EXPORTER_PORT:-9108}"
SYMBOL_PREFIX="${SYMBOL_PREFIX:-}"

python3 "$REPO_ROOT/tools/grafana/lean_exporter.py" \
  --launcher-dir "$LEAN_LAUNCHER_DIR" \
  --algorithm "$ALGORITHM_TYPE_NAME" \
  --host "$EXPORTER_HOST" \
  --port "$EXPORTER_PORT" \
  --symbol-prefix "$SYMBOL_PREFIX"
