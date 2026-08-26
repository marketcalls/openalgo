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

escape_sed_replacement() {
  printf '%s' "$1" | sed -e 's/[\/&|\\]/\\&/g'
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
      "$PYTHON_VENV/lib/libpython3.11.so"
      "$PYTHON_VENV/lib/libpython3.11.so.1.0"
      "$PYTHON_VENV/lib/libpython3.10.so"
      "$LEAN_REPO/.conda/lean-py311/lib/libpython3.11.dylib"
      "$LEAN_REPO/.conda/lean-py311/lib/libpython3.11.so"
      "$LEAN_REPO/.conda/lean-py311/lib/libpython3.11.so.1.0"
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

  # Linux servers may not have Mono installed. Lean targets .NET, so tell
  # pythonnet to load CoreCLR using the launcher's runtime configuration.
  if [[ "$(uname -s)" == "Linux" ]]; then
    export DOTNET_ROOT="${DOTNET_ROOT:-$HOME/.dotnet}"
    export PATH="$DOTNET_ROOT:$PATH"
    export PYTHONNET_RUNTIME="${PYTHONNET_RUNTIME:-coreclr}"
    export PYTHONNET_CORECLR_RUNTIME_CONFIG="${PYTHONNET_CORECLR_RUNTIME_CONFIG:-$LEAN_LAUNCHER_DIR/QuantConnect.Lean.Launcher.runtimeconfig.json}"
  fi
}

