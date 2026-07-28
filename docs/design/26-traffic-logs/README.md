# 26 - Traffic Logs

## Purpose

OpenAlgo records HTTP request metadata for monitoring, latency review, and security analysis. It does not store request bodies, response bodies, headers, user agents, or a per-request processing timeline in the traffic table.

## Capture Flow

`utils/traffic_logger.py` wraps the Flask WSGI application. For each included request it captures context before submitting a serialized write to a single-worker executor:

| Field | Source |
|---|---|
| `timestamp` | Database default |
| `client_ip` | Trusted client-IP helper |
| `method` | Flask request method |
| `path` | Flask request path |
| `status_code` | WSGI response status |
| `duration_ms` | Middleware wall time |
| `host` | Request host |
| `error` | Unhandled middleware exception, when present |
| `user_id` | `flask.g`, when populated |

Writes go to `logs.db` through `database/traffic_db.py`. The executor has one worker so SQLite commits remain serialized and do not delay the HTTP response. The worker removes its scoped session after every write.

Static assets, the favicon, latency-log reads, and the traffic dashboard's own routes are excluded to avoid noise and recursion.

## Dashboard

The supported React page is `/logs/traffic` (with `/traffic` retained as an alias). It calls session-authenticated routes under `/traffic`:

| Route | Behavior |
|---|---|
| `GET /traffic/api/logs` | Return recent entries; `limit` defaults to 100 and is capped at 1,000 |
| `GET /traffic/api/stats` | Return overall, `/api/v1`-only, and selected endpoint statistics |
| `GET /traffic/export` | Export the current log set as CSV |

The page shows total requests, error requests, average duration, a recent-request table, and per-endpoint totals/errors/average duration. UI filters select all versus `/api/v1` traffic and all, successful, or error status.

The table displays timestamp, method, path, status, duration, client IP, and host. It deliberately does not expose stored request/response payloads because none are collected.

## Retention

`init_traffic_logging()` initializes the store, purges rows beyond the configured retention policy, and then installs the middleware. Retention comes from security settings rather than a documented multi-tier archive scheme.

## Security

- Proxy-derived IP headers are trusted only when `TRUST_PROXY_HEADERS` is enabled for a controlled reverse proxy.
- API keys and tokens are not captured because traffic logging stores metadata only.
- Dashboard, stats, logs, and export routes require a valid application session and have explicit rate limits.
- `logs.db` also contains IP-ban and invalid-attempt security data; it is separate from `openalgo.db`.

## Key Files

| File | Responsibility |
|---|---|
| `utils/traffic_logger.py` | Middleware, exclusions, asynchronous write dispatch |
| `database/traffic_db.py` | Traffic schema, queries, retention, IP/security tables |
| `blueprints/traffic.py` | Logs, stats, CSV export, legacy template route |
| `frontend/src/pages/monitoring/TrafficDashboard.tsx` | Current dashboard |
