#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

load_env
resolve_lean_paths
configure_python_runtime
resolve_strategy "${1:-strategies/python/FyersBrokerageSmokeTestStrategy.py}" "${2:-FyersBrokerageSmokeTestStrategy}"

FYERS_BROKERAGE_PROJECT="${FYERS_BROKERAGE_PROJECT:-/Users/arifkhan/github/Lean-Brokerages/Lean.Brokerages.Fyers/QuantConnect.FyersBrokerage/QuantConnect.FyersBrokerage.csproj}"
FYERS_BROKERAGE_DIR="$(cd "$(dirname "$FYERS_BROKERAGE_PROJECT")" && pwd)"
FYERS_BROKERAGE_OUTPUT="$FYERS_BROKERAGE_DIR/bin/Debug"

if [[ "${LIVE_CONFIRM:-}" != "true" ]]; then
  echo "Safety check: set LIVE_CONFIRM=true to run live mode"
  echo "Example: LIVE_CONFIRM=true scripts/run-live-fyers.sh"
  exit 1
fi

if [[ "${FYERS_PLACE_TEST_ORDER:-false}" == "true" && "${LIVE_CONFIRM_FYERS_ORDER:-}" != "true" ]]; then
  echo "Safety check: FYERS_PLACE_TEST_ORDER=true can place a live order."
  echo "To test connect/data only, leave FYERS_PLACE_TEST_ORDER=false."
  echo "To intentionally submit the test order, also set LIVE_CONFIRM_FYERS_ORDER=true."
  exit 1
fi

if [[ -z "${FYERS_CLIENT_ID:-}" ]]; then
  echo "Error: FYERS_CLIENT_ID is required. Set it in .env"
  exit 1
fi

if [[ -z "${FYERS_SECRET_KEY:-}" ]]; then
  echo "Error: FYERS_SECRET_KEY is required. Set it in .env"
  exit 1
fi

mkdir -p "$REPO_ROOT/.tmp"
CONFIG_PATH="$REPO_ROOT/.tmp/live-fyers.config.json"
TEMPLATE_PATH="$REPO_ROOT/config/templates/live-fyers.template.json"

echo "Building FYERS brokerage plugin"
dotnet build "$FYERS_BROKERAGE_PROJECT" /p:Configuration=Debug /p:LeanRoot="$LEAN_REPO"

echo "Copying FYERS brokerage plugin into Lean launcher output"
rsync -a \
  --include='QuantConnect.FyersBrokerage.dll' \
  --include='QuantConnect.FyersBrokerage.pdb' \
  --include='QuantConnect.FyersBrokerage.deps.json' \
  --include='fyerscsharpsdk.dll' \
  --include='hypersynclib.dll' \
  --include='protobuf-net*.dll' \
  --include='RestSharp.dll' \
  --include='System.Security.Cryptography.ProtectedData.dll' \
  --exclude='*' \
  "$FYERS_BROKERAGE_OUTPUT/" "$LEAN_LAUNCHER_DIR/"

generate_config "$TEMPLATE_PATH" "$CONFIG_PATH"

echo "Running live FYERS"
echo "  strategy:          $STRATEGY_PATH"
echo "  class:             $ALGORITHM_TYPE_NAME"
echo "  brokerage project: $FYERS_BROKERAGE_PROJECT"
echo "  symbol:            ${FYERS_TEST_SYMBOL:-SBIN}"
echo "  place order:       ${FYERS_PLACE_TEST_ORDER:-false}"
echo "  pyvenv:            ${PYTHON_VENV:-<not-set>}"
echo "  pydll:             ${PYTHONNET_PYDLL:-<not-set>}"
echo "  config:            $CONFIG_PATH"

cd "$LEAN_LAUNCHER_DIR"
dotnet "$LEAN_LAUNCHER_DLL" --config "$CONFIG_PATH"
