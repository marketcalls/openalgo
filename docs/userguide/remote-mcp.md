# Remote MCP

## OpenAlgo Remote MCP — Hosted AI Clients via OAuth

Brings the OpenAlgo MCP toolset to **hosted AI clients** — ChatGPT, Claude.ai, Claude mobile, anything that speaks the MCP HTTP transport — over the public internet using OAuth 2.1 with PKCE.

The local stdio MCP (Claude Desktop / Cursor / Windsurf running on the same machine as your OpenAlgo install) keeps working unchanged. Remote MCP is a parallel, opt-in transport that **shares the same 40 tools** but reaches them over HTTPS instead of a stdin/stdout pipe.

***

### When to use Remote MCP vs. local stdio

| You want to... | Use |
| --- | --- |
| Trade from your laptop using Claude Desktop, Cursor, or Windsurf | **Local stdio** ([MCP setup guide](./)) |
| Use ChatGPT.com, Claude.ai, or Claude mobile to manage trades | **Remote MCP** (this guide) |
| Both | Enable both — they share tool definitions but run independently |

You don't have to choose: enabling Remote MCP **does not** disturb the local stdio integration. Existing Claude Desktop configs keep working untouched.

***

### Prerequisites

#### 1. A working OpenAlgo install with a custom domain

Remote MCP needs HTTPS. You should already have:

* OpenAlgo dashboard reachable at `https://yourdomain.com` (or any subdomain you used)
* A Let's Encrypt or custom SSL cert installed
* The dashboard fully working — login, broker auth, orders all functional via the web UI

If you're not there yet, start with one of the install scripts:

* **Native Ubuntu (single domain)** → `install/install.sh`
* **Native Ubuntu (multiple domains)** → `install/install-multi.sh`
* **Docker (single instance)** → `install/install-docker.sh`
* **Docker (multi-instance + custom SSL)** → `install/install-docker-multi-custom-ssl.sh`

#### 2. OpenAlgo platform version 2.0.1.0 or later

Check at the bottom of the dashboard footer or via:

```bash
curl https://yourdomain.com/api/v1/openalgo-version
```

If you're on an older version, run `install/update.sh` first — it pulls the latest code and runs database migrations automatically.

#### 3. An OpenAlgo API key

Same as local stdio. Generate one at **Profile → API Keys** if you haven't already. The MCP server uses your API key server-side to call the underlying `/api/v1/*` endpoints — hosted clients never see it; they get OAuth tokens instead.

***

### Quick start — enable Remote MCP

OpenAlgo ships **two enabler scripts** that handle the env-var changes, signing-key generation, schema migrations, service restart, and endpoint smoke checks. Pick the one matching your install:

#### Native Ubuntu (`install.sh` / `install-multi.sh`)

```bash
cd /path/to/openalgo
sudo ./install/enable-remote-mcp.sh
```

The script:

1. Detects all `openalgo-*` systemd services (asks you to pick if you have multiple)
2. Refuses if `FLASK_DEBUG=True` is set (token leak risk)
3. Backs up your `.env`, then sets the four MCP keys
4. Runs `upgrade/migrate_all.py` to apply schema changes
5. Restarts the service
6. Probes `/.well-known/oauth-authorization-server`, `/oauth/jwks.json`, `/mcp/healthz` to confirm everything responds

#### Docker (`install-docker.sh` / `install-docker-multi-custom-ssl.sh`)

```bash
cd /path/to/openalgo
sudo ./install/enable-remote-mcp-docker.sh
```

The script:

1. Walks `/opt/openalgo/*/docker-compose.yaml` (override with `INSTALL_BASE=/your/path`)
2. Picks one stack if multiple exist; re-run for each instance you want enabled
3. Backs up the bind-mounted per-instance `.env`
4. Updates the four MCP keys
5. `docker compose restart` — container's `start.sh` runs migrations automatically before gunicorn comes up
6. Same five-endpoint smoke probe as the native helper

