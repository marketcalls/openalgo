# PRD: Remote MCP (self-hosted, OAuth-authenticated)

> **Status:** in development on branch `remotemcp`
> **Owner:** TBD
> **Related issue:** TBD

## Goal

Let a self-hosted OpenAlgo install expose its MCP tools to **hosted AI clients** (chatgpt.com, claude.ai, claude mobile) in addition to the existing local stdio integration with Claude Desktop / Cursor / Windsurf.

Concrete outcome: after running `install/install.sh` and pointing a domain at the server, the user can connect a hosted MCP client to `https://mcp.<their-domain>/mcp` and use OpenAlgo tools through standard OAuth.

## Non-goals

- **Multi-user**: a remote MCP server is still single-user, single-broker. The single OpenAlgo admin authorizes the client; there's no per-user MCP access.
- **Replacing the local stdio MCP**: stdio stays the default and works unchanged. Remote MCP is purely additive — opt-in, off by default.
- **A SaaS hosted MCP**: nothing runs on infrastructure operated by the OpenAlgo project.

## Coexistence requirement

Both transports must work:

| Transport | Use case | Auth | Default |
|---|---|---|---|
| stdio (`mcp/mcpserver.py`) | Claude Desktop, Cursor, Windsurf — local processes spawn the server | none (process boundary) | always available |
| HTTP+SSE (`blueprints/mcp_http.py`, new) | claude.ai, chatgpt.com, mobile, browser-side MCP clients | OAuth 2.1 + PKCE | opt-in via `MCP_HTTP_ENABLED=True` |

They share **one** tool registry. No tool is implemented twice.

## Architecture

```
                                                         ┌──────────────────────────┐
                                                         │  Hosted MCP client       │
                                                         │  (claude.ai / chatgpt)   │
                                                         └─────────┬────────────────┘
                                                                   │ OAuth + Bearer
                                                                   ▼
┌──────────────────────────────┐         ┌────────────────────────────────────────┐
│ Local MCP client              │         │ Flask app (Gunicorn + eventlet)        │
│ (Claude Desktop / Cursor)     │         │                                        │
└────────────┬──────────────────┘         │  ┌─────────────────────────────────┐   │
             │ stdio                       │  │ blueprints/mcp_oauth.py         │   │
             ▼                             │  │   /.well-known/* (discovery)    │   │
┌──────────────────────────────┐           │  │   /oauth/register (DCR)         │   │
│ mcp/mcpserver.py             │           │  │   /oauth/authorize              │   │
│   if __name__ == "__main__"  │           │  │   /oauth/token                  │   │
│   → mcp.run("stdio")          │           │  │   /oauth/revoke                 │   │
└────────────┬──────────────────┘           │  └─────────────────────────────────┘   │
             │                              │                                        │
             ▼                              │  ┌─────────────────────────────────┐   │
        ┌────────────────────────────────┐  │  │ blueprints/mcp_http.py          │   │
        │ mcp/tool_registry.py            │  │  │   POST /mcp (JSON-RPC dispatch) │   │
        │   mcp = FastMCP("openalgo")     │◀─┼──│   GET  /mcp (SSE stream)        │   │
        │   @mcp.tool()                   │  │  └─────────────────────────────────┘   │
        │   def place_order(...): ...     │  │                                        │
        │   ... (all tools)               │  │  ┌─────────────────────────────────┐   │
        └─────────────────────────────────┘  │  │ Existing service layer + REST   │   │
                                             │  │ /api/v1/* (broker calls)        │   │
                                             │  └─────────────────────────────────┘   │
                                             └────────────────────────────────────────┘
```

### Tool registry sharing

`mcp/mcpserver.py` is split into:

- **`mcp/tool_registry.py`** — the `FastMCP` instance and every `@mcp.tool()` definition. Pure logic, no transport concerns. Importable.
- **`mcp/mcpserver.py`** — kept as the stdio entry point. After the split it shrinks to ~10 lines: import the registry, `mcp.run()`. Existing `claude_desktop_config.json` users see no change.
- **`blueprints/mcp_http.py`** — imports the same `mcp` instance and exposes a JSON-RPC dispatcher over Flask routes. Bypasses FastMCP's HTTP server so it stays under our (eventlet-friendly) WSGI stack.

### Authentication flow

