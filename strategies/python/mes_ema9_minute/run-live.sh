#!/usr/bin/env bash
set -euo pipefail

STRATEGY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$STRATEGY_DIR/../../.." && pwd)"
ALGORITHM_TYPE_NAME="MesEma9MinuteStrategy"
STRATEGY_PATH="$STRATEGY_DIR/${ALGORITHM_TYPE_NAME}.py"
LOG_DIR="$REPO_ROOT/.tmp/mes-ema9-minute"
EXPORTER_PORT="${STRATEGY_EXPORTER_PORT:-9113}"
PROMETHEUS_PORT="${PROMETHEUS_PORT:-9090}"
GRAFANA_PORT="${GRAFANA_PORT:-3001}"
DASHBOARD_URL="http://127.0.0.1:${GRAFANA_PORT}/d/mes-ema9-minute/mes-ema9-minute?orgId=1&from=now-1h&to=now&timezone=browser&refresh=5s"

INITIAL_ENV_KEYS="$(mktemp)"
trap 'rm -f "$INITIAL_ENV_KEYS"' EXIT
env | sed 's/=.*//' > "$INITIAL_ENV_KEYS"
was_initially_exported() { grep -qx "$1" "$INITIAL_ENV_KEYS"; }
load_file() {
  local file="$1" override="${2:-false}" line key
  [[ -f "$file" ]] || return 0
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

mkdir -p "$LOG_DIR"
is_listening() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
start_background() {
  local name="$1" port="$2"; shift 2
  if is_listening "$port"; then echo "$name already listening on 127.0.0.1:$port"; return; fi
  nohup "$@" > "$LOG_DIR/${name}.log" 2>&1 & echo $! > "$LOG_DIR/${name}.pid"; sleep 2
}

if command -v prometheus >/dev/null 2>&1 && command -v grafana >/dev/null 2>&1; then
  start_background "lean-mes-ema9-exporter" "$EXPORTER_PORT" env EXPORTER_PORT="$EXPORTER_PORT" SYMBOL_PREFIX="MES" "$REPO_ROOT/scripts/run-metrics-exporter.sh" "$ALGORITHM_TYPE_NAME"
  start_background "prometheus" "$PROMETHEUS_PORT" "$REPO_ROOT/scripts/run-prometheus.sh"
  start_background "grafana" "$GRAFANA_PORT" "$REPO_ROOT/scripts/run-grafana.sh"
fi
echo "Grafana dashboard: $DASHBOARD_URL"
cd "$REPO_ROOT"
"$REPO_ROOT/scripts/run-live-ib.sh" "$STRATEGY_PATH" "$ALGORITHM_TYPE_NAME"
