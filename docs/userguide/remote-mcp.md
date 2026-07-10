# Remote MCP

Lets hosted AI clients — ChatGPT, Claude.ai, Claude mobile — talk to your OpenAlgo install over the internet so you can ask them to fetch quotes, summarise positions, or place orders in plain English.

Local stdio MCP (Claude Desktop / Cursor / Windsurf on the same machine as your install) keeps working unchanged. Remote MCP is a parallel, opt-in transport that shares the same tool registry but reaches it over HTTPS.

| You want to...                                                   | Use                                |
| ---------------------------------------------------------------- | ---------------------------------- |
| Trade from your laptop using Claude Desktop, Cursor, or Windsurf | **Local stdio** (MCP setup guide)  |
| Trade from ChatGPT.com, Claude.ai, or the Claude mobile app      | **Remote MCP** (this guide)        |
| Both                                                             | Enable both — they don't interfere |

***

### What you need

1. **OpenAlgo on your own domain with HTTPS.** Dashboard reachable at `https://yourdomain.com`, login + broker auth + orders all working through the web UI. If you're not there yet, start with one of the install scripts: `install/install.sh`, `install/install-multi.sh`, `install/install-docker.sh`, or `install/install-docker-multi-custom-ssl.sh`.
2. **OpenAlgo 2.0.1.0 or later.** The dashboard footer shows the version; `GET https://yourdomain.com/auth/app-info` returns it as JSON. On older builds run `install/update.sh` first.
3. **An OpenAlgo API key.** Generate one at **Profile → API Keys**. The MCP server uses it server-side; hosted clients never see it — they get OAuth tokens instead.
4. **A hosted client account that supports custom MCP connectors.** Check the client's current plan and workspace requirements; these are controlled by the client vendor.

***

### Turn it on

#### Native install (`install.sh`)

The installer asks at run time whether to enable Remote MCP. If you said **yes**, it's already on at `https://yourdomain.com/mcp` — skip to _Connecting_.

If you said no and want to flip it now, edit `/var/python/openalgo/.env`:

```ini
MCP_HTTP_ENABLED = 'True'
MCP_PUBLIC_URL = 'https://yourdomain.com'
```

Then `sudo systemctl restart openalgo`.

#### Multi-domain native (`install-multi.sh`)

Edit the per-deploy `.env` (typically `/var/python/openalgo-flask/<deploy-name>/.env`) with the same two keys, then `sudo systemctl restart openalgo-<deploy-name>`.

#### Docker (`install-docker.sh` / `install-docker-multi-custom-ssl.sh`)

```bash
cd /path/to/openalgo
sudo ./install/enable-remote-mcp-docker.sh
```

The helper picks the stack (or asks if you have several), backs up the bind-mounted `.env`, sets the keys, restarts the container, and probes the OAuth + healthz endpoints. Re-run for each instance.

#### Defaults after enabling

Native installers only turn on `MCP_HTTP_ENABLED` and set `MCP_PUBLIC_URL`. They inherit the current `.sample.env` values: approval is off and write scope is enabled. Review these settings before exposing the service:

```ini
MCP_OAUTH_REQUIRE_APPROVAL = 'True'
MCP_OAUTH_WRITE_SCOPE_ENABLED = 'False'
```

The `enable-remote-mcp-docker.sh` helper applies that stricter posture automatically: new clients require approval and Remote MCP starts read-only. It also preserves the default browser allowlist of `https://claude.ai,https://chatgpt.com`.

Enable `MCP_OAUTH_WRITE_SCOPE_ENABLED=True` only after validating read-only sessions and deciding that hosted clients may place or modify orders.

***

### Connecting & using ChatGPT and Claude

Once it's enabled, your MCP URL is:

```
https://yourdomain.com/mcp
```

With `MCP_OAUTH_REQUIRE_APPROVAL=True`, the first connection pauses until you approve the client at `/admin/remote-mcp`. With approval disabled, registration proceeds immediately; use that setting only on a deliberately restricted deployment.

