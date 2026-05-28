#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

load_env() {
  if [[ -f "$REPO_ROOT/.env" ]]; then
    local line key
    while IFS= read -r line || [[ -n "$line" ]]; do
      [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
      key="${line%%=*}"
      [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
      if [[ -z "${!key+x}" ]]; then
        eval "export $line"
      fi
    done < "$REPO_ROOT/.env"
  fi
}

resolve_lean_paths() {
  local default_lean_repo
  default_lean_repo="$(cd "$REPO_ROOT/../Lean" && pwd 2>/dev/null || true)"

  LEAN_REPO="${LEAN_REPO:-$default_lean_repo}"
  LEAN_LAUNCHER_DIR="${LEAN_LAUNCHER_DIR:-$LEAN_REPO/Launcher/bin/Debug}"
  LEAN_LAUNCHER_DLL="$LEAN_LAUNCHER_DIR/QuantConnect.Lean.Launcher.dll"
  LEAN_DATA_DIR="${LEAN_DATA_DIR:-$LEAN_REPO/Data}"

  if [[ ! -f "$LEAN_LAUNCHER_DLL" ]]; then
    echo "Error: Lean launcher not found at $LEAN_LAUNCHER_DLL"
    echo "Build Lean first: dotnet build /path/to/Lean/QuantConnect.Lean.sln"
    exit 1
  fi

  if [[ ! -d "$LEAN_DATA_DIR" ]]; then
    echo "Error: Lean data folder not found at $LEAN_DATA_DIR"
    exit 1
  fi
}

resolve_strategy() {
  local strategy_input="${1:-}"
  if [[ -z "$strategy_input" ]]; then
    echo "Usage: $0 <strategy.py> [AlgorithmTypeName]"
    exit 1
  fi

  if [[ "$strategy_input" = /* ]]; then
    STRATEGY_PATH="$strategy_input"
  else
    STRATEGY_PATH="$REPO_ROOT/$strategy_input"
  fi

  if [[ ! -f "$STRATEGY_PATH" ]]; then
    echo "Error: strategy file not found: $STRATEGY_PATH"
    exit 1
  fi

  ALGORITHM_TYPE_NAME="${2:-$(basename "$STRATEGY_PATH" .py)}"
}

configure_python_runtime() {
  local default_python_venv
  default_python_venv="$LEAN_REPO/.conda/lean-py311"
  PYTHON_VENV="${PYTHON_VENV:-$default_python_venv}"

  if [[ -d "$PYTHON_VENV" ]]; then
    export PATH="$PYTHON_VENV/bin:$PATH"
  fi

  if [[ -z "${PYTHONNET_PYDLL:-}" ]]; then
    local candidates
    candidates=(
      "$PYTHON_VENV/lib/libpython3.11.dylib"
      "$PYTHON_VENV/lib/libpython3.10.dylib"
      "$LEAN_REPO/.conda/lean-py311/lib/libpython3.11.dylib"
    )

    local candidate
    for candidate in "${candidates[@]}"; do
      if [[ -f "$candidate" ]]; then
        PYTHONNET_PYDLL="$candidate"
        break
      fi
    done
  fi

  if [[ -n "${PYTHONNET_PYDLL:-}" && ! -f "$PYTHONNET_PYDLL" ]]; then
    echo "Error: PYTHONNET_PYDLL points to a missing file: $PYTHONNET_PYDLL"
    exit 1
  fi

  if [[ -n "${PYTHONNET_PYDLL:-}" ]]; then
    export PYTHONNET_PYDLL
  fi
}

generate_config() {
  local template="$1"
  local output="$2"

  sed \
    -e "s|__ALGORITHM_TYPE__|$ALGORITHM_TYPE_NAME|g" \
    -e "s|__ALGORITHM_LOCATION__|$STRATEGY_PATH|g" \
    -e "s|__DATA_FOLDER__|$LEAN_DATA_DIR|g" \
    -e "s|__PYTHON_VENV__|${PYTHON_VENV:-}|g" \
    -e "s|__IB_ACCOUNT__|${IB_ACCOUNT:-}|g" \
    -e "s|__IB_USER_NAME__|${IB_USER_NAME:-}|g" \
    -e "s|__IB_PASSWORD__|${IB_PASSWORD:-}|g" \
    -e "s|__IB_HOST__|${IB_HOST:-127.0.0.1}|g" \
    -e "s|__IB_PORT__|${IB_PORT:-4002}|g" \
    -e "s|__IB_TRADING_MODE__|${IB_TRADING_MODE:-paper}|g" \
    -e "s|__FYERS_API_URL__|${FYERS_API_URL:-https://api-t1.fyers.in/api/v3}|g" \
    -e "s|__FYERS_DATA_API_URL__|${FYERS_DATA_API_URL:-https://api-t1.fyers.in/data}|g" \
    -e "s|__FYERS_MARKET_DATA_SOCKET_URL__|${FYERS_MARKET_DATA_SOCKET_URL:-wss://socket.fyers.in/data}|g" \
    -e "s|__FYERS_ORDER_SOCKET_URL__|${FYERS_ORDER_SOCKET_URL:-wss://socket.fyers.in/order}|g" \
    -e "s|__FYERS_CLIENT_ID__|${FYERS_CLIENT_ID:-}|g" \
    -e "s|__FYERS_SECRET_KEY__|${FYERS_SECRET_KEY:-}|g" \
    -e "s|__FYERS_REDIRECT_URL__|${FYERS_REDIRECT_URL:-https://127.0.0.1}|g" \
    -e "s|__FYERS_BOOTSTRAP_AUTHORIZATION_CODE__|${FYERS_BOOTSTRAP_AUTHORIZATION_CODE:-}|g" \
    -e "s|__FYERS_ACCESS_TOKEN__|${FYERS_ACCESS_TOKEN:-}|g" \
    -e "s|__FYERS_REFRESH_TOKEN__|${FYERS_REFRESH_TOKEN:-}|g" \
    -e "s|__FYERS_AUTH_STATE__|${FYERS_AUTH_STATE:-}|g" \
    -e "s|__FYERS_ACCOUNT_ID__|${FYERS_ACCOUNT_ID:-}|g" \
    -e "s|__FYERS_AUTH_USE_INTEGRATED_BROWSER__|${FYERS_AUTH_USE_INTEGRATED_BROWSER:-true}|g" \
    -e "s|__FYERS_AUTH_ENABLE_HEADLESS_FALLBACK__|${FYERS_AUTH_ENABLE_HEADLESS_FALLBACK:-true}|g" \
    -e "s|__FYERS_AUTH_BOOTSTRAP_ON_CONNECT__|${FYERS_AUTH_BOOTSTRAP_ON_CONNECT:-false}|g" \
    -e "s|__FYERS_AUTH_CALLBACK_HOST__|${FYERS_AUTH_CALLBACK_HOST:-127.0.0.1}|g" \
    -e "s|__FYERS_AUTH_CALLBACK_PORT__|${FYERS_AUTH_CALLBACK_PORT:-5000}|g" \
    -e "s|__FYERS_AUTH_CALLBACK_PATH__|${FYERS_AUTH_CALLBACK_PATH:-/fyers/callback}|g" \
    -e "s|__FYERS_AUTH_CALLBACK_TIMEOUT_SECONDS__|${FYERS_AUTH_CALLBACK_TIMEOUT_SECONDS:-180}|g" \
    -e "s|__FYERS_AUTH_SECURE_STORE_ENABLED__|${FYERS_AUTH_SECURE_STORE_ENABLED:-true}|g" \
    -e "s|__FYERS_AUTH_SECURE_STORE_NAMESPACE__|${FYERS_AUTH_SECURE_STORE_NAMESPACE:-QuantConnect.FyersBrokerage}|g" \
    -e "s|__FYERS_AUTH_SECURE_STORE_ACCOUNT_SCOPE__|${FYERS_AUTH_SECURE_STORE_ACCOUNT_SCOPE:-}|g" \
    -e "s|__FYERS_TEST_SYMBOL__|${FYERS_TEST_SYMBOL:-SBIN}|g" \
    -e "s|__FYERS_PLACE_TEST_ORDER__|${FYERS_PLACE_TEST_ORDER:-false}|g" \
    -e "s|__FYERS_TEST_QUANTITY__|${FYERS_TEST_QUANTITY:-1}|g" \
    -e "s|__FYERS_TEST_HOLD_MINUTES__|${FYERS_TEST_HOLD_MINUTES:-2}|g" \
    "$template" > "$output"
}
