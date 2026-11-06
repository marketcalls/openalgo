# Health monitoring: operations and implementation

Current reference checked against `blueprints/health.py`,
`utils/health_monitor.py`, `database/health_db.py` and `app.py` on 2026-11-06.
Health monitoring is already registered and started by the application. No
additional blueprint registration or dashboard template is needed.

## Dashboard and probes

Open `/health` after signing in for the React dashboard. Use `/health/status`
for an unauthenticated JSON probe. `/health` serves the application HTML; a 200
there does not establish that the metrics are healthy.

| Endpoint | Authentication | Purpose |
|---|---|---|
| `GET /health/status` | None | Cached overall health |
| `GET /health/check` | None | Cached health plus database connectivity checks |
| `GET /health` | Signed-in UI | React dashboard |
| `GET /health/api/current` | Browser session | Current metrics, thread and process details |
| `GET /health/api/history?hours=24` | Browser session | Historical samples |
| `GET /health/api/stats?hours=24` | Browser session | Aggregated statistics |
| `GET /health/api/alerts` | Browser session | Active alerts |
| `POST /health/api/alerts/<id>/acknowledge` | Browser session and CSRF | Acknowledge an alert |
| `POST /health/api/alerts/<id>/resolve` | Browser session and CSRF | Resolve an alert |
| `GET /health/export?hours=24` | Browser session | CSV export |

History, statistics and export clamp `hours` to 1–168, defaulting to 24. The
probe limit is 300 requests/minute for `/health/status` and 60/minute for
`/health/check`. Both probes return 200 for `pass` or `warn` and 503 for `fail`.
A healthy cached sample does not prove that a broker is connected or an order
can be placed.

```bash
curl --fail http://127.0.0.1:5000/health/status
curl --fail http://127.0.0.1:5000/health/check
```

Example status response:

```json
{
  "status": "pass",
  "version": "1.0",
  "serviceId": "openalgo",
  "description": "OpenAlgo Trading Platform"
}
```

Use `/health/status` as the path when configuring a load balancer or a
container probe. It reports resource health, so a memory or descriptor threshold
breach can produce 503 even while the HTTP process is running. Choose any
restart policy with that behavior in mind. `/health/check` additionally opens
database connections and is more suitable for a readiness check.

Authenticated endpoints use the OpenAlgo browser session, not HTTP Basic
Authentication or an OpenAlgo API key. Use the dashboard for manual inspection;
scripted access must supply a valid session and CSRF token for writes.

## Collection and storage

`app.py` registers `health_bp` and calls `init_health_monitoring(app)` during
startup. `HealthCollector` samples descriptors/handles, memory, database
connections, WebSocket connections and threads outside the HTTP request path.
`HealthMetric` and `HealthAlert` persist to the separate health database
(`HEALTH_DATABASE_URL`, normally `db/health.db`). The initialization purges old
metrics using the configured retention period. Alerts are created on threshold
breaches and can resolve automatically when the metric returns below its
warning threshold.

Collection reduces request-path work; it is not a guarantee of zero CPU,
latency or database overhead. Timing and capacity depend on the host and load.

Production runs one Gunicorn worker with eventlet by default or the optional
64-thread gthread worker. The dev server uses normal threading. Thread counts
and descriptor metrics must be interpreted for the active runtime and OS. See
[the worker guide](gthread/README.md) for diagnostics and switching.

## Configuration

Restart OpenAlgo after changing these environment values.

| Setting | Default when absent |
|---|---|
| `HEALTH_MONITOR_ENABLED` | `true` |
| `HEALTH_SAMPLE_INTERVAL` | `10` seconds |
| `HEALTH_RETENTION_DAYS` | `7` |
| `HEALTH_FD_WARNING_THRESHOLD` / `HEALTH_FD_CRITICAL_THRESHOLD` | `700` / `900` on POSIX; `5000` / `10000` on Windows |
| `HEALTH_MEMORY_WARNING_THRESHOLD` / `HEALTH_MEMORY_CRITICAL_THRESHOLD` | `500` / `1000` MB in code |
| `HEALTH_DB_WARNING_THRESHOLD` / `HEALTH_DB_CRITICAL_THRESHOLD` | `10` / `20` |
| `HEALTH_WS_WARNING_THRESHOLD` / `HEALTH_WS_CRITICAL_THRESHOLD` | `10` / `20` |
| `HEALTH_THREAD_WARNING_THRESHOLD` / `HEALTH_THREAD_CRITICAL_THRESHOLD` | `50` / `100` outside gthread; `144` / `224` with the standard 64-thread gthread pool |

The shipped `.sample.env` sets memory thresholds to **3000 / 5000 MB** for a
typical desktop/VPS with Historify. Those explicit values override the lower
code defaults. Existing installations may keep different values. Explicit thread
thresholds also override gthread's pool-adjusted defaults. Outside gthread,
`eventbus-critical` and `openalgo-hub-worker` threads are excluded from the
threshold count, since they were introduced after the baseline thresholds.

Avoid copying a full environment block merely to change one threshold: preserve
the instance's existing secrets and settings.

## Verification and troubleshooting

1. Open `/health` and confirm samples change while auto-refresh is enabled.
2. Check `/health/status` and `/health/check` independently of the dashboard.
3. Review thread and process details before treating a higher count as a leak.
   A configured gthread pool differs from a development process.
4. If collection stops, inspect `log/errors.jsonl` and confirm
   `HEALTH_MONITOR_ENABLED` and the database path are correct.
5. A failed memory check may mean a threshold below the normal workload; compare
   the actual process memory, Historify activity and the instance's settings.

The React dashboard and its chart implementation are documented in
[HEALTH_MONITOR_REACT_FRONTEND.md](HEALTH_MONITOR_REACT_FRONTEND.md).