```
1. claude.ai POSTs to /mcp without a token.
2. Server returns 401 + WWW-Authenticate: Bearer
   resource_metadata="https://mcp.example/.well-known/oauth-protected-resource"
3. claude.ai fetches resource metadata, then authorization-server metadata.
4. claude.ai POSTs to /oauth/register (DCR) with its redirect_uri.
5. claude.ai redirects user to /oauth/authorize?... (with PKCE challenge).
6. User logs in to OpenAlgo (existing session) and approves scopes on a consent page.
7. Server redirects back to claude.ai with an authorization code.
8. claude.ai POSTs the code + verifier to /oauth/token; receives access + refresh.
9. claude.ai retries POST /mcp with Authorization: Bearer <access_token>.
10. Server validates JWT signature + scope; dispatches to tool registry.
```

### User authentication at the consent step

**Decision: the OpenAlgo dashboard login (username + password + TOTP), not the API key.**

There are two distinct credentials in play, which are easy to conflate:

| Credential | Who holds it | Where it's used in remote MCP |
|---|---|---|
| OpenAlgo login (username + password + TOTP) | Admin user, interactively at the browser | Gates `/oauth/authorize` — proves the human at the keyboard is the OpenAlgo admin and consents to grant the MCP client access |
| OpenAlgo API key | Server-side `.env` value | Used **inside** the tool implementations when they call back to `/api/v1/*` — the user never sees or enters it during OAuth |

The user-facing OAuth flow looks like:

```
1. claude.ai redirects to https://mcp.example/oauth/authorize?...
2. /oauth/authorize is gated by @check_session_validity:
   - If no valid session → standard OpenAlgo login page (username + password + TOTP)
   - On successful login → redirected back to the consent screen
3. Consent screen shows: "claude.ai wants: read:market, read:account [, write:orders]"
                         [Authorize]  [Deny]
4. Authorize → server emits authorization code → redirect back to claude.ai
```

Why login, not API key:

- **TOTP gate.** The login flow already enforces TOTP. API keys do not. Authorizing an order-placement client is exactly the moment a TOTP step is appropriate.
- **Right level of friction.** OAuth consent is a one-time interactive step. Pasting an API key on a consent screen is awkward and trains users to expose API keys in browsers.
- **Aligns with industry norm.** Kite, Google, GitHub, etc. all gate their OAuth `/authorize` with the same login the user uses for the dashboard, not with an API token.
- **Recovery story.** A user who loses their API key still has password+TOTP and can revoke MCP access; a user who loses password+TOTP would already be locked out of OpenAlgo entirely, so MCP is not a new dependency.

#### Fresh-auth requirement (MUST-HAVE for v1)

For sensitive scope grants, the existing session alone is not enough. Rules:

- **`read:*` only** — existing session sufficient. Click `Authorize` and proceed.
- **`write:orders`** — server requires a fresh TOTP within the last 60 seconds before showing the consent screen. If the user logged in 4 hours ago, they are re-prompted for TOTP only (not full password). Implemented via a `tot_verified_at` timestamp on the session.
- **Any scope, first-time client approval** (DCR client never approved before) — full re-auth: password + TOTP, regardless of session age. The first approval is the trust establishment step and deserves the friction.

#### `MCP_OAUTH_LOGIN_AUTH_LEVEL` config

| Value | Behavior |
|---|---|
| `session` | Any valid OpenAlgo session passes (least friction) |
| `totp` (**default**) | Fresh TOTP within 60s required for any `write:orders` grant |
| `password+totp` | Full re-auth on every `/authorize`, regardless of scope |

Default is `totp` — strikes the balance between UX and order-placement authority.

#### What about API key only?

If we ever want a non-interactive flow (e.g. headless test scripts), the API key path stays available via the existing `/api/v1/*` REST endpoints. **There is intentionally no MCP OAuth flow that accepts an API key as the user credential** — that would defeat the purpose of having an interactive consent step and lose the TOTP gate. CLI clients that want MCP access still go through the standard browser-based OAuth dance once; the resulting refresh token then enables headless use until it expires (30 days).

### Token model