***

#### Adding OpenAlgo to ChatGPT

> Heads up — ChatGPT recently renamed **Connectors → Apps**. Same feature, new menu name. The in-chat menu still says _Connectors_, so don't be confused.

**Step 1 — Open Apps settings**

1. Avatar (bottom left) → **Settings**
2. Sidebar → **Apps**
3. Top right → **Add more** → opens **New App BETA**

**Step 2 — Fill in the form**

| Field          | Value                                |
| -------------- | ------------------------------------ |
| Name           | `OpenAlgo`                           |
| Description    | `OpenAlgo trading server` (optional) |
| MCP Server URL | `https://yourdomain.com/mcp`         |
| Authentication | `OAuth`                              |

**Step 3 — Advanced OAuth settings**

Expand **Advanced OAuth settings** → **Registration method** → `Dynamic Client Registration (DCR)`.

The notice _"CIMD is unavailable…"_ is expected — OpenAlgo advertises DCR. DCR is the right pick.

Default scopes ChatGPT requests are `read:market read:account`. Add `write:orders` only if you've turned `MCP_OAUTH_WRITE_SCOPE_ENABLED=True` on the server **and** you want this connector to place orders.

**Step 4 — Acknowledge and create**

Tick _"I understand and want to continue"_ under the orange warning, then **Create**.

**Step 5 — Pending approval (when enabled)**

ChatGPT will show:

> OAuth authorization failed: unauthorized\_client

This is expected only when `MCP_OAUTH_REQUIRE_APPROVAL=True`. Your server saw the registration but is holding it until you approve. Don't dismiss the modal.

**Step 6 — Approve in OpenAlgo**

1. New tab → `https://yourdomain.com/admin/remote-mcp`
2. Sign in (TOTP if MCP 2FA is on)
3. **Pending approvals** → verify name + timestamp match → **Approve**

**Step 7 — Complete OAuth**

1. Back in ChatGPT → **Reconnect**
2. A tab pops to `https://yourdomain.com/oauth/authorize?...`
3. Sign in if needed → consent screen lists scopes (verify the redirect URI is a `chatgpt.com` URL) → **Authorize**
4. App moves from Drafts to Enabled

**Step 8 — Use it**

In any new chat, click **+** below the message box → **Connectors** → toggle **OpenAlgo** ON.

Try:

> _"Using OpenAlgo, give me the LTP of RELIANCE on NSE."_

ChatGPT calls `get_quote` and shows the price. With `read:account` granted, also try:

> _"What's my account balance and current open positions?"_

**Client policy and tool availability**

OpenAlgo exposes tools allowed by the granted OAuth scopes. ChatGPT can apply additional product policy, confirmation, plan, and connector restrictions, so the tools visible or executable in a client can differ from the server's `tools/list` response. Verify sensitive operations in Analyzer Mode and do not treat a granted `write:orders` scope as a guarantee that a hosted client will execute every write tool.

**Useful ChatGPT prompts**

* _"Get me the bid-ask spread for INFY and HDFCBANK"_
* _"Summarise my holdings and tell me which are in profit"_
* _"Pull 1-day candles for SBIN for the last 30 days and tell me the trend"_
* _"List my orders from today and show fills vs rejects"_

***

#### Adding OpenAlgo to Claude.ai

**Step 1 — Connectors page**

claude.ai → name (bottom left) → **Settings** → **Connectors**.

**Step 2 — Add custom**

Top right **+** → **Add custom connector**.

**Step 3 — Fill in**

| Field                 | Value                        |
| --------------------- | ---------------------------- |
| Name                  | `OpenAlgo`                   |
| Remote MCP server URL | `https://yourdomain.com/mcp` |

Leave **Advanced settings** alone — OAuth is detected automatically. Click **Add**.

**Step 4 — Pending approval (when enabled)**

