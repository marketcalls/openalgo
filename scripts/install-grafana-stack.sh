#!/usr/bin/env bash
set -euo pipefail

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required to install Grafana and Prometheus on this machine."
  exit 1
fi

if ! command -v prometheus >/dev/null 2>&1; then
  brew install prometheus
fi

if ! command -v grafana >/dev/null 2>&1; then
  brew install grafana
fi

echo "Grafana and Prometheus are installed."
echo "Start the stack with:"
echo "  scripts/run-metrics-exporter.sh"
echo "  scripts/run-prometheus.sh"
echo "  scripts/run-grafana.sh"
