#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

load_env
resolve_lean_paths
configure_python_runtime
resolve_strategy "${1:-}" "${2:-}"

mkdir -p "$REPO_ROOT/.tmp"
CONFIG_PATH="$REPO_ROOT/.tmp/backtest.config.json"
TEMPLATE_PATH="$REPO_ROOT/config/templates/backtest.template.json"

generate_config "$TEMPLATE_PATH" "$CONFIG_PATH"

echo "Running backtest"
echo "  strategy: $STRATEGY_PATH"
echo "  class:    $ALGORITHM_TYPE_NAME"
echo "  pyvenv:   ${PYTHON_VENV:-<not-set>}"
echo "  pydll:    ${PYTHONNET_PYDLL:-<not-set>}"
echo "  config:   $CONFIG_PATH"

cd "$LEAN_LAUNCHER_DIR"
set +e
dotnet "$LEAN_LAUNCHER_DLL" --config "$CONFIG_PATH"
BACKTEST_EXIT=$?
set -e

if [[ $BACKTEST_EXIT -ne 0 ]]; then
	echo "Backtest failed with exit code: $BACKTEST_EXIT"
	exit "$BACKTEST_EXIT"
fi

VISUALIZER_PORT="${VISUALIZER_PORT:-3000}"
VISUALIZER_ENABLED="${VISUALIZER_ENABLED:-true}"

if [[ "$VISUALIZER_ENABLED" == "true" ]]; then
	echo "Archiving run and launching visualizer on port $VISUALIZER_PORT"
	python3 "$REPO_ROOT/tools/visualizer/server.py" archive-and-serve \
		--launcher-dir "$LEAN_LAUNCHER_DIR" \
		--algorithm-type "$ALGORITHM_TYPE_NAME" \
		--results-dir "$REPO_ROOT/results" \
		--port "$VISUALIZER_PORT" \
		--open
else
	echo "Visualizer disabled (set VISUALIZER_ENABLED=true to enable)."
fi