When `MCP_OAUTH_REQUIRE_APPROVAL=True`, the first attempt fails with a pending-approval error. Keep the page open. With approval disabled, continue directly to OAuth consent.

**Step 5 — Approve in OpenAlgo**

`https://yourdomain.com/admin/remote-mcp` → **Pending approvals** → **Approve**.

**Step 6 — Complete OAuth**

Back in claude.ai → **Connect** on the connector card → sign in to OpenAlgo (+ TOTP if on) → consent screen (verify redirect URI is `claude.ai`) → **Authorize**. Card switches to **Disconnect** when you're live.

**Step 7 — Tool permissions**

Click your **OpenAlgo** connector to expand permissions:

| Group                                                                  | Recommendation                                                   |
| ---------------------------------------------------------------------- | ---------------------------------------------------------------- |
| Interactive tools (`place_order`, `modify_order`, `cancel_order`, ...) | **Ask me** at first; **Always allow** once you trust the prompts |
| Read-only tools                                                        | **Always allow**                                                 |
| App-only tools                                                         | **Always allow**                                                 |

You can override individual tools — e.g. _Always allow_ most things but force _Ask me_ for `cancel_all_orders`.

**Step 8 — Use it**

In any chat, click the **Tools** icon below the message box → toggle **OpenAlgo** on.

> _"Show me the current LTP of NIFTY 50 and a quick view of my open positions."_

Claude shows expandable tool-call cards. _Ask me_ tools surface a permission prompt with **Allow once / Always allow / Deny**.

**Client policy and tool availability**

OpenAlgo exposes the same scoped registry to Claude.ai, but Claude can apply client-side permissions, plan limits, confirmations, or policy restrictions. Check the connector's current tool list and require confirmation for destructive operations.

**Recommended posture for write tools**

* Start in **Sandbox / Analyzer mode** (`/analyzer`) and dry-run prompts before turning live trading on
* Keep **MCP 2FA** on — fresh authorization for `write:orders` then requires TOTP
* Set a tight `MCP_RATE_LIMIT_WRITE` (e.g. `5 per minute`) so a runaway model can't fire a flurry of orders before you intervene
* Tail `log/mcp.jsonl` while testing — every call recorded with timestamp, scope, outcome, latency
* Keep the **Kill switch** at `/admin/remote-mcp` one click away

**Useful Claude prompts**

* _"Place a limit BUY for 1 share of TCS at ₹3500 in CNC product on NSE"_
* _"Modify my last open INFY order — change the quantity to 5"_
* _"Cancel all my open orders"_
* _"What was my P\&L today?"_

For more example prompts per tool, see the Tool References — the same prompts work on Remote MCP.

***

### Switching scopes after connecting

Already connected with `read:market read:account` and want to add `write:orders`?

1. Set `MCP_OAUTH_WRITE_SCOPE_ENABLED=True` in `.env` and restart
2. **Disconnect** the connector / app in ChatGPT or Claude
3. Re-add it with the broader scope set
4. Re-approve at `/admin/remote-mcp`

OAuth doesn't let an existing token widen its scope — re-consent is required. By design.

***

### Daily operations

#### `/admin/remote-mcp`

| Section                 | What it's for                                                                                               |
| ----------------------- | ----------------------------------------------------------------------------------------------------------- |
| **Pending approvals**   | New clients land here. Approve only ones you recognise — the name is set by the hosted client itself        |
| **Approved clients**    | Currently authorised. Each row shows last-used time                                                         |
| **Revoked clients**     | Historical — cannot re-authorize without admin re-approval                                                  |
| **MCP tool call audit** | Every tool call: timestamp, client, tool, scope, outcome, latency. Filter by tool or outcome                |
| **Kill switch**         | Revokes every refresh token across approved clients. Existing access JWTs remain valid until their short expiry |

#### Audit log

Same data as the admin page, written to `log/mcp.jsonl` as JSON Lines. Tail with:

