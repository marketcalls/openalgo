# Remote MCP PRD

## Purpose

OpenAlgo supports two MCP transports over one tool implementation: local stdio for desktop clients and an optional OAuth-protected HTTP/SSE transport for hosted clients. Remote MCP is self-hosted and disabled by default.

## Transport Contract

| Transport | Entry | Authentication | Default |
|---|---|---|---|
| Local stdio | `mcp/mcpserver.py` | API key and OpenAlgo host supplied to the local process | Available |
| Remote HTTP/SSE | `POST /mcp`, `GET /mcp` | OAuth bearer access token and per-tool scope | Disabled |

The remote dispatcher supports JSON-RPC initialization, tool listing, tool calls, and ping. The SSE endpoint currently provides keepalives and transport compatibility rather than a separate tool implementation.

## Startup Gate

Remote blueprints register only when:

- `MCP_HTTP_ENABLED=True`.
- Flask debug is not enabled using any accepted truthy form.
- `MCP_PUBLIC_URL` is configured as the canonical public origin used for JWT issuer and audience claims.

Startup sets `OPENALGO_MCP_HTTP_BOOT=1` before importing the shared MCP tool module so HTTP boot does not follow the stdio argument path. OAuth tables and a signing key are initialized before route registration. A configuration change through the admin API writes `.env` and requires restart.

## OAuth Surface

| Method | Path | Purpose |
|---|---|---|
| GET | `/.well-known/oauth-authorization-server` | Authorization-server discovery |
| GET | `/.well-known/oauth-protected-resource` and aliases | Protected-resource metadata |
| GET | `/oauth/jwks.json` | Public signing keys |
| POST | `/oauth/register` | Dynamic client registration |
| GET, POST | `/oauth/authorize` | Session-authenticated consent |
| POST | `/oauth/token` | Authorization-code and refresh grants |
| POST | `/oauth/revoke` | Refresh-token revocation |

Authorization-code grants require a registered redirect URI and PKCE verification (S256 only — `plain` is rejected). Consent uses the OpenAlgo app session; write consent can require a fresh TOTP according to the user's security configuration. Refresh tokens rotate and cannot widen the original scope; each token belongs to a family, and reuse of an already-rotated refresh token revokes the entire family.

## Scopes

| Scope | Capability |
|---|---|
| `read:market` | Market data and research tools |
| `read:account` | Orders, trades, positions, holdings, and funds reads |
| `write:orders` | Place, modify, cancel, and close actions |

The dispatcher must reject a tool call when the token lacks the tool's registered scope. `write:orders` is controlled by `MCP_OAUTH_WRITE_SCOPE_ENABLED`; client approval is controlled by `MCP_OAUTH_REQUIRE_APPROVAL`.

Current sample defaults are significant: Remote MCP itself is off, but if enabled the sample has write scope enabled and approval disabled. Operators requiring a stricter posture must set `MCP_OAUTH_WRITE_SCOPE_ENABLED=False` and `MCP_OAUTH_REQUIRE_APPROVAL=True` before exposure.

## Token And Request Controls

- Access tokens are signed JWTs with a default 15-minute TTL and a hard one-hour maximum.
- Refresh tokens have a default 30-day TTL and a hard 31-day maximum; stored values are protected using `API_KEY_PEPPER`-derived hashing.
- Dynamic registration is limited to 10 requests per hour and token/revoke endpoints to 20 per minute.
- Dispatcher rate limiting uses token JTI where available. Per-scope defaults are 60 reads per minute and 50 writes per minute, configurable with `MCP_RATE_LIMIT_READ` and `MCP_RATE_LIMIT_WRITE`.
- CORS is returned only for `MCP_HTTP_CORS_ORIGINS`; the sample permits `https://claude.ai` and `https://chatgpt.com`.
- Every tool call appends a bounded audit entry to `log/mcp.jsonl` with identifiers, tool, scope, parameter hash, duration, outcome, and request IP. Full arguments are not logged.
- Write-scope calls issue a best-effort pre-execution Telegram notification when configured.

## Admin Controls

The session-protected admin API can list, approve, and revoke OAuth clients; read MCP audit entries; read/update settings; and invoke a kill switch.

The current kill switch revokes all refresh tokens. Stateless access JWTs are not blocklisted and remain usable until their short expiry. Documentation and UI must not claim immediate invalidation of already-issued access tokens.

## Data And Security Requirements

- OAuth clients, refresh tokens, and signing-key metadata are stored through `database/oauth_db.py` in the main application database; private key material remains on disk.
- Redirect URI comparison, PKCE, issuer/audience checks, scope checks, CORS, and rate limits must fail closed.
- Secrets, bearer tokens, authorization codes, refresh tokens, and full tool arguments must not enter normal logs or audit output.
- Remote MCP must never start with Flask debug enabled.
- Public deployment requires HTTPS and deliberate review of write scope, client approval, CORS, reverse proxy, and network access controls.

## Ownership And Coverage

| Area | Source |
|---|---|
| Startup and conditional registration | `app.py` |
| HTTP/SSE dispatch, scope enforcement, audit | `blueprints/mcp_http.py` |
| OAuth discovery and grants | `blueprints/mcp_oauth.py` |
| OAuth persistence and revocation | `database/oauth_db.py` |
| Tokens and keys | `utils/oauth_tokens.py`, `utils/oauth_keys.py` |
| Shared tools | `utils/mcp_tool_registry.py`, `mcp/mcpserver.py` |
| Admin controls | `blueprints/admin.py` |

See `docs/design/41-mcp-architecture/README.md` and `docs/bdd/admin_and_security.feature`.