| Token | Format | Storage | TTL | Notes |
|---|---|---|---|---|
| Access | RS256 JWT, signed with key in `keys/mcp_oauth_signing.pem` | none (stateless) | **15 min** | Includes `scope`, `client_id`, `jti` |
| Refresh | opaque random | hashed with `API_KEY_PEPPER` in `oauth_db.RefreshToken` | **30 days**, single-use, rotated | Identical hashing to API keys |
| Authorization code | opaque random | in-memory (dict with TTL) | **60 sec** | PKCE-verified, single-use |

### Scopes

Coarse, three-way split. Refining later as tools are added.

| Scope | Granted tools |
|---|---|
| `read:market` | quotes, depth, history, search, intervals, optionchain, optionsymbol |
| `read:account` | orderbook, tradebook, positionbook, holdings, funds, openposition, orderstatus |
| `write:orders` | place_order, place_smart_order, place_options_order, modify_order, cancel_order, cancel_all_orders, close_position, basket, split |

Each tool is annotated with its required scope in the registry. Token verification middleware enforces `scope` on every dispatch.

### Database

New file `database/oauth_db.py` with three tables in `db/openalgo.db`:

- `oauth_clients` — DCR-registered clients. Fields: `client_id`, `client_name`, `redirect_uris[]`, `created_at`, `approved` (bool, optional admin approval).
- `oauth_refresh_tokens` — `id`, `client_id`, `token_hash`, `scopes`, `created_at`, `expires_at`, `revoked_at`, `last_used_at`, `parent_token_id` (chain for rotation audit).
- `oauth_signing_keys` — `kid`, `algorithm`, `public_jwk`, `created_at`, `rotated_at`. Private key stays on disk under `keys/`.

Authorization codes are NOT persisted — kept in-memory with 60s TTL.

### Audit

Every MCP tool invocation logs to `log/mcp.jsonl`:

```json
{"ts": "...", "jti": "...", "client_id": "...", "scope": "write:orders",
 "tool": "place_order", "params_hash": "...", "duration_ms": 42, "outcome": "success"}
```

Params are NOT logged in full — only a SHA-256 hash for correlation. The actual order shows up in the existing trade logs anyway.

### Rate limits

Tighter than the regular API rate limits to protect order placement.

| Endpoint | Limit |
|---|---|
| `/oauth/register` (DCR) | 10/hour per IP |
| `/oauth/token` | 20/min per client_id |
| `POST /mcp` (read scopes) | 60/min per token |
| `POST /mcp` (write:orders) | 5/min per token |

## Security model — defense in depth

Exposing an order-placement surface to the public internet is fundamentally
high-risk: a stolen access token from a registered IP places real orders
that SEBI's static-IP rule cannot prevent. The defaults below are deliberately
restrictive — write tools are **off** by default even after MCP HTTP is
enabled. Users who want trading-via-MCP must consciously opt in twice.

### Defense layers

```
Internet → Cloudflare/WAF (recommended) → nginx → Flask
                                          ↓
                                  ┌───────────────┐
                                  │  Layer 0: TLS │  (Let's Encrypt, HSTS preload)
                                  └───────┬───────┘
                                          ↓
                                  ┌───────────────┐
                                  │  Layer 1: IP  │  optional MCP_HTTP_IP_ALLOWLIST
                                  └───────┬───────┘
                                          ↓
                                  ┌───────────────┐
                                  │  Layer 2: CORS│  exact origin match
                                  └───────┬───────┘
                                          ↓
                                  ┌───────────────┐
                                  │  Layer 3: Rate│  per-IP, per-client, per-token
                                  └───────┬───────┘
                                          ↓
                                  ┌───────────────┐
                                  │  Layer 4: OAuth│ PKCE, JWT signature, exp, jti
                                  └───────┬───────┘
                                          ↓
                                  ┌───────────────┐
                                  │  Layer 5: Scope│ read-only vs write gates
                                  └───────┬───────┘
                                          ↓
                                  ┌───────────────┐
                                  │  Layer 6: Tool │ per-tool quantity caps,
                                  │  guards        │ confirmation, kill switch
                                  └───────┬───────┘
                                          ↓
                                  ┌───────────────┐
                                  │  Layer 7: Audit│ jsonl log + Telegram notify
                                  └───────────────┘
```

### MUST-HAVE for v1 (release blocker if any are missing)

