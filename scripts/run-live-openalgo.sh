#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

load_env
resolve_lean_paths
configure_python_runtime
resolve_strategy "${1:-strategies/python/openalgo_order_placement_test/OpenAlgoOrderPlacementTest.py}" "${2:-OpenAlgoOrderPlacementTest}"

OPENALGO_BROKERAGE_PROJECT="${OPENALGO_BROKERAGE_PROJECT:-/Users/arifkhan/github/Lean-Brokerages/Lean.Brokerages.OpenAlgo/QuantConnect.OpenAlgoBrokerage/QuantConnect.OpenAlgoBrokerage.csproj}"
OPENALGO_BROKERAGE_DIR="$(cd "$(dirname "$OPENALGO_BROKERAGE_PROJECT")" && pwd)"
OPENALGO_BROKERAGE_OUTPUT="$OPENALGO_BROKERAGE_DIR/bin/Debug"

if [[ "${LIVE_CONFIRM:-}" != "true" ]]; then
  echo "Safety check: set LIVE_CONFIRM=true to run live mode"
  exit 1
fi

if [[ "${OPENALGO_PLACE_TEST_ORDERS:-false}" == "true" && "${LIVE_CONFIRM_OPENALGO_ORDER:-}" != "true" ]]; then
  echo "Safety check: OPENALGO_PLACE_TEST_ORDERS=true can place live orders."
  echo "To intentionally submit this throwaway test, also set LIVE_CONFIRM_OPENALGO_ORDER=true."
  exit 1
fi

if [[ -z "${OPENALGO_API_KEY:-}" ]]; then
  echo "Error: OPENALGO_API_KEY is required. Set it in the strategy .env"
  exit 1
fi

mkdir -p "$REPO_ROOT/.tmp"
CONFIG_PATH="$REPO_ROOT/.tmp/live-openalgo-${ALGORITHM_TYPE_NAME}.config.json"
TEMPLATE_PATH="$REPO_ROOT/config/templates/live-openalgo.template.json"

echo "Building OpenAlgo brokerage plugin"
dotnet build "$OPENALGO_BROKERAGE_PROJECT" /p:Configuration=Debug /p:LeanRoot="$LEAN_REPO"

echo "Copying OpenAlgo brokerage plugin into Lean launcher output"
find "$OPENALGO_BROKERAGE_OUTPUT" -type f \( -name '*.dll' -o -name '*.pdb' -o -name '*.deps.json' \) -exec cp {} "$LEAN_LAUNCHER_DIR/" \;

generate_config "$TEMPLATE_PATH" "$CONFIG_PATH"

echo "Running live OpenAlgo"
echo "  strategy:          $STRATEGY_PATH"
echo "  class:             $ALGORITHM_TYPE_NAME"
echo "  brokerage project: $OPENALGO_BROKERAGE_PROJECT"
echo "  host:              ${OPENALGO_HOST:-http://127.0.0.1:5000}"
echo "  ws:                ${OPENALGO_WS_URL:-ws://127.0.0.1:8443}"
echo "  product type:      ${OPENALGO_PRODUCT_TYPE:-MIS}"
echo "  place orders:      ${OPENALGO_PLACE_TEST_ORDERS:-false}"
echo "  config:            $CONFIG_PATH"

cd "$LEAN_LAUNCHER_DIR"
dotnet "$LEAN_LAUNCHER_DLL" --config "$CONFIG_PATH"
