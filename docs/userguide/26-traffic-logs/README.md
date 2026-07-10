# 26 - Traffic Logs

## Overview

OpenAlgo records HTTP request metadata for monitoring, latency review, and security analysis. It does **not** store request bodies, response bodies, headers, user agents, or a processing timeline in the traffic table.

Open **Logs > Traffic** or visit `/logs/traffic` after signing in.

## What the Dashboard Shows

| Field | Meaning |
|---|---|
| Timestamp | Time recorded for the request |
| Method | HTTP method such as GET or POST |
| Path | Requested application path |
| Status | HTTP response status code |
| Duration | Middleware wall time in milliseconds |
| Client IP | Address resolved by the trusted client-IP helper |
| Host | Request host |
| Error | Unhandled middleware exception, when present |

Summary panels show total requests, error requests, and average duration. Endpoint statistics include request totals, errors, and average duration for selected `/api/v1` endpoints. Filters can limit the view to all traffic or REST API traffic and to all, successful, or error responses.

Static assets, the favicon, latency-log reads, and the traffic dashboard's own routes are excluded to avoid noise and recursion.

## Export

Use **Export CSV** on the dashboard. The authenticated `GET /traffic/export` route exports the stored metadata fields; it cannot include request or response payloads because those values are never captured.

## Retention

Traffic rows are stored in `db/logs.db`. `TRAFFIC_LOG_RETENTION_DAYS` controls the retention window and defaults to 30 days in `.sample.env`. Expired rows are purged when traffic logging initializes.

## Security Notes

- API keys and broker tokens are not captured by traffic logging.
- Dashboard, data, statistics, and export routes require an application session.
- `TRUST_PROXY_HEADERS` is off by default. Enable it only when a controlled reverse proxy is the only route to OpenAlgo; otherwise forwarded IP headers can be spoofed.
- `logs.db` also contains IP-ban and invalid-attempt tracking, but that state is managed from the Security dashboard.

## Supporting Routes

| Route | Purpose |
|---|---|
| `GET /traffic/api/logs` | Return recent traffic rows; limit is capped at 1,000 |
| `GET /traffic/api/stats` | Return overall, API-only, and selected endpoint statistics |
| `GET /traffic/export` | Download the current stored rows as CSV |

---

**Previous**: [25 - Latency Monitor](../25-latency-monitor/README.md)

**Next**: [27 - Security Settings](../27-security-settings/README.md)