#### Same defaults on both paths

| Key | Default | Why |
| --- | --- | --- |
| `MCP_HTTP_ENABLED` | `True` | Master switch the script flips on |
| `MCP_PUBLIC_URL` | Your dashboard domain | Anchors JWT iss/aud claims |
| `MCP_OAUTH_REQUIRE_APPROVAL` | `True` | Newly registered DCR clients land pending until you approve |
| `MCP_OAUTH_WRITE_SCOPE_ENABLED` | `False` | **Read-only by default** — order placement disabled until you opt in |
| `MCP_HTTP_CORS_ORIGINS` | `https://claude.ai,https://chatgpt.com` | Browser-side OAuth flow allowlist |

***

### Connecting & using ChatGPT and Claude

Once Remote MCP is enabled, your MCP URL is:

```
https://yourdomain.com/mcp
```

The OAuth dance is automatic via Dynamic Client Registration (DCR) — you don't pre-register anything in OpenAlgo. The hosted client introduces itself, you approve it once at `/admin/remote-mcp`, and from then on the client refreshes its own tokens silently.

The first-connect shape is the same on both ChatGPT and Claude:

```
You add the URL in the AI app
   → AI app calls /oauth/register   (DCR — creates a pending client)
      → AI app calls /oauth/authorize  → "pending approval" error
         → You log into OpenAlgo, approve at /admin/remote-mcp
            → AI app retries  /oauth/authorize
               → Browser pops to OpenAlgo login
                  → You log in (+ TOTP if MCP 2FA is on)
                     → Consent screen lists scopes — you approve
                        → Browser bounces back to AI app with auth code
                           → AI app exchanges code for access + refresh tokens
                              → You can now ask the AI to use OpenAlgo tools
```

***

#### Adding OpenAlgo to ChatGPT

⚠️ **Heads up — terminology has changed.** ChatGPT recently renamed **Connectors → Apps**. The same MCP feature lives under **Settings → Apps** now. The in-chat menu still says *Connectors* though, so don't be confused.

**Requirements**: ChatGPT Plus / Team / Enterprise — custom MCP servers are not in the free tier.

##### Step 1 — Open Apps settings

1. Click your avatar (bottom left) → **Settings**
2. In the left sidebar pick **Apps**
3. You'll see your **Enabled apps** at the top and a **Drafts** section below for apps still in dev mode
4. Click **Add more** (top right) — opens the **New App BETA** modal

##### Step 2 — Fill in the New App form

| Field | Value |
| --- | --- |
| **Icon** | Optional — upload a 128×128 PNG if you want |
| **Name** | `OpenAlgo` (or `OpenAlgo MCP`) |
| **Description** | `OpenAlgo trading server` (optional) |
| **MCP Server URL** | `https://yourdomain.com/mcp` |
| **Authentication** | `OAuth` (pick from the dropdown) |

##### Step 3 — Configure Advanced OAuth settings

Expand **Advanced OAuth settings** — a panel slides in from the right.

Under **Client registration**:

| Field | Value |
| --- | --- |
| **Registration method** | `Dynamic Client Registration (DCR)` |

You may see a notice that *"CIMD is unavailable because the server did not advertise CIMD support"* — that is expected. OpenAlgo advertises DCR, not Client Identifier Metadata Document. DCR is the right choice.

Under **Scopes**:

* Default scopes ChatGPT requests: `read:market read:account`
* Add `write:orders` **only if** (a) you've set `MCP_OAUTH_WRITE_SCOPE_ENABLED=True` server-side, and (b) you actually want this connector to be able to place orders

Close the Advanced panel.

##### Step 4 — Acknowledge the risk and create

Below the form there's an orange warning:

> ⚠️ *Custom MCP servers introduce risk. OpenAI hasn't reviewed this MCP server. Attackers may attempt to steal your data or trick the model into taking unintended actions, including destroying data.*

