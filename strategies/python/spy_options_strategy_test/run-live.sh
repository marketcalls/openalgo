#!/usr/bin/env bash
set -euo pipefail

STRATEGY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$STRATEGY_DIR/../../.." && pwd)"

ALGORITHM_TYPE_NAME="SpyOptionsStrategyPlacementTest"
STRATEGY_PATH="strategies/python/spy_options_strategy_test/SpyOptionsStrategyPlacementTest.py"
LOG_DIR="$REPO_ROOT/.tmp/spy-options-strategy-test"

INITIAL_ENV_KEYS="$(mktemp)"
env | sed 's/=.*//' > "$INITIAL_ENV_KEYS"
trap 'rm -f "$INITIAL_ENV_KEYS"' EXIT

was_initially_set() {
  grep -qx "$1" "$INITIAL_ENV_KEYS"
}

load_env_file() {
  local file="$1"
  local override="${2:-false}"
  [[ -f "$file" ]] || return 0

  local line key
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    key="${line%%=*}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    was_initially_set "$key" && continue
    if [[ "$override" == "true" || -z "${!key+x}" ]]; then
      eval "export $line"
    fi
  done < "$file"
}

is_listening() {
  local port="$1"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
}

start_background() {
  local name="$1"
  local port="$2"
  shift 2

  if is_listening "$port"; then
    echo "$name already listening on 127.0.0.1:$port"
    return
  fi

  echo "Starting $name on 127.0.0.1:$port"
  nohup "$@" > "$LOG_DIR/${name}.log" 2>&1 &
  echo $! > "$LOG_DIR/${name}.pid"
  sleep 2
}

load_env_file "$REPO_ROOT/.env" false
load_env_file "$STRATEGY_DIR/.env" true

EXPORTER_PORT="${SPY_OPTIONS_EXPORTER_PORT:-9110}"
PROMETHEUS_PORT="${PROMETHEUS_PORT:-9090}"
GRAFANA_PORT="${GRAFANA_PORT:-${GF_SERVER_HTTP_PORT:-3001}}"
DASHBOARD_URL="http://127.0.0.1:${GRAFANA_PORT}/d/spy-options-strategy-test/spy-options-strategy-test?orgId=1&from=now-1h&to=now&timezone=browser&refresh=5s"

mkdir -p "$LOG_DIR"

if ! command -v prometheus >/dev/null 2>&1 || ! command -v grafana >/dev/null 2>&1; then
  echo "Grafana/Prometheus is not installed. Install first with:"
  echo "  scripts/install-grafana-stack.sh"
  exit 1
fi

start_background \
  "lean-spy-options-exporter" \
  "$EXPORTER_PORT" \
  env EXPORTER_PORT="$EXPORTER_PORT" "$REPO_ROOT/scripts/run-metrics-exporter.sh" "$ALGORITHM_TYPE_NAME"

start_background \
  "prometheus" \
  "$PROMETHEUS_PORT" \
  "$REPO_ROOT/scripts/run-prometheus.sh"

start_background \
  "grafana" \
  "$GRAFANA_PORT" \
  env GF_SERVER_HTTP_PORT="$GRAFANA_PORT" "$REPO_ROOT/scripts/run-grafana.sh"

echo
echo "SPY options strategy dashboard:"
echo "  $DASHBOARD_URL"
echo
echo "Exporter metrics:"
echo "  http://127.0.0.1:${EXPORTER_PORT}/metrics"
echo
echo "Strategy-local configuration:"
echo "  $STRATEGY_DIR/.env"
echo

if command -v open >/dev/null 2>&1; then
  open "$DASHBOARD_URL" >/dev/null 2>&1 || true
fi

export LIVE_CONFIRM="${LIVE_CONFIRM:-true}"
export IB_CLIENT_ID="${IB_CLIENT_ID:-9}"
export IB_TRADING_MODE="${IB_TRADING_MODE:-paper}"
export SPY_OPTIONS_TEST_STRATEGY="${SPY_OPTIONS_TEST_STRATEGY:-iron_butterfly_0dte}"
export SPY_OPTIONS_PLACE_TEST_ORDER="${SPY_OPTIONS_PLACE_TEST_ORDER:-false}"
export SPY_OPTIONS_QUANTITY="${SPY_OPTIONS_QUANTITY:-1}"
export SPY_OPTIONS_WING_WIDTH="${SPY_OPTIONS_WING_WIDTH:-5}"
export SPY_OPTIONS_HOLD_MINUTES="${SPY_OPTIONS_HOLD_MINUTES:-2}"

cd "$REPO_ROOT"
"$REPO_ROOT/scripts/run-live-ib.sh" "$STRATEGY_PATH" "$ALGORITHM_TYPE_NAME"
