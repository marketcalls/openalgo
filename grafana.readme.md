# Grafana Live Strategy Dashboard

This setup shows live Lean strategy performance in Grafana.

## How the data flows

Lean writes live strategy results to local JSON files in:

```text
/Users/arifkhan/github/Lean/Launcher/bin/Debug
```

For the MES test strategy, the main files are:

```text
/Users/arifkhan/github/Lean/Launcher/bin/Debug/MesSimpleBuySellTestStrategy.json
/Users/arifkhan/github/Lean/Launcher/bin/Debug/MesSimpleBuySellTestStrategy-order-events.json
```

Grafana cannot read those Lean JSON files directly. The local metrics exporter reads them, converts the values into Prometheus metrics, and exposes them at:

```text
http://127.0.0.1:9108/metrics
```

Prometheus scrapes that exporter, and Grafana reads from Prometheus.

## Processes to run

The strategy run is separate from the dashboard stack.

Start the live strategy:

```bash
LIVE_CONFIRM=true IB_TRADING_MODE=paper scripts/run-live-ib.sh strategies/python/MesSimpleBuySellTestStrategy.py MesSimpleBuySellTestStrategy
```

Start the metrics exporter:

```bash
scripts/run-metrics-exporter.sh MesSimpleBuySellTestStrategy
```

Start Prometheus:

```bash
scripts/run-prometheus.sh
```

Start Grafana:

```bash
scripts/run-grafana.sh
```

## Dashboard URL

Open:

```text
http://127.0.0.1:3001/d/mes-live-performance/mes-live-strategy-performance
```

The dashboard refreshes every 5 seconds.

## What lean_exporter.py does

`tools/grafana/lean_exporter.py` is only a metrics bridge.

It:

- Reads Lean's local live result files.
- Extracts equity, holdings, net profit, unrealized P/L, fees, orders, fills, and status.
- Exposes those values in Prometheus format.

It does not:

- Connect to Interactive Brokers.
- Place orders.
- Modify the strategy.
- Start or stop Lean.

If the exporter is not running, Grafana will not receive fresh Lean metrics.

## Local endpoints

Metrics exporter:

```text
http://127.0.0.1:9108/metrics
```

Prometheus:

```text
http://127.0.0.1:9090
```

Grafana:

```text
http://127.0.0.1:3001
```

## Configuration files

Prometheus scrape config:

```text
config/prometheus/prometheus.yml
```

Grafana datasource provisioning:

```text
config/grafana/provisioning/datasources/prometheus.yml
```

Grafana dashboard provisioning:

```text
config/grafana/provisioning/dashboards/dashboards.yml
```

Dashboard JSON:

```text
config/grafana/dashboards/mes-live-performance.json
```

## One-time install

If Grafana and Prometheus are not installed:

```bash
scripts/install-grafana-stack.sh
```