Tick **"I understand and want to continue"**, then click **Create** (bottom right).

##### Step 5 — Hit the expected error

ChatGPT immediately tries the OAuth flow and shows:

> ❌ *OAuth authorization failed: unauthorized_client*

This is **normal and expected** on the first attempt — your OpenAlgo server saw the registration but is holding the client in the pending bucket waiting for you. Don't click Cancel; just leave the modal as-is.

##### Step 6 — Approve the client in OpenAlgo

1. Open a new browser tab to `https://yourdomain.com`
2. Sign in to OpenAlgo (TOTP if MCP 2FA is on)
3. Go to **Admin → Remote MCP** (or directly `https://yourdomain.com/admin/remote-mcp`)
4. The **Pending approvals** card shows the new client. The `client_name` will be set by ChatGPT (e.g. *"ChatGPT MCP Connector"* or whatever you typed in **Name**), and `client_id_issued_at` will be the last few seconds
5. Verify it's the right one (timestamp + name match), then click **Approve**

##### Step 7 — Complete OAuth

1. Switch back to the ChatGPT tab
2. Click **Reconnect** (or close + reopen the app — both work; ChatGPT keeps the same `client_id`)
3. A new tab pops to `https://yourdomain.com/oauth/authorize?...`
4. Sign in to OpenAlgo if you aren't already
5. The **consent screen** appears showing client name, redirect URI (verify it's a `chatgpt.com` URL!), and the scopes
6. Click **Authorize** — browser bounces to ChatGPT, exchanges code for tokens
7. App goes from Drafts to Enabled apps with status active

##### Step 8 — Use it in a chat

In any new chat:

1. Click the `+` icon below the message box → **Connectors**
2. Toggle **OpenAlgo** ON for this chat
3. Ask a read-only question:

   > *"Using OpenAlgo, give me the LTP of RELIANCE on NSE."*

ChatGPT calls `get_quote` and returns a live price.

If you granted `read:account`, also try:

> *"What's my account balance and current open positions?"*

That uses `get_funds` + `get_positions`.

##### ChatGPT — what works and what doesn't

* ✅ All read-only tools work cleanly: quotes, depth, holdings, positions, funds, history, orderbook
* ✅ `modify_order`, `cancel_order`, `cancel_all_orders` usually go through
* ⚠️ `place_order` — ChatGPT often **blocks at its own safety layer** even when `write:orders` was granted. The tool call is shown, the model tries, OpenAI's policy layer refuses. This is a ChatGPT limit, not OpenAlgo's. If you need order placement from a hosted client, use Claude.ai

##### ChatGPT — useful prompts

* *"Get me the bid-ask spread for INFY and HDFCBANK"*
* *"Summarise my holdings and tell me which are in profit"*
* *"Pull 1-day candles for SBIN for the last 30 days and tell me the trend"*
* *"List my orders from today and show fills vs rejects"*

***

#### Adding OpenAlgo to Claude.ai

**Requirements**: Claude Pro, Team, or Enterprise account. Custom connectors are not in the free tier.

##### Step 1 — Open the Connectors page

1. Open **claude.ai** and sign in
2. Click your name (bottom left) → **Settings**
3. In the left sidebar pick **Connectors**
4. The page shows two groups: **Web** (your active connectors, with `CUSTOM` badge for ones you've added) and **Not connected**

##### Step 2 — Add a custom connector

1. Top-right of the Connectors list, click the **+** button
2. A small menu appears with two options — pick **Add custom connector**
   * (The other option, *Browse connectors*, is for first-party Anthropic ones — Gmail, Drive, etc.)

##### Step 3 — Fill in the modal

The **Add custom connector BETA** modal has just two main fields:

| Field | Value |
| --- | --- |
| **Name** | `OpenAlgo` |
| **Remote MCP server URL** | `https://yourdomain.com/mcp` |

Below them is a collapsed **Advanced settings** section — for OpenAlgo you can leave it alone; OAuth is detected automatically from `/.well-known/oauth-protected-resource`.

The trust warning underneath reads:

> *Only use connectors from developers you trust. Anthropic does not control which tools developers make available and cannot verify that they will work as intended or that they won't change.*

Click **Add**.

##### Step 4 — Hit the expected error

Same as ChatGPT — the first attempt fails with a pending-approval error because your OpenAlgo server holds the new DCR client until you approve it. Don't dismiss; keep the page open.

##### Step 5 — Approve in OpenAlgo

1. New tab → `https://yourdomain.com/admin/remote-mcp`
2. Sign in
3. **Pending approvals** card → the just-arrived Claude client → **Approve**

##### Step 6 — Complete OAuth

1. Back in claude.ai → click **Connect** on the connector card again
2. A browser tab opens to your OpenAlgo `/oauth/authorize`
3. Sign in (+ TOTP if MCP 2FA is on for the MCP purpose)
4. Consent screen lists requested scopes — verify the redirect URI is a `claude.ai` URL
5. Click **Authorize**
6. Bounces back; the connector card now shows **Disconnect** instead of Connect — you're live

##### Step 7 — Configure tool permissions

This is where Claude is more granular than ChatGPT. Click your **OpenAlgo** connector in the list and you'll see the right pane fill with **Tool permissions**:

| Group | What to set |
| --- | --- |
| **Interactive tools** | `place_order`, `modify_order`, `cancel_order`, etc. — set to **Always allow** if you want zero friction, or **Ask me** if you want a confirmation prompt before every order |
| **Read-only tools** | Quotes, depth, holdings, etc. — usually fine on **Always allow** |
| **App-only tools** | Internal helpers — leave on **Always allow** |

You can also expand each group and override permissions on individual tools — e.g. *Always allow* most tools but force *Ask me* specifically for `cancel_all_orders`.

##### Step 8 — Use it in a chat

In any new chat, Claude exposes the connector via the **🔧 Tools** icon below the message box. Make sure **OpenAlgo** is toggled on for that chat (you can disable per-chat if you don't want trading tools active).

Try:

> *"Show me the current LTP of NIFTY 50 and give me a quick view of my open positions."*

Claude shows tool-call cards you can expand to inspect the exact parameters. If a tool is set to *Ask me*, you'll get a permission prompt with **Allow once / Always allow / Deny**.

##### Claude.ai — what works (more permissive than ChatGPT)

* ✅ All read-only tools work
* ✅ All write tools work — `place_order`, `modify_order`, `cancel_order`, `cancel_all_orders` go through
* ✅ Same OAuth tokens automatically work in the **Claude iOS / Android apps** — no separate setup; chat-trade from your phone

##### Claude.ai — recommended posture for write tools

* Start in **Sandbox / Analyzer mode** in OpenAlgo to dry-run prompts (toggle at `/analyzer`)
* Set `MCP_MAX_ORDER_QTY` to a sane cap (e.g. `10` for equity, `1` for a Nifty lot) so a model error can't place an outsized order
* Keep MCP 2FA on for the MCP purpose — every fresh authorization demands a TOTP code
* Tail `log/mcp.jsonl` while testing — every tool call is recorded with timestamp, scope, outcome, latency

##### Claude.ai — useful prompts

* *"Place a limit BUY for 1 share of TCS at ₹3500 in CNC product on NSE"* — `place_order`
* *"Modify my last open INFY order — change the quantity to 5"* — `modify_order`
* *"Cancel all my open orders"* — `cancel_all_orders`
* *"What was my P&L today?"* — `get_tradebook` + summary

For more example prompts per tool, see [Tool References](./tool-references.md) — every prompt there works on Remote MCP too.

***

#### Switching scopes after connecting

If you initially connected with `read:market read:account` and later want to add `write:orders`:

1. Make sure server-side `MCP_OAUTH_WRITE_SCOPE_ENABLED=True` (in `.env`)
2. **Disconnect** the connector / app in ChatGPT or Claude
3. Re-add it with the broader scope set
4. Re-approve at `/admin/remote-mcp`

You can't widen the scope of an existing token — OAuth requires re-consent. This is by design.

***

#### Verifying the connection from the OpenAlgo side

After connecting, on the OpenAlgo dashboard:

1. **`/admin/remote-mcp` → Approved clients** — you should see the client with `last_used_at` recent
2. **`/admin/remote-mcp` → MCP tool call audit** — each tool the AI invoked is logged with `client_id`, `tool`, `scope`, `outcome`, `latency_ms`, `params_hash` (raw params are not logged for safety)
3. **`log/mcp.jsonl`** — same data as JSON Lines; tail with `tail -f log/mcp.jsonl`

If the AI says *"the tool returned an error"* and refuses to elaborate, check the audit log — `outcome=error` rows include the reason.

***

#### Common errors at each step

| Error | Where | Cause | Fix |
| --- | --- | --- | --- |
| `unauthorized_client` | ChatGPT/Claude after Create/Add | DCR client not approved yet | Approve at `/admin/remote-mcp` |
| `invalid_client` | OAuth retry | Client was revoked or DB reset | Disconnect + re-add (forces fresh DCR) |
| *"Server doesn't implement OAuth"* | First connect | Old OpenAlgo build | Update to 2.0.1.0+ |
| *"CIMD is unavailable"* | ChatGPT advanced settings | OpenAlgo advertises DCR, not CIMD | Expected — pick **DCR** |
| Tools not appearing in chat | After connecting | Connector/app not toggled on for that chat | Toggle from `+` menu (ChatGPT) or 🔧 Tools menu (Claude) |
| `bad_arguments` on a tool call | During tool call | Hosted client hallucinated parameter names | Update OpenAlgo (newer builds expose strict tool schemas) |
| Sudden 401 on every tool call | Mid-session | Refresh token expired or kill switch fired | Click Reconnect on the connector |
| `place_order` blocked | ChatGPT only | ChatGPT's safety policy | Use Claude.ai for order placement, or stick to read-only on ChatGPT |

***

### Admin operations — `/admin/remote-mcp`

Full operations console for Remote MCP, gated behind your OpenAlgo admin login.

| Section | Use |
| --- | --- |
| **Pending approvals** | New DCR clients land here. Approve only ones you recognize (the client_name is set by the hosted client itself, e.g. *"ChatGPT MCP Connector"*). |
| **Approved clients** | Currently authorized — can complete OAuth flows and call MCP tools |
| **Revoked clients** | Historical record; cannot re-authorize without admin re-approval |
| **MCP tool call audit** | Tail of `log/mcp.jsonl` — every tool call by every client with timestamp, JTI, scope, outcome, latency. Filter by tool / scope / outcome. |
| **Kill switch** | Top-right red button. Two-step confirmation. Atomically revokes every refresh token across every approved client. Use if you suspect a stolen token, an unexpected order, or before disabling Remote MCP entirely. |

***

### 2FA enforcement

OpenAlgo's per-user TOTP can gate **three independent purposes** — toggle each in **Profile → TOTP tab → 2FA Enforcement**:

| Purpose | What it gates |
| --- | --- |
| Dashboard sign-in | Demands 6-digit code after password on every login |
| Remote MCP authorization | Demands fresh TOTP at `/oauth/authorize` when a client requests `write:orders` |
| Password reset | Forces TOTP path through reset (no email fallback) |

All three default to **off** so existing installs see no behavior change. Turn on the master switch first, then pick the purposes that apply. Saving requires a fresh TOTP code in the same request — proves you have authenticator access for both enabling and disabling.

For Remote MCP specifically: with the **MCP** purpose flag on, every grant of `write:orders` will demand a fresh code. Read-only grants are unaffected.

***

### Configuration reference

All of these go in your `.env` (native) or the bind-mounted `.env` (Docker). The enablers set the first five for you.

| Key | Default | Purpose |
| --- | --- | --- |
| `MCP_HTTP_ENABLED` | `False` | Master switch — when False, blueprints don't register |
| `MCP_PUBLIC_URL` | (required when enabled) | Canonical HTTPS origin advertised in OAuth metadata. Anchors JWT iss/aud |
| `MCP_OAUTH_REQUIRE_APPROVAL` | `True` | DCR clients land pending until admin approves |
| `MCP_OAUTH_WRITE_SCOPE_ENABLED` | `False` | Whether `write:orders` is even advertised in discovery |
| `MCP_HTTP_CORS_ORIGINS` | `https://claude.ai,https://chatgpt.com` | Comma-separated browser-origin allowlist |
| `MCP_HTTP_IP_ALLOWLIST` | empty | Optional IP / CIDR allowlist on `/mcp`. Empty = no filtering |
| `MCP_OAUTH_ACCESS_TTL` | `900` | Access-token TTL in seconds (capped at 3600) |
| `MCP_OAUTH_REFRESH_TTL` | `2592000` | Refresh-token TTL in seconds (30 days) |
| `MCP_OAUTH_CODE_TTL` | `60` | Authorization-code TTL (capped at 300) |
| `MCP_RATE_LIMIT_READ` | `60 per minute` | Per-token rate limit for read scopes |
| `MCP_RATE_LIMIT_WRITE` | `50 per minute` | Per-token rate limit for `write:orders` |
| `MCP_MAX_ORDER_QTY` | `0` | Hard cap on order quantity placed via MCP. `0` = no cap |

***

### Security model — defense in depth

```
Internet → Cloudflare/WAF (recommended)
        → nginx (TLS termination)
            → Layer 1: optional MCP_HTTP_IP_ALLOWLIST
                → Layer 2: CORS exact-origin match
                    → Layer 3: per-IP / per-token rate limits
                        → Layer 4: OAuth — PKCE, JWT signature, exp, jti
                            → Layer 5: scope check (read:market / read:account / write:orders)
                                → Layer 6: tool guards — quantity caps, kill switch, audit log
```

#### Highlights

* **PKCE S256 only** — `plain` is not advertised; `alg=none` and `alg=HS256` JWTs are rejected by the verifier
* **Refresh token rotation with reuse detection** — single-use; replay of a revoked token revokes the entire family (RFC 6749 §10.4)
* **Write tools off by default** — `MCP_OAUTH_WRITE_SCOPE_ENABLED=False` means order placement is unreachable until you flip the env var and restart
* **DCR approval gate** — random internet clients can register but cannot complete OAuth until the admin approves
* **Pre-flight refusal** — server refuses to start with `MCP_HTTP_ENABLED=True` and `FLASK_DEBUG=True` together (debug-mode tracebacks would leak bearer tokens)
* **Per-page CSP** — the consent screen sets a tight CSP that allows form submission only to the registered redirect_uri's origin
* **Audit log** — every tool call appended to `log/mcp.jsonl` with `params_hash` (not raw params) so the log isn't itself a data leak
* **Kill switch** — one click on `/admin/remote-mcp` revokes every refresh token

⚠️ **The blast radius is real.** A stolen access token can place orders that the broker accepts because they originate from your registered server IP. The 15-minute access TTL caps the damage window; the kill switch is your panic button. Do not enable `write:orders` and leave `MCP_OAUTH_REQUIRE_APPROVAL=False` together — that combination lets any internet client register, auto-approve, and start placing orders.

***

### Subdomain mode (advanced)

If you want MCP on a separate hostname (e.g. `mcp.yourdomain.com`) so its cookies, CORS, and TLS lifecycle are isolated from the dashboard, the manual recipe is in `install/Remote-MCP-readme.md`. It uses the same nginx + certbot patterns as `install-docker-multi-custom-ssl.sh`.

Why bother:

* Bug at `/mcp` cannot read dashboard session cookies (cookie scope)
* Tighter MCP-specific CORS allowlist
* Cert lifecycle for MCP rotates independently
* Drop just the MCP surface (DNS or nginx) without affecting the dashboard

For most users, **same-domain mode is enough**. The same-domain path is what the enablers automate.

***

### Troubleshooting

**ChatGPT says "MCP server does not implement OAuth"**

Hit `https://yourdomain.com/mcp/.well-known/oauth-protected-resource` directly. If it returns HTML instead of JSON, you're on an old build — pull the latest code and restart.

**"Error: Could not build URL for endpoint 'auth.login'"**

You're on the dev path (`uv run app.py`) without the auth blueprint registered. Use the production path or `install.sh` flow.

**`unauthorized_client` at `/oauth/authorize`**

Expected on first connect — go to `/admin/remote-mcp` and approve the pending client.

**`invalid_client` at `/oauth/authorize`**

The client was revoked or the database was reset. ChatGPT/Claude may have cached the old `client_id`. Disconnect/reconnect the integration to force a fresh DCR.

**Form submit blocked by Content Security Policy**

You're on a build before the per-page CSP fix. Update to `2.0.1.0` or later.

**Tool calls fail with `bad_arguments`**

The hosted client is using wrong parameter names. Check `log/mcp.jsonl` for the failed call. If `tools/list` is returning empty schemas, you're on a build before the schema-exposure fix — update.

**Container won't restart after enabler runs**

Enabler prints a one-liner rollback command pointing at the `.env` backup. Run it, restart, then investigate the logs in `log/errors.jsonl`.

**Tokens issued but `/mcp` returns 401**

Verify `MCP_PUBLIC_URL` matches the URL the client is using. The JWT's `iss` claim must match exactly — `https://example.com` vs `https://example.com/` vs `https://www.example.com` are all different to the verifier.

***

### Disabling

**Native Ubuntu:**

```bash
sudo sed -i "s|MCP_HTTP_ENABLED.*|MCP_HTTP_ENABLED = 'False'|" /var/python/openalgo-flask/<deploy-name>/.env
sudo systemctl restart openalgo-<deploy-name>
```

**Docker:**

```bash
sudo sed -i "s|MCP_HTTP_ENABLED.*|MCP_HTTP_ENABLED = 'False'|" /opt/openalgo/<domain>/.env
cd /opt/openalgo/<domain> && sudo docker compose restart
```

OAuth + MCP routes immediately stop responding. Existing tokens become unreachable. **Local stdio MCP is unaffected** — it runs through `mcp/mcpserver.py` over stdin/stdout and doesn't touch the HTTP transport at all.

For a softer takedown that keeps Remote MCP enabled but boots every active session: visit `/admin/remote-mcp` and click **Kill switch**. Hosted clients are forced through a fresh OAuth dance the next time they refresh.

***

### Related

* [MCP Server Setup Guide](./) — local stdio integration with Claude Desktop / Cursor / Windsurf
* [Tool References](./tool-references.md) — every tool with parameters and example prompts (shared across both transports)
* OpenAlgo Symbol Format — how equity / future / option symbols are constructed
* `install/Remote-MCP-readme.md` — operator-focused install + threat model in the source tree


---

# Agent Instructions: Querying This Documentation

If you need additional information that is not directly available in this page, you can query the documentation dynamically by asking a question.

Perform an HTTP GET request on the current page URL with the `ask` query parameter:

```
GET https://docs.openalgo.in/mcp/remote-mcp.md?ask=<question>
```

The question should be specific, self-contained, and written in natural language.
The response will contain a direct answer to the question and relevant excerpts and sources from the documentation.

Use this mechanism when the answer is not explicitly present in the current page, you need clarification or additional context, or you want to retrieve related documentation sections.
