# 23 - IP Security

## Request Boundary

`SecurityMiddleware` checks the resolved client IP against `logs.db` before Flask handles the request. An active ban returns plain-text HTTP 403 and removes the scoped logs session on both blocked and allowed paths.

Client-IP resolution is deliberately gated by `TRUST_PROXY_HEADERS`:

- Default `FALSE`: use only the immediate peer (`REMOTE_ADDR` / `request.remote_addr`).
- `TRUE`: accept `CF-Connecting-IP`, `True-Client-IP`, `X-Real-IP`, the first `X-Forwarded-For` value, then `X-Client-IP`.

Enable forwarded headers only when a controlled reverse proxy is the sole route to Gunicorn/Flask. Otherwise a direct client can spoof those headers and evade per-IP controls.

## Stored Security State

`database/traffic_db.py` stores three IP-related domains in `logs.db`:

| Table | Purpose |
|---|---|
| `ip_bans` | Active temporary or permanent bans, reason, count, creator |
| `error_404_tracker` | Per-IP 404 count and up to 50 distinct attempted paths in a 24-hour window |
| `invalid_api_key_tracker` | Per-IP invalid-key count and up to 20 key hashes in a 24-hour window |

Raw API keys are not stored by the invalid-key tracker.

Ban lookups use a short TTL cache. Manual ban/unban and automatic changes invalidate the affected cache entry.

## Automatic Bans

Automatic bans are controlled by the persisted Security settings, not environment variables. Current defaults are:

| Setting | Default |
|---|---:|
| Automatic banning | Off |
| 404 threshold in 24 hours | 100 |
| 404 ban duration | 0 hours (permanent) |
| Invalid API-key threshold in 24 hours | 100 |
| Invalid API-key ban duration | 0 hours (permanent) |
| Repeat-offender limit | 2 bans |

The authenticated Security dashboard can change thresholds from 1 to 10,000, durations from 0 to 8,760 hours, and repeat limit from 1 to 10. A duration of zero means permanent.

When automatic banning is enabled and a tracker reaches its threshold, localhost addresses are never banned. The tracker resets after its 24-hour window. Existing ban records increment `ban_count`; reaching the configured repeat limit makes the ban permanent. Durations are not automatically doubled.

## Dashboard And Routes

The React Security page is `/logs/security`. Session-authenticated routes are registered under `/security`:

| Route | Purpose |
|---|---|
| `POST /security/ban` | Ban one validated IPv4/IPv6 address |
| `POST /security/unban` | Remove one ban |
| `POST /security/ban-host` | Resolve recent traffic for a validated host and ban matching IPs |
| `POST /security/clear-404` | Clear one 404 tracker |
| `GET /security/api/data` | Read ban/tracker/settings data |
| `GET /security/stats` | Read security totals |
| `POST /security/settings` | Update automatic-ban settings |
| `GET /security/api/login-activity` | Read login audit data |
| `POST /security/api/login-activity/clear` | Clear login audit data |
| `GET /security/api/active-sessions` | Read active application sessions |

There is no CIDR whitelist feature in the current middleware. Rate limiting and IP bans are separate controls.

## Key Files

| File | Responsibility |
|---|---|
| `utils/security_middleware.py` | Pre-Flask ban enforcement |
| `utils/ip_helper.py` | Trusted client-IP resolution |
| `database/traffic_db.py` | Ban and attempt persistence |
| `database/settings_db.py` | Persisted thresholds and defaults |
| `blueprints/security.py` | Authenticated controls and data routes |
| `frontend/src/pages/monitoring/SecurityDashboard.tsx` | Current dashboard |