1. **PKCE S256 only.** `code_challenge_method=plain` is rejected; only `S256` is advertised in discovery and accepted at the token endpoint.
2. **Refresh token rotation with reuse detection.** Each refresh token is single-use. If a revoked refresh token is presented, the entire token family (chain via `parent_token_id`) is immediately revoked — RFC 6749 §10.4 pattern. Forces an attacker who stole one refresh to lose all subsequent tokens the moment the legitimate client refreshes.
3. **Write tools off by default.** `MCP_OAUTH_WRITE_SCOPE_ENABLED=False` is the default. Even with `MCP_HTTP_ENABLED=True`, the `write:orders` scope is not advertised in discovery and any token request that asks for it returns `invalid_scope`. The admin must explicitly opt in by flipping the env var and restarting.
4. **DCR requires admin approval by default.** `MCP_OAUTH_REQUIRE_APPROVAL=True`. New DCR registrations land in `pending` state and cannot complete the OAuth flow until the admin approves them on `/admin/oauth-clients` (new admin tile). This stops the "anyone in the world can start an OAuth flow against your server" attack.
5. **Pre-flight refusal in debug mode.** If `FLASK_DEBUG=True` *and* `MCP_HTTP_ENABLED=True`, app startup fails with a clear error. Debug mode leaks tokens via `werkzeug` tracebacks and must never coexist with the MCP transport.
6. **Tokens hashed with `API_KEY_PEPPER`.** Refresh tokens never persist in plaintext. Same Argon2/HMAC pipeline as OpenAlgo API keys.
7. **Signing key on disk.** RS256 private key in `keys/mcp_oauth_signing.pem`, chmod `600`, owned by the OpenAlgo process user. Auto-generated by install scripts. Not in git, not in `.env`.
8. **Audit log for every tool call.** Append-only `log/mcp.jsonl`. Contains `ts`, `jti`, `client_id`, `tool`, `scope`, `params_hash` (SHA-256 of the JSON-canonical params), `duration_ms`, `outcome`, `request_ip`. Params are NOT logged in full — only hashed for correlation against the existing trade log.
9. **Telegram notification on every write tool call** when the existing Telegram bot is configured. The notification fires **before** the order goes to the broker so the admin gets a chance to see "MCP is about to place X" and revoke if surprising. Re-uses existing `services/telegram_bot_service.py`.
10. **Kill switch endpoint.** `POST /admin/mcp/disable` (admin-session-gated) atomically: sets a runtime flag that 503s every `/mcp` request, revokes all refresh tokens, dumps the in-memory access-token allowlist. One click stops the world without restarting Gunicorn.
11. **Per-tool rate limits.** Defaults: `5/min` for `write:orders`, `60/min` for `read:*`. Enforced per token (`jti`), not per IP — a single compromised token can't slip past by hopping IPs.
12. **Per-IP rate limits on auth endpoints.** `/oauth/register` 10/hour, `/oauth/token` 20/min, `/oauth/authorize` 30/min. These run *before* OAuth so brute-force / spray attacks fail fast.
13. **Exact `redirect_uri` match.** No wildcards, no path-prefix matching. The registered URI is compared character-by-character at both `/oauth/authorize` and `/oauth/token`.
14. **Strict CORS allowlist.** `Access-Control-Allow-Origin` is set only for origins in `MCP_HTTP_CORS_ORIGINS` (default: `https://claude.ai,https://chatgpt.com`). Pre-flight responses don't reveal the full allowlist on a mismatch — they just return without the CORS headers.
15. **Sensitive-data redaction.** Existing `SensitiveDataFilter` in `utils/logging.py` is extended to redact `Authorization: Bearer …`, `client_secret`, `code`, and `refresh_token` values from any log path the MCP code touches.
16. **Short access TTL.** 15 minutes. Refresh-only path forces revocation propagation within one TTL window.
17. **`kid` rotation support.** Two signing keys (`active` + `previous`) advertised in JWKS for one TTL window after rotation. Validation accepts either. Compromise response: drop `previous`, restart, force re-auth.
18. **Replay protection on writes.** Every JSON-RPC request with a `write:orders` scope must include a client-generated `request_id` (UUID). Server tracks the last 1000 `request_id`s per token in-memory; duplicates within the access-token window are rejected with `idempotency_replay`.

### SHOULD-HAVE for v1 (default-on, configurable)