generate_config() {
  local template="$1"
  local output="$2"
  local ib_account ib_user_name ib_password ib_host ib_port ib_client_id ib_tws_dir ib_version ib_trading_mode mes_contract_expiry
  local spy_options_test_strategy spy_options_place_test_order spy_options_quantity spy_options_wing_width spy_options_hold_minutes
  local sandwich_place_orders sandwich_force_exit sandwich_min_vix sandwich_max_vix sandwich_min_reward_risk sandwich_wing_width sandwich_max_allocation
  local openalgo_api_key openalgo_host openalgo_ws_url openalgo_strategy_name openalgo_product_type
  local openalgo_place_test_orders openalgo_test_quantity openalgo_hold_minutes openalgo_submit_without_price openalgo_sbin_symbol
  local openalgo_nifty_future_symbol openalgo_fo_expiry openalgo_nifty_spread_enabled openalgo_nifty_long_call_strike
  local openalgo_nifty_short_call_strike openalgo_banknifty_spread_enabled openalgo_banknifty_long_call_strike
  local openalgo_banknifty_short_call_strike openalgo_sensex_spread_enabled openalgo_sensex_long_call_strike
  local openalgo_sensex_short_call_strike
  local nwm_mode nwm_futures_map_path
  local ib_agent_description ib_weekly_restart_utc_time ib_financial_advisors_group_filter ib_use_existing_gateway

  ib_account="$(escape_sed_replacement "${IB_ACCOUNT:-}")"
  ib_user_name="$(escape_sed_replacement "${IB_USER_NAME:-}")"
  ib_password="$(escape_sed_replacement "${IB_PASSWORD:-}")"
  ib_host="$(escape_sed_replacement "${IB_HOST:-127.0.0.1}")"
  ib_port="$(escape_sed_replacement "${IB_PORT:-4002}")"
  ib_client_id="$(escape_sed_replacement "${IB_CLIENT_ID:-0}")"
  ib_tws_dir="$(escape_sed_replacement "${IB_TWS_DIR:-$HOME/Jts}")"
  ib_version="$(escape_sed_replacement "${IB_VERSION:-1034}")"
  ib_trading_mode="$(escape_sed_replacement "${IB_TRADING_MODE:-paper}")"
  mes_contract_expiry="$(escape_sed_replacement "${MES_CONTRACT_EXPIRY:-}")"
  spy_options_test_strategy="$(escape_sed_replacement "${SPY_OPTIONS_TEST_STRATEGY:-}")"
  spy_options_place_test_order="$(escape_sed_replacement "${SPY_OPTIONS_PLACE_TEST_ORDER:-}")"
  spy_options_quantity="$(escape_sed_replacement "${SPY_OPTIONS_QUANTITY:-}")"
  spy_options_wing_width="$(escape_sed_replacement "${SPY_OPTIONS_WING_WIDTH:-}")"
  spy_options_hold_minutes="$(escape_sed_replacement "${SPY_OPTIONS_HOLD_MINUTES:-}")"
  spx_0dte_place_test_order="$(escape_sed_replacement "${SPX_0DTE_PLACE_TEST_ORDER:-false}")"
  sandwich_place_orders="$(escape_sed_replacement "${SPX_SANDWICH_PLACE_ORDERS:-false}")"
  sandwich_force_exit="$(escape_sed_replacement "${SPX_SANDWICH_FORCE_EXIT:-false}")"
  sandwich_min_vix="$(escape_sed_replacement "${SPX_SANDWICH_MIN_VIX:-0}")"
  sandwich_max_vix="$(escape_sed_replacement "${SPX_SANDWICH_MAX_VIX:-24}")"
  sandwich_min_reward_risk="$(escape_sed_replacement "${SPX_SANDWICH_MIN_REWARD_RISK:-1.0}")"
  sandwich_wing_width="$(escape_sed_replacement "${SPX_SANDWICH_WING_WIDTH:-5}")"
  sandwich_max_allocation="$(escape_sed_replacement "${SPX_SANDWICH_MAX_ALLOCATION:-2500}")"
  openalgo_api_key="$(escape_sed_replacement "${OPENALGO_API_KEY:-}")"
  openalgo_host="$(escape_sed_replacement "${OPENALGO_HOST:-http://127.0.0.1:5000}")"
  openalgo_ws_url="$(escape_sed_replacement "${OPENALGO_WS_URL:-ws://127.0.0.1:8443}")"
  openalgo_strategy_name="$(escape_sed_replacement "${OPENALGO_STRATEGY_NAME:-Lean}")"
  openalgo_product_type="$(escape_sed_replacement "${OPENALGO_PRODUCT_TYPE:-MIS}")"
  openalgo_place_test_orders="$(escape_sed_replacement "${OPENALGO_PLACE_TEST_ORDERS:-false}")"
  openalgo_test_quantity="$(escape_sed_replacement "${OPENALGO_TEST_QUANTITY:-1}")"
  openalgo_hold_minutes="$(escape_sed_replacement "${OPENALGO_HOLD_MINUTES:-5}")"
  openalgo_submit_without_price="$(escape_sed_replacement "${OPENALGO_SUBMIT_WITHOUT_PRICE:-true}")"
  openalgo_sbin_symbol="$(escape_sed_replacement "${OPENALGO_SBIN_SYMBOL:-SBIN}")"
  openalgo_nifty_future_symbol="$(escape_sed_replacement "${OPENALGO_NIFTY_FUTURE_SYMBOL:-NIFTY}")"
  openalgo_fo_expiry="$(escape_sed_replacement "${OPENALGO_FO_EXPIRY:-}")"
  openalgo_nifty_spread_enabled="$(escape_sed_replacement "${OPENALGO_NIFTY_SPREAD_ENABLED:-true}")"
  openalgo_nifty_long_call_strike="$(escape_sed_replacement "${OPENALGO_NIFTY_LONG_CALL_STRIKE:-0}")"
  openalgo_nifty_short_call_strike="$(escape_sed_replacement "${OPENALGO_NIFTY_SHORT_CALL_STRIKE:-0}")"
  openalgo_banknifty_spread_enabled="$(escape_sed_replacement "${OPENALGO_BANKNIFTY_SPREAD_ENABLED:-true}")"
  openalgo_banknifty_long_call_strike="$(escape_sed_replacement "${OPENALGO_BANKNIFTY_LONG_CALL_STRIKE:-0}")"
  openalgo_banknifty_short_call_strike="$(escape_sed_replacement "${OPENALGO_BANKNIFTY_SHORT_CALL_STRIKE:-0}")"
  openalgo_sensex_spread_enabled="$(escape_sed_replacement "${OPENALGO_SENSEX_SPREAD_ENABLED:-true}")"
  openalgo_sensex_long_call_strike="$(escape_sed_replacement "${OPENALGO_SENSEX_LONG_CALL_STRIKE:-0}")"
  openalgo_sensex_short_call_strike="$(escape_sed_replacement "${OPENALGO_SENSEX_SHORT_CALL_STRIKE:-0}")"
  nwm_mode="$(escape_sed_replacement "${NWM_MODE:-data-only}")"
  nwm_futures_map_path="$(escape_sed_replacement "${NWM_FUTURES_MAP_PATH:-}")"
  ib_agent_description="$(escape_sed_replacement "${IB_AGENT_DESCRIPTION:-Individual}")"
  ib_weekly_restart_utc_time="$(escape_sed_replacement "${IB_WEEKLY_RESTART_UTC_TIME:-22:00:00}")"
  ib_financial_advisors_group_filter="$(escape_sed_replacement "${IB_FINANCIAL_ADVISORS_GROUP_FILTER:-}")"
  ib_use_existing_gateway="$(escape_sed_replacement "${IB_USE_EXISTING_GATEWAY:-true}")"

  sed \
    -e "s|__ALGORITHM_TYPE__|$ALGORITHM_TYPE_NAME|g" \
    -e "s|__ALGORITHM_LOCATION__|$STRATEGY_PATH|g" \
    -e "s|__MES_CONTRACT_EXPIRY__|$mes_contract_expiry|g" \
    -e "s|__SPY_OPTIONS_TEST_STRATEGY__|$spy_options_test_strategy|g" \
    -e "s|__SPY_OPTIONS_PLACE_TEST_ORDER__|$spy_options_place_test_order|g" \
    -e "s|__SPY_OPTIONS_QUANTITY__|$spy_options_quantity|g" \
    -e "s|__SPY_OPTIONS_WING_WIDTH__|$spy_options_wing_width|g" \
    -e "s|__SPY_OPTIONS_HOLD_MINUTES__|$spy_options_hold_minutes|g" \
    -e "s|__SPX_0DTE_PLACE_TEST_ORDER__|$spx_0dte_place_test_order|g" \
    -e "s|__SANDWICH_PLACE_ORDERS__|$sandwich_place_orders|g" \
    -e "s|__SANDWICH_FORCE_EXIT__|$sandwich_force_exit|g" \
    -e "s|__SANDWICH_MIN_VIX__|$sandwich_min_vix|g" \
    -e "s|__SANDWICH_MAX_VIX__|$sandwich_max_vix|g" \
    -e "s|__SANDWICH_MIN_REWARD_RISK__|$sandwich_min_reward_risk|g" \
    -e "s|__SANDWICH_WING_WIDTH__|$sandwich_wing_width|g" \
    -e "s|__SANDWICH_MAX_ALLOCATION__|$sandwich_max_allocation|g" \
    -e "s|__OPENALGO_API_KEY__|$openalgo_api_key|g" \
    -e "s|__OPENALGO_HOST__|$openalgo_host|g" \
    -e "s|__OPENALGO_WS_URL__|$openalgo_ws_url|g" \
    -e "s|__OPENALGO_STRATEGY_NAME__|$openalgo_strategy_name|g" \
    -e "s|__OPENALGO_PRODUCT_TYPE__|$openalgo_product_type|g" \
    -e "s|__OPENALGO_PLACE_TEST_ORDERS__|$openalgo_place_test_orders|g" \
    -e "s|__OPENALGO_TEST_QUANTITY__|$openalgo_test_quantity|g" \
    -e "s|__OPENALGO_HOLD_MINUTES__|$openalgo_hold_minutes|g" \
    -e "s|__OPENALGO_SUBMIT_WITHOUT_PRICE__|$openalgo_submit_without_price|g" \
    -e "s|__OPENALGO_SBIN_SYMBOL__|$openalgo_sbin_symbol|g" \
    -e "s|__OPENALGO_NIFTY_FUTURE_SYMBOL__|$openalgo_nifty_future_symbol|g" \
    -e "s|__OPENALGO_FO_EXPIRY__|$openalgo_fo_expiry|g" \
    -e "s|__OPENALGO_NIFTY_SPREAD_ENABLED__|$openalgo_nifty_spread_enabled|g" \
    -e "s|__OPENALGO_NIFTY_LONG_CALL_STRIKE__|$openalgo_nifty_long_call_strike|g" \
    -e "s|__OPENALGO_NIFTY_SHORT_CALL_STRIKE__|$openalgo_nifty_short_call_strike|g" \
    -e "s|__OPENALGO_BANKNIFTY_SPREAD_ENABLED__|$openalgo_banknifty_spread_enabled|g" \
    -e "s|__OPENALGO_BANKNIFTY_LONG_CALL_STRIKE__|$openalgo_banknifty_long_call_strike|g" \
    -e "s|__OPENALGO_BANKNIFTY_SHORT_CALL_STRIKE__|$openalgo_banknifty_short_call_strike|g" \
    -e "s|__OPENALGO_SENSEX_SPREAD_ENABLED__|$openalgo_sensex_spread_enabled|g" \
    -e "s|__OPENALGO_SENSEX_LONG_CALL_STRIKE__|$openalgo_sensex_long_call_strike|g" \
    -e "s|__OPENALGO_SENSEX_SHORT_CALL_STRIKE__|$openalgo_sensex_short_call_strike|g" \
    -e "s|__NWM_MODE__|$nwm_mode|g" \
    -e "s|__NWM_FUTURES_MAP_PATH__|$nwm_futures_map_path|g" \
    -e "s|__DATA_FOLDER__|$LEAN_DATA_DIR|g" \
    -e "s|__PYTHON_VENV__|${PYTHON_VENV:-}|g" \
    -e "s|__IB_ACCOUNT__|$ib_account|g" \
    -e "s|__IB_USER_NAME__|$ib_user_name|g" \
    -e "s|__IB_PASSWORD__|$ib_password|g" \
    -e "s|__IB_HOST__|$ib_host|g" \
    -e "s|__IB_PORT__|$ib_port|g" \
    -e "s|__IB_CLIENT_ID__|$ib_client_id|g" \
    -e "s|__IB_TWS_DIR__|$ib_tws_dir|g" \
    -e "s|__IB_VERSION__|$ib_version|g" \
    -e "s|__IB_TRADING_MODE__|$ib_trading_mode|g" \
    -e "s|__IB_AGENT_DESCRIPTION__|$ib_agent_description|g" \
    -e "s|__IB_WEEKLY_RESTART_UTC_TIME__|$ib_weekly_restart_utc_time|g" \
    -e "s|__IB_FINANCIAL_ADVISORS_GROUP_FILTER__|$ib_financial_advisors_group_filter|g" \
    -e "s|__IB_USE_EXISTING_GATEWAY__|$ib_use_existing_gateway|g" \
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
