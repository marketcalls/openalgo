#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

load_env
resolve_lean_paths
configure_python_runtime
resolve_strategy "${1:-}" "${2:-}"

is_ib_gateway_listening() {
  local host="${IB_HOST:-127.0.0.1}"
  local port="${IB_PORT:-4002}"

  if [[ "$host" != "127.0.0.1" && "$host" != "localhost" && "$host" != "::1" ]]; then
    return 1
  fi

  lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
}

if [[ -z "${IB_ACCOUNT:-}" ]]; then
  echo "Error: IB_ACCOUNT is required for live runs. Set it in .env"
  exit 1
fi

if [[ "$IB_ACCOUNT" == "U1234567" || "$IB_ACCOUNT" == "DU1234567" ]]; then
  echo "Error: IB_ACCOUNT still has a placeholder value: $IB_ACCOUNT"
  echo "Set IB_ACCOUNT to your actual IB account id, usually U... or DU... for paper."
  exit 1
fi

IB_GATEWAY_ALREADY_RUNNING=false
if is_ib_gateway_listening; then
  IB_GATEWAY_ALREADY_RUNNING=true
  export IB_USE_EXISTING_GATEWAY=true
  echo "Detected IB Gateway/TWS already listening on ${IB_HOST:-127.0.0.1}:${IB_PORT:-4002}; using existing gateway for this run."
else
  export IB_USE_EXISTING_GATEWAY=false
  echo "No IB Gateway detected on ${IB_HOST:-127.0.0.1}:${IB_PORT:-4002}; IBAutomater will start it."
  if [[ "$(uname -s)" == "Darwin" && -x "$REPO_ROOT/scripts/install-macos-ibautomater.sh" ]]; then
    "$REPO_ROOT/scripts/install-macos-ibautomater.sh"
  fi
fi

if [[ "${IB_USE_EXISTING_GATEWAY:-true}" == "false" ]]; then
  if [[ -z "${IB_USER_NAME:-}" || -z "${IB_PASSWORD:-}" ]]; then
    echo "Error: IB_USER_NAME and IB_PASSWORD are required when IB_USE_EXISTING_GATEWAY=false."
    echo "IBAutomater needs credentials to launch and log in to IB Gateway/TWS."
    exit 1
  fi

  if [[ "$IB_USER_NAME" =~ ^(U|DU)[0-9]+$ ]]; then
    echo "Error: IB_USER_NAME looks like an IB account id, not a login username: $IB_USER_NAME"
    echo "Use your actual IBKR login username for IB_USER_NAME. Keep the U.../DU... value in IB_ACCOUNT."
    exit 1
  fi

  if [[ ! -d "${IB_TWS_DIR:-$HOME/Jts}" ]]; then
    echo "Error: IB_TWS_DIR does not exist: ${IB_TWS_DIR:-$HOME/Jts}"
    echo "Install IB Gateway locally or set IB_TWS_DIR to the IB Gateway/TWS installation folder."
    exit 1
  fi
fi

if [[ "${LIVE_CONFIRM:-}" != "true" ]]; then
  echo "Safety check: set LIVE_CONFIRM=true to run live mode"
  echo "Example: LIVE_CONFIRM=true scripts/run-live-ib.sh strategies/python/YourAlgo.py YourAlgo"
  exit 1
fi

if [[ "${IB_TRADING_MODE:-paper}" == "live" && "${LIVE_CONFIRM_REAL:-}" != "true" ]]; then
  echo "Safety check: IB_TRADING_MODE=live can place real orders."
  echo "For paper testing, run with IB_TRADING_MODE=paper."
  echo "For real trading, also set LIVE_CONFIRM_REAL=true."
  exit 1
fi

mkdir -p "$REPO_ROOT/.tmp"
CONFIG_PATH="$REPO_ROOT/.tmp/live-ib-${ALGORITHM_TYPE_NAME}.config.json"
TEMPLATE_PATH="$REPO_ROOT/config/templates/live-interactive.template.json"

if pgrep -f -- "$CONFIG_PATH" >/dev/null 2>&1; then
  echo "Error: $ALGORITHM_TYPE_NAME is already running. Stop the existing LEAN process with Ctrl+C before starting another copy." >&2
  exit 1
fi

generate_config "$TEMPLATE_PATH" "$CONFIG_PATH"

echo "Running live-interactive against IB"
echo "  strategy: $STRATEGY_PATH"
echo "  class:    $ALGORITHM_TYPE_NAME"
echo "  account:  $IB_ACCOUNT"
echo "  host:     ${IB_HOST:-127.0.0.1}:${IB_PORT:-4002}"
echo "  client:   ${IB_CLIENT_ID:-0}"
echo "  mode:     ${IB_TRADING_MODE:-paper}"
echo "  automater: $([[ "${IB_USE_EXISTING_GATEWAY:-true}" == "false" ]] && echo enabled || echo disabled)"
echo "  gateway:  $([[ "$IB_GATEWAY_ALREADY_RUNNING" == "true" ]] && echo existing || echo not-detected)"
if [[ "${IB_USE_EXISTING_GATEWAY:-true}" == "false" ]]; then
  echo "  ib dir:   ${IB_TWS_DIR:-$HOME/Jts}"
  echo "  version:  ${IB_VERSION:-1034}"
fi
echo "  pyvenv:   ${PYTHON_VENV:-<not-set>}"
echo "  pydll:    ${PYTHONNET_PYDLL:-<not-set>}"
echo "  config:   $CONFIG_PATH"

cd "$LEAN_LAUNCHER_DIR"
dotnet "$LEAN_LAUNCHER_DLL" --config "$CONFIG_PATH"
