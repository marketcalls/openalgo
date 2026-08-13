# 05 - Security Architecture

## Trust Boundaries

OpenAlgo is a self-hosted trading application. The application enforces authentication, request validation, rate limits, IP bans, browser protections, and encrypted token persistence. The operator owns host hardening, TLS termination, reverse-proxy trust, firewall policy, secrets, backups, and broker-account controls.

```text
client
  -> TLS/reverse proxy and host firewall
  -> Flask security and IP-ban middleware
  -> session, API-key, webhook, or OAuth authentication
  -> schema/CSRF/rate-limit policy
  -> service and broker/sandbox boundary
  -> isolated local stores
```

The internal ZeroMQ market-data endpoint is unauthenticated and must remain private. The public market-data WebSocket has its own API-key authentication handshake.

## Application Authentication

Application passwords are Argon2-hashed with `API_KEY_PEPPER`. TOTP can be required independently for login, Remote MCP write authorization, and password reset.

Device sessions and the installation-wide broker session are separate:

- at most five active application sessions are retained per user;
- same-user/same-IP login replaces the existing device row;
- session-status polling refreshes `last_seen` no more than once every 30 seconds;
- broker-token expiry preserves a valid app session and reports reconnect state;
- password changes revoke active device sessions.

The default daily session boundary is `03:00` IST. `DISABLE_SESSION_EXPIRY=true` supports deliberately continuous deployments such as crypto, but it expands session lifetime and should be an explicit decision.

## API Keys And Tokens

OpenAlgo generates one current 64-character hexadecimal API key per user. `database/auth_db.py` stores:

- an Argon2 hash for verification;
- an encrypted copy for authenticated UI and integration retrieval;
- hashed cache keys for positive and negative verification caches.

Regeneration invalidates the prior key. The key has no per-operation scopes; public REST operations remain subject to schemas, Analyzer Mode, Action Center policy, services, and rate limits.

Broker auth/feed tokens and other supported token fields use Fernet. The key is derived from `API_KEY_PEPPER` and the per-install `FERNET_SALT`. A legacy static-salt fallback exists only for migration compatibility and must not be documented as the normal installation design.

Static broker application credentials remain in `.env`; masking them in Profile responses does not encrypt that file.

## Browser And REST Policy

- HTTPS deployments use Secure, HTTP-only, SameSite session cookies and the `__Secure-` prefix where configured.
- Session-authenticated state changes use CSRF protection unless a route has a specific callback/webhook exemption.
- `/api/v1` is CSRF-exempt because it uses API-key request authentication.
- CORS, CSP, referrer, permissions, framing, and related response headers are configured centrally.
- Debug mode is rejected on externally bound hosts unless the operator explicitly overrides the guard.

Most REST schemas require `apikey` in the JSON body. Only endpoints that explicitly implement another location should accept a header or query parameter.

## IP Security

`SecurityMiddleware` checks the resolved client IP against `logs.db` before Flask handles the request. `TRUST_PROXY_HEADERS` is false by default; forwarded headers are accepted only when it is enabled. Enabling it without an enforced reverse-proxy boundary permits IP spoofing.

Automatic banning is persisted in application settings and is off by default:

| Setting | Default |
|---|---:|
| 404 threshold in 24 hours | 100 |
| 404 ban duration | 0 hours (permanent) |
| Invalid API-key threshold in 24 hours | 100 |
| Invalid API-key ban duration | 0 hours (permanent) |
| Repeat-offender limit | 2 bans |

Localhost addresses are excluded from automatic bans. There is no general CIDR allowlist in the application middleware. See [23 IP Security](../23-ip-security/).

## Traffic And Audit Boundaries

Traffic logging stores timestamp, client IP, method, path, status, duration, host, optional middleware error, and user ID when available. It does not store request/response bodies, headers, user agents, or a processing timeline.

Order, analyzer, login, MCP, latency, health, and notification events use separate persistence or logging paths. `logs.db` traffic rows are therefore not a complete audit trail of every state change.

## WebSocket And MCP Security

The public market-data proxy requires an API-key authentication message within `WS_AUTH_GRACE_SECONDS`. Per-client queue size, ping interval, timeout, and subscription capacity are bounded by configuration. Private order, position, and margin topics are not fanned out as public market data.

Remote MCP is opt-in. Its OAuth boundary implements exact redirect-URI checks, S256-only PKCE, signed access tokens, refresh-token rotation, and token-family revocation after refresh-token reuse. The sample keeps HTTP off but has approval off and write scope enabled if only the master switch is changed; the Docker enable helper applies approval on and write scope off. Write authorization can require fresh TOTP.

## Data Protection

Five SQLite databases and one DuckDB store isolate operational domains; this is not database-wide encryption. Backups must protect all stores together with `.env`, Fernet material, strategy secrets, and MCP signing keys.

| Store | Security-relevant contents |
|---|---|
| `openalgo.db` | Users, hashes, encrypted tokens/API key copy, settings, sessions, OAuth and application state |
| `logs.db` | Traffic metadata, login/security trackers, IP bans |
| `latency.db` | Timing telemetry |
| `health.db` | Runtime health telemetry |
| `sandbox.db` | Simulated account and order state |
| `historify.duckdb` | Historical market data and Historify metadata |

## Key Files

| File | Responsibility |
|---|---|
| `app.py` | Security initialization, CSRF exemptions, headers, teardown |
| `database/user_db.py` | Password/TOTP user model |
| `database/auth_db.py` | API-key verification, encrypted tokens, sessions |
| `database/traffic_db.py` | Traffic and IP security persistence |
| `database/settings_db.py` | Persisted automatic-ban settings |
| `utils/security_middleware.py` | Pre-Flask ban enforcement |
| `utils/ip_helper.py` | Trusted client-IP resolution |
| `utils/session.py` | Session-expiry guards |
| `blueprints/security.py` | Security dashboard controls |
| `blueprints/mcp_oauth.py` | Remote MCP OAuth boundary |
