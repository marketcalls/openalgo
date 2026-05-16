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
printf '\n' | dotnet "$LEAN_LAUNCHER_DLL" --config "$CONFIG_PATH"
BACKTEST_EXIT=$?
set -e

if [[ $BACKTEST_EXIT -ne 0 ]]; then
	SUMMARY_JSON="$LEAN_LAUNCHER_DIR/${ALGORITHM_TYPE_NAME}-summary.json"
	DETAIL_JSON="$LEAN_LAUNCHER_DIR/${ALGORITHM_TYPE_NAME}.json"
	if [[ -f "$SUMMARY_JSON" && -f "$DETAIL_JSON" ]]; then
		echo "Backtest process exited with code $BACKTEST_EXIT, but result artifacts were generated. Continuing."
	else
		echo "Backtest failed with exit code: $BACKTEST_EXIT"
		exit "$BACKTEST_EXIT"
	fi
fi

VISUALIZER_PORT="${VISUALIZER_PORT:-3000}"
VISUALIZER_ENABLED="${VISUALIZER_ENABLED:-true}"

if [[ "$VISUALIZER_ENABLED" == "true" ]]; then
	echo "Archiving run and launching Streamlit visualizer on port $VISUALIZER_PORT"
	RUN_ID="$(python3 "$REPO_ROOT/tools/visualizer/server.py" ingest \
		--launcher-dir "$LEAN_LAUNCHER_DIR" \
		--algorithm-type "$ALGORITHM_TYPE_NAME" \
		--results-dir "$REPO_ROOT/results")"
	echo "Archived run: $RUN_ID"
	set +e
	VISUALIZER_RUN_ID="$RUN_ID" VISUALIZER_PORT="$VISUALIZER_PORT" "$REPO_ROOT/scripts/run-visualizer.sh"
	VISUALIZER_EXIT=$?
	set -e
	if [[ $VISUALIZER_EXIT -ne 0 ]]; then
		echo "Warning: visualizer failed to start (exit $VISUALIZER_EXIT)."
		echo "Run manually after installing dependencies: python3 -m pip install streamlit"
	fi
else
	echo "Visualizer disabled (set VISUALIZER_ENABLED=true to enable)."
fi
