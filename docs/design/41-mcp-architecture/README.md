# 41 - MCP Architecture

## Transports

OpenAlgo has two MCP deployment modes:

| Transport | Entry | Registration | Auth |
|---|---|---|---|
| Local stdio | `mcp/mcpserver.py` | Spawned by a desktop/client config | OpenAlgo API key and host passed to local process |
| Remote HTTP/SSE | `blueprints/mcp_http.py` | Opt-in during Flask startup | OAuth 2.1 access token and scopes |

Both modes expose trading and research tools backed by OpenAlgo services/SDK behavior. The Python application currently pins the OpenAlgo SDK at `2.0.2`.

## Local Stdio

The MCP client launches `.venv/bin/python mcp/mcpserver.py <api-key> <host>` (Windows uses the equivalent interpreter path). It communicates over stdio and calls the configured OpenAlgo host. The API key should be scoped to the local self-hosted installation and protected as a secret in client configuration.

`mcp/README.md` contains client path examples and the current tool list.

## Remote Gate

Remote MCP is disabled by default. `app.py` registers the OAuth and MCP blueprints only when all startup requirements pass:

- `MCP_HTTP_ENABLED=True`.
- Flask debug is disabled.
- `MCP_PUBLIC_URL` is configured as the canonical public origin.
- The guarded boot marker is set before importing transport modules.

This conditional surface is included in static route discovery but is absent from a default runtime URL map.

## OAuth Model

`blueprints/mcp_oauth.py` implements discovery, protected-resource metadata, JWKS, dynamic client registration, authorization, token, refresh, and revocation behavior. OAuth data is stored by `database/oauth_db.py` in the main database.

Supported scopes are:

| Scope | Capability |
|---|---|
| `read:market` | Quotes, depth, history, instruments and research data |
| `read:account` | Orders, trades, positions, holdings, funds |
| `write:orders` | Place, modify, cancel, and close trading actions |

`write:orders` is advertised only when `MCP_OAUTH_WRITE_SCOPE_ENABLED=True`. Consent can require a fresh TOTP verification. Dynamic clients can require admin approval through `MCP_OAUTH_REQUIRE_APPROVAL`.

## Remote Request Flow

```text
hosted MCP client
  -> OAuth discovery / registration
  -> local-user consent (and fresh TOTP for write when configured)
  -> authorization-code + PKCE token exchange
  -> bearer token with scopes
  -> /mcp JSON-RPC or SSE transport
  -> scoped tool dispatch
  -> OpenAlgo service/API behavior
```

The public origin anchors issuer/audience behavior. Production exposure requires HTTPS, a restricted CORS allowlist, strong signing keys, and deliberate write/approval settings.

## Admin Controls

The admin surface provides OAuth client review, MCP settings/audit data, and a kill switch. Startup logs explicitly warn when write access is enabled or client approval is disabled.

## Security Invariants

- Do not enable Remote MCP in Flask debug mode.
- Never grant a requested scope that was not advertised and enabled.
- Require redirect URI exactness and PKCE for public clients.
- Keep local app authentication and OAuth client authentication separate.
- Keep order tools behind `write:orders`; read tokens cannot execute trades.
- Treat the self-hosted server and static broker-IP controls as additional deployment boundaries, not substitutes for OAuth checks.

## Key Files

| File | Purpose |
|---|---|
| `mcp/mcpserver.py` | Local stdio server |
| `utils/mcp_tool_registry.py` | Shared tool registration helpers |
| `blueprints/mcp_http.py` | Remote MCP transport/dispatch |
| `blueprints/mcp_oauth.py` | OAuth authorization server |
| `database/oauth_db.py` | Clients, grants/tokens, audit/control state |
| `app.py` | Opt-in startup gate and warnings |
