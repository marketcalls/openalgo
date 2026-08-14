#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

ALGORITHM_TYPE_NAME="Spx0DteOrderFlowProfileSpreadStrategy"
STRATEGY_PATH="strategies/python/spx_0dte_orderflow_profile/Spx0DteOrderFlowProfileSpreadStrategy.py"
EXPORTER_PORT="${SPX_0DTE_EXPORTER_PORT:-9109}"
PROMETHEUS_PORT="${PROMETHEUS_PORT:-9090}"
GRAFANA_PORT="${GF_SERVER_HTTP_PORT:-3001}"
LOG_DIR="$REPO_ROOT/.tmp/spx-0dte-orderflow-profile"
DASHBOARD_URL="http://127.0.0.1:${GRAFANA_PORT}/d/spx-0dte-orderflow-profile/spx-0dte-orderflow-profile?orgId=1&from=now-1h&to=now&timezone=browser&refresh=5s"

mkdir -p "$LOG_DIR"

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

if ! command -v prometheus >/dev/null 2>&1 || ! command -v grafana >/dev/null 2>&1; then
  echo "Grafana/Prometheus is not installed. Install first with:"
  echo "  scripts/install-grafana-stack.sh"
  exit 1
fi

start_background \
  "lean-spx-exporter" \
  "$EXPORTER_PORT" \
  env EXPORTER_PORT="$EXPORTER_PORT" "$REPO_ROOT/scripts/run-metrics-exporter.sh" "$ALGORITHM_TYPE_NAME"

start_background \
  "prometheus" \
  "$PROMETHEUS_PORT" \
  "$REPO_ROOT/scripts/run-prometheus.sh"

start_background \
  "grafana" \
  "$GRAFANA_PORT" \
  "$REPO_ROOT/scripts/run-grafana.sh"

echo
echo "SPX 0DTE dashboard:"
echo "  $DASHBOARD_URL"
echo
echo "Exporter metrics:"
echo "  http://127.0.0.1:${EXPORTER_PORT}/metrics"
echo
echo "Starting live IB paper strategy:"
echo "  $STRATEGY_PATH"
echo

LIVE_CONFIRM="${LIVE_CONFIRM:-true}" \
IB_CLIENT_ID="${IB_CLIENT_ID:-7}" \
IB_TRADING_MODE="${IB_TRADING_MODE:-paper}" \
SPX_0DTE_PLACE_TEST_ORDER="${SPX_0DTE_PLACE_TEST_ORDER:-true}" \
"$REPO_ROOT/scripts/run-live-ib.sh" "$STRATEGY_PATH" "$ALGORITHM_TYPE_NAME"
