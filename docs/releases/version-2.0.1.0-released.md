# Version 2.0.1.0 Released

**Date: 3rd May 2026**

**Major Feature Release: Remote MCP — Self-Hosted OAuth 2.1 + MCP HTTP/SSE Server for ChatGPT, Claude.ai, and Claude Mobile, Plus Per-Purpose 2FA Enforcement, Symbol Search Expansion, Admin Diagnostics, and Zerodha NCO/GLOBAL_INDEX Support**

This is the biggest release in the 2.0.x line, covering **20+ commits** since v2.0.0.9. The headline change is **Remote MCP** — a self-hosted OAuth 2.1 + Model Context Protocol HTTP/SSE transport that lets hosted AI clients (ChatGPT.com, Claude.ai, Claude iOS / Android) connect to your OpenAlgo install over HTTPS with the same 40 tools the local stdio MCP already exposes. The local stdio MCP (Claude Desktop, Cursor, Windsurf) is **untouched** — Remote MCP is a parallel, opt-in transport, off by default, that ships behind two enabler scripts (one for native Ubuntu, one for Docker) and a full admin operations console at `/admin/remote-mcp`. Alongside Remote MCP, this release lands per-purpose TOTP enforcement (login / MCP / password reset), a multi-exchange Symbol Search expansion (issue #1326), an admin Diagnostics page with downloadable system reports, and Zerodha NCO + GLOBAL_INDEX exchange support.

***

**Highlights**

* **Remote MCP — Hosted AI Clients via OAuth** — Brand-new `/mcp` HTTP/SSE transport with full OAuth 2.1 + PKCE, Dynamic Client Registration (DCR), JWKS-published RS256 JWTs, refresh-token rotation with reuse-detection family revocation, and per-token-per-scope rate limits. ChatGPT-compatible discovery (`/.well-known/oauth-authorization-server`, `/.well-known/oauth-protected-resource`), claude.ai-compatible scope flow. Off by default; turned on by `install/enable-remote-mcp.sh` (native) or `install/enable-remote-mcp-docker.sh` (Docker).
* **Per-purpose 2FA enforcement** — TOTP can now be required independently for **dashboard login**, **MCP authorization (`write:orders` consent)**, and **password reset** — set the master switch in Profile → TOTP, then pick which purposes apply. Saving requires a fresh TOTP code in the same request to prove authenticator access for both enabling and disabling.
* **Admin → Remote MCP operations console** — Approve / revoke DCR clients, browse the full MCP tool-call audit log (`log/mcp.jsonl`) by tool / scope / outcome, and a one-click **Kill switch** that atomically revokes every refresh token across every approved client.
* **Symbol Search rewrite (#1326)** — Multi-exchange + multi-instrumenttype filtering, CSV download, AmiBroker / TradingView / Python / Excel copy formats, lifted the 500-row hard cap, exchange-only browse mode, and per-user search history.
* **Admin Diagnostics page** — `/admin/diagnostics` shows live system info (Python / Flask versions, DB sizes, broker session state), a paginated error browser over `log/errors.jsonl`, and a one-click downloadable diagnostic bundle (env-redacted) for support tickets.
* **Zerodha NCO + GLOBAL_INDEX exchanges** — NCO (NSE Commodities) and GLOBAL_INDEX (US30 / JAPAN225 / HANGSENG, plus GIFTNIFTY from NSE IFSC) now route correctly through the master contract download and quote endpoints. Quote-only on GLOBAL_INDEX (no orders by exchange convention).
* **"Virtual / Paper" → "Sandbox" rename** — All in-product copy, docs, and SDK examples now uniformly say *Sandbox* (the database, blueprint, and API endpoint names were already `sandbox` — only display strings were inconsistent).
* **Platform version bump** — `2.0.0.9` → `2.0.1.0`. `.sample.env` `ENV_CONFIG_VERSION` `1.0.6` → `1.0.7`. SDK pin (`openalgo==1.0.49`) unchanged.

***

**Remote MCP — feature deep dive**

Remote MCP brings the OpenAlgo MCP toolset to **hosted AI clients** over the public internet. Same 40 tools as the local stdio integration, exposed at `https://yourdomain.com/mcp` with full OAuth 2.1.

**Architecture in one sentence:** the hosted client (ChatGPT / Claude.ai) only ever holds an OAuth Bearer JWT signed by your server's RS256 keypair; tool dispatch on the server side reuses your existing `/api/v1/*` API key (looked up server-side at boot) over loopback. The hosted client never sees your API key or your broker tokens.

**OAuth foundation (Phase 2a + 2c + 2d)** — `e86cf450f`, `0f4f71f0`-derived family, `cb9350f27`:

* RS256 keypair generated and rotated via `utils/oauth_keys.py`; public set published at `/oauth/jwks.json`
* Dynamic Client Registration at `/oauth/register` (RFC 7591) — clients land in a *pending* bucket, gated behind admin approval (default `MCP_OAUTH_REQUIRE_APPROVAL=True`)
* Authorization Code + PKCE-S256 only — `plain` is not advertised; `alg=none` and `alg=HS256` JWTs are rejected by the verifier
* Refresh-token rotation with **family revocation** (RFC 6749 §10.4): single-use, atomic `UPDATE ... WHERE revoked_at IS NULL`, replay of a revoked token revokes the entire family
* `/oauth/revoke` for explicit token retirement, `/oauth/token` for code-exchange and refresh
* Argon2 hashing with `API_KEY_PEPPER` for client_secret + refresh-token storage in `database/oauth_db.py`

**Per-purpose 2FA (Phase 2b + Phase 2 UI)** — `dbc595e88`, `ff44adf46`:

* Four new boolean columns on `users`: `totp_enabled` + `totp_required_for_login` + `totp_required_for_mcp` + `totp_required_for_password_reset`
* `is_totp_required_for(purpose)` helper centralizes the gating decision
* Login flow: POST `/auth/login` → on TOTP requirement, returns `totp_required` flag + temp ticket → POST `/auth/login/totp` with code
* Configure flow at `/auth/2fa/configure` requires a fresh TOTP in the same request (proves authenticator access for *both* enabling and disabling — closes the "stolen session can disable 2FA" hole)
* React UI: `TwoFactorEnforcement.tsx` profile-page toggle, `Login.tsx` TOTP step, `ResetPassword.tsx` TOTP path

**HTTP transport (Phase 3)** — `7d805af15`:

* JSON-RPC 2.0 dispatcher at `/mcp` (POST) + Server-Sent Events transport for streaming
* Per-token-per-scope sliding-window rate limits (`MCP_RATE_LIMIT_READ` / `MCP_RATE_LIMIT_WRITE`)
* CORS allowlist (default: `https://claude.ai,https://chatgpt.com`) with `WWW-Authenticate` exposed via `Access-Control-Expose-Headers` so browsers can read the realm hint on 401
* Audit log writes to `log/mcp.jsonl` — every tool call with timestamp, JTI, scope, outcome, latency, `params_hash` (raw params are deliberately *not* logged)
* Tool registry (`utils/mcp_tool_registry.py`) maps all 40 tools to scopes (`read:market` / `read:account` / `write:orders`) and exposes FastMCP-generated JSON schemas in the `tools/list` response
* Pre-flight refusal: server refuses to boot with `MCP_HTTP_ENABLED=True` and `FLASK_DEBUG=True` together (debug tracebacks would leak bearer tokens)

**Install integration (Phase 4)** — `b36637b5e`, `90897a550`:

* `install/enable-remote-mcp.sh` — native Ubuntu enabler. Detects all `openalgo-*` systemd services, refuses if `FLASK_DEBUG=True`, backs up `.env`, sets the four MCP keys, runs `upgrade/migrate_all.py`, restarts the service, and probes the discovery / JWKS / `/mcp/healthz` endpoints to confirm boot.
* `install/enable-remote-mcp-docker.sh` — Docker enabler. Walks `/opt/openalgo/*/docker-compose.yaml`, picks a stack, backs up the bind-mounted `.env`, updates keys, restarts the container (whose `start.sh` runs migrations automatically), and runs the same smoke probe.
* `install/Remote-MCP-readme.md` — operator-focused install guide with same-domain Mode 1 (automated) and subdomain Mode 2 (manual nginx + certbot recipe), threat model, and disabling instructions.
* New `docs/userguide/remote-mcp.md` — end-user guide for connecting ChatGPT (Settings → Apps → New App BETA → Advanced OAuth → DCR) and Claude.ai (Settings → Connectors → + → Add custom connector).

**Admin operations (Phase 5)** — `8be942a7c`:

* `/admin/remote-mcp` React page with three tables (Pending / Approved / Revoked) + audit viewer + kill switch
* `GET /admin/api/oauth/clients` lists clients by status; approve/revoke endpoints require typed-string confirmation for destructive actions
* `GET /admin/api/mcp/audit` — paginated audit log over `log/mcp.jsonl` with whitelisted query keys
* `POST /admin/api/mcp/kill-switch` — typed-string confirm, atomically revokes every refresh token across every approved client (read-only access tokens still expire on their existing 15-minute TTL)

**Security audit fixes + ChatGPT compatibility** — `926a597bf`:

* Migrated from deprecated `authlib.jose` → `joserfc` with explicit `algorithms=["RS256"]` pinning
* `MCP_PUBLIC_URL` is a hard requirement when `MCP_HTTP_ENABLED=True` — collapsing it to empty would let JWTs minted on instance A be replayed against instance B's loopback
* `error_detail` in MCP responses replaced with generic *"Tool execution failed"* — the full detail is in the audit log only, so SQL errors / stack traces don't leak to the model
* Added path-relative discovery alias `/mcp/.well-known/oauth-protected-resource` because ChatGPT fetches it that way (RFC 9728 says root-relative is canonical, but ChatGPT does both)
* Default `MCP_RATE_LIMIT_WRITE` raised from 5/min → 50/min based on real ChatGPT/Claude usage patterns
* Removed the vestigial `MCP_OAUTH_LOGIN_AUTH_LEVEL` env var (replaced by the per-purpose 2FA flags)

**CSP and consent screen fixes** — `52c96a11a`, `5f60b4817`, `3175a4104`:

* Per-page CSP on the consent screen sets `form-action` to allow exactly the registered redirect_uri's origin — fixes the form-submit block when the global CSP middleware would otherwise refuse the cross-origin POST
* Global CSP middleware (`csp.py`) now respects view-set CSP headers (won't overwrite if a header is already set)
* `tools/list` response now includes the real Pydantic-generated JSON schemas (reach into FastMCP's `_tool_manager._tools`) so ChatGPT stops hallucinating parameter names like `product_type` instead of `product`
* Removed Jinja-time `csrf_token()` dependency on the consent template — render the token via `_csrf_token_value()` helper inside the view so timing-of-globals isn't an issue

**Three new admin endpoints + four new database models:**

| New | Purpose |
| --- | --- |
| `database/oauth_db.py` | `OAuthClient`, `OAuthRefreshToken` (with `family_id` / `parent_id`), `OAuthSigningKey` |
| `database/user_db.py` | 4 boolean columns + `find_user_by_exact_username()` |
| `utils/oauth_keys.py` | RS256 keypair generation + rotation + `public_jwks()` |
| `utils/oauth_tokens.py` | `issue_access_token`, `rotate_refresh_token`, `verify_access_token` |

**Default security posture:**

| Setting | Default | Why |
| --- | --- | --- |
| `MCP_HTTP_ENABLED` | `False` | Off until you opt in |
| `MCP_OAUTH_REQUIRE_APPROVAL` | `True` | DCR clients land pending until admin approves |
| `MCP_OAUTH_WRITE_SCOPE_ENABLED` | `False` | Order placement unreachable until you flip the switch |
| `MCP_RATE_LIMIT_READ` | `60/min` | Per-token sliding window |
| `MCP_RATE_LIMIT_WRITE` | `50/min` | Per-token sliding window |
| `MCP_MAX_ORDER_QTY` | `0` (no cap) | Recommend setting a sane cap |

***

**Symbol Search expansion (#1326)**

* `232c637fb` — `feat(search): lift 500 cap, allow exchange-only browse, add search history`
* `f0c03eede` — `feat(search): multi-exchange/instrumenttype, CSV download, copy formats`

The Symbol Search page now supports filtering across multiple exchanges and multiple instrument types in a single query, browsing an entire exchange without entering a search term, downloading the result set as CSV, and copying selections in AmiBroker / TradingView / Python / Excel formats. The previous 500-row hard cap is gone — large result sets stream incrementally. Per-user search history is preserved across sessions.

***

**Admin / Operations**

* `566113d49` — `feat(admin): add Diagnostics page with system info, error browser, and downloadable report`

`/admin/diagnostics` consolidates the moving parts of "what's going on with this install" into a single React page: Python / Flask / SQLAlchemy versions, database sizes for all six SQLite/DuckDB databases, broker session state, configured env vars (with secrets redacted), a paginated browser over `log/errors.jsonl` with stack traces and Flask request context, and a one-click **Download diagnostic bundle** that produces an env-redacted ZIP suitable for attaching to a support ticket.

***

**Brokers**

**Zerodha**

* `6bc37381e` — `feat(zerodha): support NCO and GLOBAL_INDEX exchanges`

Adds two Zerodha-only exchange codes:
* **NCO** — NSE Commodities (Zerodha's symbol format differs from NCDEX; this fix routes correctly through the master contract download)
* **GLOBAL_INDEX** — US30, JAPAN225, HANGSENG, plus `GIFTNIFTY` from NSE IFSC. Quote-only by exchange convention; orders are not supported on GLOBAL_INDEX.

***

**Documentation**

* `199c544d1` — `docs: rename "virtual/paper trading" to "sandbox trading" terminology`
* `6efaf1655` — `docs: rename remaining "virtual" trading terms to "sandbox" equivalents`
* `500e27cbb` — `docs: add Remote MCP user guide for ChatGPT and Claude.ai`
* New `install/Remote-MCP-readme.md` — operator-focused install + threat model
* New `docs/prd/remote-mcp.md` — full product requirements doc with architecture, MUST/SHOULD/COULD security controls

The "virtual / paper trading" rename only touched display strings — the database (`db/sandbox.db`), blueprint (`blueprints/sandbox.py`), and API endpoints (`/api/v1/sandbox/*`) were already named `sandbox`. The rename closes a long-standing inconsistency between in-product copy and the underlying schema.

***

**Configuration changes**

`.sample.env`:

* `ENV_CONFIG_VERSION` `1.0.6` → `1.0.7`
* New section: `MCP_HTTP_ENABLED`, `MCP_PUBLIC_URL`, `MCP_OAUTH_REQUIRE_APPROVAL`, `MCP_OAUTH_WRITE_SCOPE_ENABLED`, `MCP_HTTP_CORS_ORIGINS`, `MCP_HTTP_IP_ALLOWLIST`, `MCP_OAUTH_ACCESS_TTL`, `MCP_OAUTH_REFRESH_TTL`, `MCP_OAUTH_CODE_TTL`, `MCP_RATE_LIMIT_READ`, `MCP_RATE_LIMIT_WRITE`, `MCP_MAX_ORDER_QTY`
* Removed: `MCP_OAUTH_LOGIN_AUTH_LEVEL` (vestigial — replaced by per-purpose 2FA flags)

`pyproject.toml`:
* `version = "2.0.1.0"`
* SDK pin (`openalgo==1.0.49`) unchanged

`utils/version.py`:
* `VERSION = "2.0.1.0"`

***

**Upgrade procedure**

**For existing installs (Native Ubuntu):**

```bash
cd /var/python/openalgo-flask/<deploy-name>/openalgo
sudo ./install/update.sh
# update.sh runs migrate_all.py — schema changes for the OAuth + 2FA columns
# are applied automatically. Remote MCP stays disabled by default.
```

**For existing installs (Docker):**

```bash
cd /opt/openalgo/<domain>
sudo docker compose pull
sudo docker compose up -d
# The container's start.sh runs migrate_all.py before gunicorn boots.
# Remote MCP stays disabled by default.
```

**To enable Remote MCP (after upgrading):**

```bash
# Native Ubuntu
sudo ./install/enable-remote-mcp.sh

# Docker
sudo ./install/enable-remote-mcp-docker.sh
```

Both enabler scripts are idempotent and back up `.env` before any change. They print a one-liner rollback command if the smoke probe fails.

**For local developers (uv):**

```bash
git pull origin main
uv sync
cd frontend && npm install && npm run build
uv run app.py
```

***

**Contributors**

* **@marketcalls (Rajandran)** — release management, Remote MCP architecture and full OAuth 2.1 implementation (5 phases — scaffold → OAuth foundation → 2FA wiring → discovery + JWKS + DCR → /authorize + /token + /revoke → Phase 2 UI → HTTP/SSE transport → install integration → admin UI), security audit + joserfc migration, CSP fixes for the consent flow, ChatGPT-compatibility hardening (path-relative discovery, real tool schemas, generic error_detail), Docker enabler, install integration, comprehensive PRD + operator docs + end-user docs, Symbol Search rewrite (#1326), Admin Diagnostics page, Zerodha NCO + GLOBAL_INDEX support, and the "virtual → sandbox" terminology cleanup.

***

**Links**

* **Repository**: <https://github.com/marketcalls/openalgo>
* **Documentation**: <https://docs.openalgo.in>
* **Remote MCP guide**: <https://docs.openalgo.in/mcp/remote-mcp>
* **Discord**: <https://www.openalgo.in/discord>
* **YouTube**: <https://www.youtube.com/@openalgo>
* **Issue tracker**: <https://github.com/marketcalls/openalgo/issues>

***


---

# Agent Instructions: Querying This Documentation

If you need additional information that is not directly available in this page, you can query the documentation dynamically by asking a question.

Perform an HTTP GET request on the current page URL with the `ask` query parameter:

```
GET https://docs.openalgo.in/change-log/release/version-2.0.1.0-released.md?ask=<question>
```

The question should be specific, self-contained, and written in natural language.
The response will contain a direct answer to the question and relevant excerpts and sources from the documentation.

Use this mechanism when the answer is not explicitly present in the current page, you need clarification or additional context, or you want to retrieve related documentation sections.