```bash
tail -f log/mcp.jsonl
```

Tool **arguments are hashed**, not stored verbatim — the log itself is not a data leak.

#### 2FA enforcement

Profile → TOTP → **2FA Enforcement** lets you gate three independent purposes:

| Purpose                  | What it gates                                                   |
| ------------------------ | --------------------------------------------------------------- |
| Dashboard sign-in        | TOTP after password on every login                              |
| Remote MCP authorization | Fresh TOTP at `/oauth/authorize` for every `write:orders` grant |
| Password reset           | Forces TOTP path (no email fallback)                            |

All three default off so existing installs see no change. Saving requires a fresh TOTP code in the same request — proves you have authenticator access for both enabling and disabling.

***

### Configuration reference

All keys live in `.env` (native) or the bind-mounted `.env` (Docker). Native installers set the master switch and public URL; the dedicated Docker helper also applies the stricter approval and write-scope settings described above.

| Key                             | Sample default                          | Purpose                                          |
| ------------------------------- | --------------------------------------- | ------------------------------------------------ |
| `MCP_HTTP_ENABLED`              | `False`                                 | Master switch                                    |
| `MCP_PUBLIC_URL`                | empty; required when enabled            | Public HTTPS origin advertised in OAuth metadata |
| `MCP_OAUTH_REQUIRE_APPROVAL`    | `False`                                 | New clients require admin approval when enabled  |
| `MCP_OAUTH_WRITE_SCOPE_ENABLED` | `True`                                  | Whether `write:orders` is grantable at all       |
| `MCP_HTTP_CORS_ORIGINS`         | `https://claude.ai,https://chatgpt.com` | Browser allowlist                                |
| `MCP_HTTP_IP_ALLOWLIST`         | empty                                   | Optional IP / CIDR allowlist on `/mcp`           |
| `MCP_OAUTH_ACCESS_TTL`          | `900`                                   | Access-token TTL in seconds (max 3600)           |
| `MCP_OAUTH_REFRESH_TTL`         | `2592000`                               | Refresh-token TTL in seconds (30 days)           |
| `MCP_OAUTH_CODE_TTL`            | `60`                                    | Authorization-code TTL (max 300)                 |
| `MCP_RATE_LIMIT_READ`           | `60 per minute`                         | Per-token cap for read scopes                    |
| `MCP_RATE_LIMIT_WRITE`          | `50 per minute`                         | Per-token cap for `write:orders`                 |
| `MCP_LOOPBACK_URL`              | inherits `HOST_SERVER`                  | Override only for unusual topologies             |
| `MCP_OAUTH_KEYS_DIR`            | `keys`                                  | Directory for RS256 signing keys                 |

***

### Security model

The defenses, in plain order:

1. **Optional approval gate** — with `MCP_OAUTH_REQUIRE_APPROVAL=True`, clients cannot complete OAuth until you approve them at `/admin/remote-mcp`
2. **Scope gate** — `write:orders` is invisible in OAuth discovery when `MCP_OAUTH_WRITE_SCOPE_ENABLED=False`
3. **Short access tokens** — 15-minute TTL caps the damage window if a token is stolen
4. **Rate limits** — per-token, separately for reads and writes
5. **PKCE + JWT** — S256-only PKCE, exact redirect\_uri matching, signed access JWTs, and rotating refresh tokens
6. **Refresh-token family protection** — reuse of an already-rotated refresh token revokes its entire token family
7. **Kill switch** — one click revokes all refresh tokens; already-issued access JWTs remain valid until expiry

> **The blast radius is real.** A stolen access token can place orders the broker accepts — they originate from your registered server IP. The 15-minute default TTL limits the window, but the kill switch does not immediately invalidate an access JWT. Never combine `MCP_OAUTH_WRITE_SCOPE_ENABLED=True` with `MCP_OAUTH_REQUIRE_APPROVAL=False` on a public deployment — that lets any internet client register, auto-approve, and request order scope.

