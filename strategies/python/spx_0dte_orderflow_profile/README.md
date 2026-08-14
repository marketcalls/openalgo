# SPX 0DTE Orderflow Profile Strategy

Run the live paper strategy with its Grafana dashboard:

```bash
scripts/run-live-spx0dte-grafana.sh
```

Dashboard:

```text
http://127.0.0.1:3001/d/spx-0dte-orderflow-profile/spx-0dte-orderflow-profile?orgId=1&from=now-1h&to=now&timezone=browser&refresh=5s
```

Metrics exporter:

```text
http://127.0.0.1:9109/metrics
```

This runner starts the Lean metrics exporter, Prometheus, Grafana, and then the live IB paper strategy. IB credentials still need to be valid in the repo `.env` file before Lean can log in through IBAutomater.
