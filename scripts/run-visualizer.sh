#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

load_env

VISUALIZER_PORT="${1:-${VISUALIZER_PORT:-3000}}"
VISUALIZER_OPEN="${VISUALIZER_OPEN:-true}"
VISUALIZER_RUN_ID="${VISUALIZER_RUN_ID:-}"
VISUALIZER_RESULTS_DIR="${VISUALIZER_RESULTS_DIR:-$REPO_ROOT/results}"

OPEN_ARGS=()
if [[ "$VISUALIZER_OPEN" == "false" ]]; then
  OPEN_ARGS=(--server.headless true)
fi

RUN_ID_ARGS=()
if [[ -n "$VISUALIZER_RUN_ID" ]]; then
  RUN_ID_ARGS=(-- --run-id "$VISUALIZER_RUN_ID")
fi

if [[ ${#RUN_ID_ARGS[@]} -eq 0 ]]; then
  RUN_ID_ARGS=(--)
fi

# Resolve Python from the Lean venv if available, falling back to PATH python3.
_DEFAULT_PYTHON_VENV="${LEAN_REPO:-$(cd "$REPO_ROOT/../Lean" && pwd 2>/dev/null || true)}/.conda/lean-py311"
_VENV="${PYTHON_VENV:-$_DEFAULT_PYTHON_VENV}"
if [[ -x "$_VENV/bin/python" ]]; then
  PYTHON_BIN="$_VENV/bin/python"
else
  PYTHON_BIN="python3"
fi

echo "Starting Streamlit visualizer"
echo "  results: $VISUALIZER_RESULTS_DIR"
echo "  app:     $REPO_ROOT/tools/visualizer/streamlit_app.py"
echo "  port:    $VISUALIZER_PORT"
echo "  python:  $PYTHON_BIN"

if ! "$PYTHON_BIN" -m streamlit --help >/dev/null 2>&1; then
  echo "Error: Streamlit is not installed in this Python environment."
  echo "Install it with: $PYTHON_BIN -m pip install streamlit"
  exit 3
fi

"$PYTHON_BIN" -m streamlit run "$REPO_ROOT/tools/visualizer/streamlit_app.py" \
  --server.port "$VISUALIZER_PORT" \
  --server.address 127.0.0.1 \
  "${OPEN_ARGS[@]+"${OPEN_ARGS[@]}"}" \
  "${RUN_ID_ARGS[@]+"${RUN_ID_ARGS[@]}"}" \
  --results-dir "$VISUALIZER_RESULTS_DIR"