For the implementation boundaries behind these controls, see [MCP Architecture](../design/41-mcp-architecture/README.md).

***

### Troubleshooting

| Symptom                                           | Cause                                                  | Fix                                                                               |
| ------------------------------------------------- | ------------------------------------------------------ | --------------------------------------------------------------------------------- |
| `unauthorized_client` after Create / Add          | DCR client not approved yet                            | Approve at `/admin/remote-mcp`                                                    |
| `invalid_client` on retry                         | Client revoked or DB reset; old `client_id` cached     | Disconnect + re-add to force fresh DCR                                            |
| _"Server doesn't implement OAuth"_                | Old build                                              | Update to 2.0.1.0+                                                                |
| _"CIMD is unavailable"_ in ChatGPT                | OpenAlgo advertises DCR, not CIMD                      | Expected — pick **DCR**                                                           |
| Tools missing from chat                           | Connector not toggled on for that chat                 | `+` menu (ChatGPT) or Tools menu (Claude)                                         |
| `bad_arguments` on a tool call                    | Hosted client guessed parameter names                  | Update OpenAlgo (newer builds expose strict tool schemas)                         |
| Sudden 401 on every call                          | Refresh token expired or kill switch fired             | **Reconnect** on the connector                                                    |
| `place_order` blocked on ChatGPT                  | OpenAI's safety policy                                 | Use Claude.ai for order placement                                                 |
| _"Failed to connect to the server"_ on tool calls | Loopback misconfigured                                 | Confirm `HOST_SERVER` in `.env` matches your dashboard URL; restart               |
| Tokens issued but `/mcp` returns 401              | `MCP_PUBLIC_URL` doesn't match the URL the client uses | Make them exactly equal — `https://example.com` ≠ `https://www.example.com`       |
| Form submit blocked by CSP                        | Old build                                              | Update to 2.0.1.0+                                                                |
| Container won't restart after enabler             | Bad `.env` change                                      | Run the rollback one-liner the enabler printed; restart; check `log/errors.jsonl` |

***

### Subdomain mode (advanced)

If you want MCP on a separate hostname (e.g. `mcp.yourdomain.com`) so its cookies, CORS, and TLS lifecycle are isolated from the dashboard, the manual recipe is in `install/Remote-MCP-readme.md`. Same nginx + certbot pattern as `install-docker-multi-custom-ssl.sh`. Most users don't need this — same-domain is what the installer automates.

***

### Disabling

Native:

```bash
sudo sed -i "s|MCP_HTTP_ENABLED.*|MCP_HTTP_ENABLED = 'False'|" /var/python/openalgo/.env
sudo systemctl restart openalgo
```

(`install-multi.sh` users: substitute the per-deploy `.env` and service name.)

Docker:

```bash
sudo sed -i "s|MCP_HTTP_ENABLED.*|MCP_HTTP_ENABLED = 'False'|" /opt/openalgo/<domain>/.env
cd /opt/openalgo/<domain> && sudo docker compose restart
```

OAuth + MCP routes immediately stop responding. Existing tokens hit 404. **Local stdio MCP is unaffected** — it runs over stdin/stdout and doesn't touch the HTTP transport.

For a softer takedown that keeps Remote MCP enabled, visit `/admin/remote-mcp` → **Kill switch**. It revokes refresh tokens, so hosted clients must complete OAuth again after their current access JWT expires. To stop access immediately, disable Remote MCP and restart the application.

***

### Related

* MCP Server Setup Guide — local stdio integration with Claude Desktop / Cursor / Windsurf
* Tool References — every tool with parameters and example prompts (shared across both transports)
* OpenAlgo Symbol Format — how equity / future / option symbols are constructed
* `install/Remote-MCP-readme.md` — operator-focused install + threat model in the source tree
* [MCP Architecture](../design/41-mcp-architecture/README.md) — transport and OAuth implementation boundaries

***



***