19. **Optional IP allowlist for `/mcp`.** `MCP_HTTP_IP_ALLOWLIST=1.2.3.4,5.6.7.0/24`. When set, all MCP requests are rejected unless the source IP matches. Empty (default) = no IP filtering. Useful if the user's MCP client lives on a known fixed egress.
20. **Kill switch on session timeout.** If the OpenAlgo admin hasn't logged in for the configurable session inactivity window (`MCP_INACTIVITY_REVOKE_DAYS`, default 7), all refresh tokens are revoked. A live admin must re-authorize the MCP client. Catches the "user forgot they enabled this" failure mode.
21. **Inbound order quantity cap.** `MCP_MAX_ORDER_QTY` (default `0` = no cap). When set, any tool placing an order with `quantity > cap` is rejected at the dispatcher before reaching the broker.
22. **Confirmation token for high-value writes.** Optional `MCP_CONFIRM_WRITES=True`. When set, write tools require an additional `confirm_token` parameter that the client obtains from a separate `/oauth/confirm-write` endpoint, which displays an admin consent prompt for that single tool call. Adds a per-trade human-in-the-loop step.
23. **Telegram-driven kill switch.** If Telegram is configured, the user can reply `/mcp_disable` in the bot to trigger the same kill switch. Useful when away from the dashboard.

### NICE-TO-HAVE (deferred to v1.1)

24. **Anomaly detection** — flag and auto-disable on patterns like 100 orders in 1 minute, or sudden symbol changes outside historical norm.
25. **Geographic / ASN restrictions** — extend the existing IP-ban list to also work as an MCP-only allowlist with country / ASN granularity.
26. **mTLS option** — pre-shared client cert in addition to OAuth, for paranoid setups.
27. **Bot Management hooks** — explicit Cloudflare Turnstile challenge on `/oauth/authorize`.

### Threat → mitigation table

| Threat | Mitigation |
|---|---|
| Token theft → unauthorized order placement | (1) Write tools off by default, (3) 15-min access TTL, (11) per-token write rate limit `5/min`, (18) request_id replay protection, (9) Telegram notification fires before broker call, (10) one-click kill switch |
| DCR abuse: world-readable registration endpoint | (4) admin approval default-on; (12) per-IP `/oauth/register` rate limit `10/hour` |
| Refresh token replay | (2) single-use rotation + family revocation on re-use; refresh tokens stored hashed |
| Code interception | (1) PKCE S256 mandatory; (13) exact `redirect_uri` match |
| Open redirect | (13) exact match — no wildcards, no prefix |
| Cross-origin token exfil from compromised browser | (14) strict CORS allowlist; (3) short access TTL limits exfil window |
| Long-running tool starves event loop | Per-tool soft-timeout (5s reads / 30s writes); cooperative `eventlet.sleep(0)` between batches |
| Debug-mode catastrophic exposure | (5) pre-flight refusal — Flask refuses to start with both flags on |
| Signing key compromise | (17) `kid` rotation; private key chmod 600, in `keys/` |
| Compromised client_secret | DCR-issued secrets stored hashed; rotation via `/oauth/register/<client_id>` PUT |
| Forgotten enablement → token still valid months later | (20) inactivity-based revocation; (10) kill switch |
| Operator accident: admin enables MCP_HTTP but never realizes write is off | Documentation + post-install banner + admin Diagnostics page shows MCP status prominently |
| Quantity-based abuse (legit token, harmful trade) | (21) `MCP_MAX_ORDER_QTY`; (22) optional per-write confirmation |
| Eventlet single-worker DoS via slow MCP traffic | Per-token rate limits run *before* tool dispatch; SSE streams have idle timeouts |
| SEBI static-IP bypass | Not exploitable — broker calls still originate from registered server IP. The trust boundary is the admin's OAuth approval, not the IP. |
| Log-based credential leak | (15) `SensitiveDataFilter` extended for OAuth fields |
| Privilege escalation across scopes | Token signature includes `scope` claim; verifier rejects tools whose required scope isn't in the token's scope set |
| Compromised OpenAlgo admin password → MCP takeover | Same blast radius as compromised admin already. Mitigation is on the OpenAlgo side (Argon2, rate-limited login). MCP doesn't widen this. |
| Discovery endpoint leak of internal hostnames | Discovery returns only the configured `MCP_PUBLIC_URL`, never internal IPs |

### Configuration (`.sample.env`)

