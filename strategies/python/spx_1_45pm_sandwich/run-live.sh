#!/usr/bin/env bash
set -euo pipefail

STRATEGY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$STRATEGY_DIR/../../.." && pwd)"
ALGORITHM_TYPE_NAME="Spx1_45PmSandwichStrategy"
STRATEGY_PATH="$STRATEGY_DIR/${ALGORITHM_TYPE_NAME}.py"
LOG_DIR="$REPO_ROOT/.tmp/spx-1-45pm-sandwich"
EXPORTER_PORT="${SPX_SANDWICH_EXPORTER_PORT:-9112}"
PROMETHEUS_PORT="${PROMETHEUS_PORT:-9090}"
GRAFANA_PORT="${GRAFANA_PORT:-3001}"
DASHBOARD_URL="http://127.0.0.1:${GRAFANA_PORT}/d/spx-1-45pm-sandwich/spx-1-45pm-sandwich?orgId=1&from=now-1h&to=now&timezone=browser&refresh=5s"

INITIAL_ENV_KEYS="$(mktemp)"
trap 'rm -f "$INITIAL_ENV_KEYS"' EXIT
env | sed 's/=.*//' > "$INITIAL_ENV_KEYS"

was_initially_exported() { grep -qx "$1" "$INITIAL_ENV_KEYS"; }

load_file() {
  local file="$1"
  local override="${2:-false}"
  [[ -f "$file" ]] || return 0
  local line key
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    key="${line%%=*}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    was_initially_exported "$key" && continue
    [[ "$override" != "true" && -n "${!key+x}" ]] && continue
    eval "export $line"
  done < "$file"
}

load_file "$REPO_ROOT/.env" false
load_file "$STRATEGY_DIR/.env" true

if [[ "${IB_TRADING_MODE:-paper}" == "paper" ]]; then
  DEFAULT_PLACE_ORDERS=true
else
  DEFAULT_PLACE_ORDERS=false
fi
export SPX_SANDWICH_PLACE_ORDERS="${SPX_SANDWICH_PLACE_ORDERS:-$DEFAULT_PLACE_ORDERS}"
export SPX_SANDWICH_FORCE_EXIT="${SPX_SANDWICH_FORCE_EXIT:-false}"
export SPX_SANDWICH_MIN_VIX="${SPX_SANDWICH_MIN_VIX:-0}"
export SPX_SANDWICH_MAX_VIX="${SPX_SANDWICH_MAX_VIX:-24}"
export SPX_SANDWICH_MIN_REWARD_RISK="${SPX_SANDWICH_MIN_REWARD_RISK:-1.0}"
export SPX_SANDWICH_WING_WIDTH="${SPX_SANDWICH_WING_WIDTH:-5}"
export SPX_SANDWICH_MAX_ALLOCATION="${SPX_SANDWICH_MAX_ALLOCATION:-2500}"

mkdir -p "$LOG_DIR"

is_listening() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

start_background() {
  local name="$1" port="$2"
  shift 2
  if is_listening "$port"; then
    echo "$name already listening on 127.0.0.1:$port"
    return
  fi
  nohup "$@" > "$LOG_DIR/${name}.log" 2>&1 &
  echo $! > "$LOG_DIR/${name}.pid"
  sleep 2
}

if command -v prometheus >/dev/null 2>&1 && command -v grafana >/dev/null 2>&1; then
  start_background "lean-sandwich-exporter" "$EXPORTER_PORT" \
    env EXPORTER_PORT="$EXPORTER_PORT" "$REPO_ROOT/scripts/run-metrics-exporter.sh" "$ALGORITHM_TYPE_NAME"
  start_background "prometheus" "$PROMETHEUS_PORT" "$REPO_ROOT/scripts/run-prometheus.sh"
  start_background "grafana" "$GRAFANA_PORT" "$REPO_ROOT/scripts/run-grafana.sh"
  echo "Grafana dashboard: $DASHBOARD_URL"
else
  echo "Grafana/Prometheus not installed; continuing with LEAN only."
fi

echo "Running $ALGORITHM_TYPE_NAME in ${IB_TRADING_MODE:-paper} mode"
echo "  strategy: $STRATEGY_PATH"
echo "  place orders: $SPX_SANDWICH_PLACE_ORDERS"

cd "$REPO_ROOT"
"$REPO_ROOT/scripts/run-live-ib.sh" "$STRATEGY_PATH" "$ALGORITHM_TYPE_NAME"
