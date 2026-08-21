#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

load_env
resolve_lean_paths
configure_python_runtime
resolve_strategy "${1:-strategies/python/nifty_weekly_momentum/strategy.py}" "${2:-NiftyWeeklyMomentumStrategy}"

OPENALGO_BROKERAGE_PROJECT="${OPENALGO_BROKERAGE_PROJECT:-/Users/arifkhan/github/Lean-Brokerages/Lean.Brokerages.OpenAlgo/QuantConnect.OpenAlgoBrokerage/QuantConnect.OpenAlgoBrokerage.csproj}"
OPENALGO_BROKERAGE_DIR="$(cd "$(dirname "$OPENALGO_BROKERAGE_PROJECT")" && pwd)"
OPENALGO_BROKERAGE_OUTPUT="$OPENALGO_BROKERAGE_DIR/bin/Debug"

# ── Safety gates ─────────────────────────────────────────────────────
MODE="${NWM_MODE:-data-only}"  # data-only | signal-only | paper | live

case "$MODE" in
  data-only|signal-only|paper|live) ;;
  *)
    echo "Error: NWM_MODE must be data-only, signal-only, paper, or live"
    exit 1
    ;;
esac

if [[ "$MODE" == "live" && "${LIVE_CONFIRM:-}" != "true" ]]; then
  echo "Safety check: set LIVE_CONFIRM=true to run live mode"
  exit 1
fi

if [[ "$MODE" == "live" && "${LIVE_CONFIRM_NWM_ORDER:-}" != "true" ]]; then
  echo "Safety check: LIVE_CONFIRM_NWM_ORDER=true required for live option orders"
  exit 1
fi

if [[ -z "${OPENALGO_API_KEY:-}" ]]; then
  echo "Error: OPENALGO_API_KEY is required"
  exit 1
fi

# ── Validate weight snapshot ────────────────────────────────────────
echo "Validating NIFTY 50 weight snapshot..."
python3 "$REPO_ROOT/scripts/validate-nifty-weights.py" || {
  echo "Error: Weight validation failed"
  exit 1
}

# ── Resolve futures contracts (requires OpenAlgo running) ────────────
FUTURES_MAP_PATH="$REPO_ROOT/.tmp/nifty-futures-map-$(date +%F).json"
echo "Resolving NIFTY 50 constituent futures..."
python3 "$REPO_ROOT/scripts/resolve-nifty-futures.py" \
  --host "${OPENALGO_HOST:-http://127.0.0.1:5000}" \
  --api-key "$OPENALGO_API_KEY" \
  --output "$FUTURES_MAP_PATH" || {
  echo "Error: Futures resolution failed; no market-data subscription map was produced"
  exit 1
}

export NWM_MODE="$MODE"
export NWM_FUTURES_MAP_PATH="$FUTURES_MAP_PATH"

# ── Build and deploy OpenAlgo brokerage ──────────────────────────────
echo "Building OpenAlgo brokerage plugin"
dotnet build "$OPENALGO_BROKERAGE_PROJECT" /p:Configuration=Debug /p:LeanRoot="$LEAN_REPO"

echo "Copying OpenAlgo brokerage plugin into Lean launcher output"
find "$OPENALGO_BROKERAGE_OUTPUT" -type f \( -name '*.dll' -o -name '*.pdb' -o -name '*.deps.json' \) -exec cp {} "$LEAN_LAUNCHER_DIR/" \;

# ── Generate config ──────────────────────────────────────────────────
mkdir -p "$REPO_ROOT/.tmp"
CONFIG_PATH="$REPO_ROOT/.tmp/live-nifty-weekly-momentum.config.json"
TEMPLATE_PATH="$REPO_ROOT/config/templates/live-nifty-weekly-momentum.template.json"

generate_config "$TEMPLATE_PATH" "$CONFIG_PATH"

# ── Run ──────────────────────────────────────────────────────────────
echo "Running NIFTY Weekly Momentum Strategy"
echo "  mode:              $MODE"
echo "  strategy:          $STRATEGY_PATH"
echo "  class:             $ALGORITHM_TYPE_NAME"
echo "  host:              ${OPENALGO_HOST:-http://127.0.0.1:5000}"
echo "  product type:      ${OPENALGO_PRODUCT_TYPE:-MIS}"
echo "  futures map:       $FUTURES_MAP_PATH"
echo "  config:            $CONFIG_PATH"

cd "$LEAN_LAUNCHER_DIR"
PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
  PYTHONNET_PYDLL="${PYTHONNET_PYDLL:-$(python3-config --prefix)/lib/libpython3.11.dylib}" \
  dotnet "$LEAN_LAUNCHER_DLL" --config "$CONFIG_PATH"