```bash
# === Remote MCP (HTTP + OAuth) ===
# Off by default. Local stdio MCP works without these.
MCP_HTTP_ENABLED = 'False'

# Public origin where the MCP HTTP transport is reachable.
# Used in OAuth discovery metadata. Must be HTTPS in production.
MCP_PUBLIC_URL = 'https://mcp.example.com'

# OAuth signing key (RS256). Auto-generated by install scripts.
MCP_OAUTH_SIGNING_KEY = 'keys/mcp_oauth_signing.pem'

# Require admin approval before a DCR client can complete OAuth.
# Recommended for production. When True, register puts the client in
# pending state visible at /admin/oauth-clients.
MCP_OAUTH_REQUIRE_APPROVAL = 'True'

# CORS allowlist for the MCP HTTP endpoint. Comma-separated.
MCP_HTTP_CORS_ORIGINS = 'https://claude.ai,https://chatgpt.com'

# Token TTLs (seconds). Sane defaults; only override for testing.
MCP_OAUTH_ACCESS_TTL = '900'      # 15 min
MCP_OAUTH_REFRESH_TTL = '2592000' # 30 days
MCP_OAUTH_CODE_TTL = '60'

# Per-token rate limits.
MCP_RATE_LIMIT_READ = '60 per minute'
MCP_RATE_LIMIT_WRITE = '5 per minute'
```

### Install integration

`install/install.sh` gains an optional MCP block:

```
[?] Enable remote MCP server (allows ChatGPT/Claude.ai to call OpenAlgo)? [y/N]
[?] MCP subdomain (e.g. mcp.yourdomain.com):
  - Generates RS256 signing key under keys/
  - Adds nginx server block with Let's Encrypt cert
  - Sets MCP_HTTP_ENABLED=True and MCP_PUBLIC_URL in .env
```

Defaults to **No**. The install scripts that already handle TLS (`install-docker-multi-custom-ssl.sh`, `change-domain.sh`) get matching support.

### Phased plan (one PR per phase)

| Phase | Scope | Branch state | Est |
|---|---|---|---|
| **1 — Foundation** *(this PR)* | PRD, scaffold blueprints, config keys, dependency add, tool-registry split skeleton | branch builds, no behavior change | — |
| **2 — OAuth server** | `mcp_oauth.py` with Authlib: discovery, DCR, authorize, token, revoke. DB models. Admin consent UI. No MCP transport yet. | OAuth flow demonstrably works against a CLI test client | ~1 wk |
| **3 — MCP HTTP transport** | `mcp_http.py` with JSON-RPC dispatcher reading the shared tool registry. Token validation middleware. SSE stream. Audit log. Rate limits. | claude.ai connector test passes end-to-end | ~1 wk |
| **4 — Install integration** | `install.sh` MCP block, nginx template, signing key generation, TLS via existing Let's Encrypt path | one-shot install on Ubuntu produces a working `https://mcp.<domain>/mcp` | ~3 days |
| **5 — Hardening + docs** | External security review, threat-model walkthrough, user docs, mention in README | ready to announce | ~3 days |

### Open questions

1. **Authlib vs hand-rolled** — Authlib brings ~600KB of dep weight but removes a category of crypto bugs. Default: Authlib. Will revisit if it conflicts with eventlet.
2. **Discovery URL shape** — RFC 8414 says `/.well-known/oauth-authorization-server`. MCP spec also references resource metadata at `/.well-known/oauth-protected-resource`. Implementing both.
3. **Per-tool re-auth for high-value writes** — should `place_order` require a token issued in the last 60s? Adds friction. Default: no re-auth, instead rely on rate limits + audit. Re-evaluate after security review.
4. **Single-tenant simplification** — DCR allows arbitrary client registration. For a single-user install we could short-circuit with one pre-approved client per OpenAlgo install. Default: keep DCR (matches MCP spec); add `MCP_OAUTH_REQUIRE_APPROVAL` for friction-on-demand.
5. **Mobile / native client UX** — claude.ai mobile follows the same OAuth flow but the redirect dance feels heavy. No special handling planned for v1.

### Out of scope for this branch

- ChatGPT custom GPTs / OpenAI's MCP support — same protocol, should "just work" but won't be explicitly tested in v1
- Multi-broker switching via MCP (the current OpenAlgo session ties one user to one broker)
- Streaming tool responses for very large reads (history, instruments) — v1 returns whole payloads
