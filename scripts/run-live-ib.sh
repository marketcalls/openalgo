#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

load_env
resolve_lean_paths
configure_python_runtime
resolve_strategy "${1:-}" "${2:-}"

if [[ -z "${IB_ACCOUNT:-}" ]]; then
  echo "Error: IB_ACCOUNT is required for live runs. Set it in .env"
  exit 1
fi

if [[ "${LIVE_CONFIRM:-}" != "true" ]]; then
  echo "Safety check: set LIVE_CONFIRM=true to run live mode"
  echo "Example: LIVE_CONFIRM=true scripts/run-live-ib.sh strategies/python/YourAlgo.py YourAlgo"
  exit 1
fi

mkdir -p "$REPO_ROOT/.tmp"
CONFIG_PATH="$REPO_ROOT/.tmp/live-ib.config.json"
TEMPLATE_PATH="$REPO_ROOT/config/templates/live-interactive.template.json"

generate_config "$TEMPLATE_PATH" "$CONFIG_PATH"

echo "Running live-interactive against IB"
echo "  strategy: $STRATEGY_PATH"
echo "  class:    $ALGORITHM_TYPE_NAME"
echo "  account:  $IB_ACCOUNT"
echo "  host:     ${IB_HOST:-127.0.0.1}:${IB_PORT:-4002}"
echo "  mode:     ${IB_TRADING_MODE:-paper}"
echo "  pyvenv:   ${PYTHON_VENV:-<not-set>}"
echo "  pydll:    ${PYTHONNET_PYDLL:-<not-set>}"
echo "  config:   $CONFIG_PATH"

cd "$LEAN_LAUNCHER_DIR"
dotnet "$LEAN_LAUNCHER_DLL" --config "$CONFIG_PATH"
