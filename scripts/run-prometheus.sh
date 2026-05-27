#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PROMETHEUS_BIN="${PROMETHEUS_BIN:-prometheus}"
PROMETHEUS_DATA_DIR="${PROMETHEUS_DATA_DIR:-$REPO_ROOT/.tmp/prometheus}"
PROMETHEUS_CONFIG="${PROMETHEUS_CONFIG:-$REPO_ROOT/config/prometheus/prometheus.yml}"

mkdir -p "$PROMETHEUS_DATA_DIR"

exec "$PROMETHEUS_BIN" \
  --config.file="$PROMETHEUS_CONFIG" \
  --storage.tsdb.path="$PROMETHEUS_DATA_DIR" \
  --web.listen-address="127.0.0.1:9090"
