# Remote MCP — Install Guide

> **Status:** opt-in feature shipped on the `remotemcp` branch
> **Default:** off — installs that don't run the enable helper see no
> behavior change, the local stdio MCP keeps working unchanged.

## What this gets you

Once enabled, hosted AI clients (claude.ai, chatgpt.com, claude mobile)
can connect to your OpenAlgo install over HTTPS using OAuth 2.1 with
PKCE. Tools the user authorizes become callable from those clients.

The local stdio MCP (`mcp/mcpserver.py` launched by Claude Desktop /
Cursor / Windsurf) is **completely unaffected** by this feature. Both
transports share the same tool definitions but live in separate code
paths.

See `docs/prd/remote-mcp.md` for the full architecture and threat
model.

---

## Mode 1 — Same-domain (recommended for most users)

This is the path the helper script automates. The MCP and OAuth
endpoints live under your existing OpenAlgo dashboard hostname, e.g.
`https://yourdomain.com/mcp`.

**No nginx changes are needed.** The existing `location /` block in
the install.sh-generated nginx config already proxies every path to
Gunicorn — `/mcp`, `/oauth/*`, and `/.well-known/oauth-*` ride that
same proxy.

### Steps

```bash
# After install/install.sh has completed and your dashboard is
# reachable, run this from the openalgo project root:
sudo ./install/enable-remote-mcp.sh
```

The script:

1. Detects the existing `openalgo-*` systemd service
2. Reads your `.env` to suggest the right public URL
3. Refuses if `FLASK_DEBUG=True` (token leak risk)
4. Backs up your `.env`, then sets:
   - `MCP_HTTP_ENABLED=True`
   - `MCP_PUBLIC_URL=https://yourdomain.com`
   - `MCP_OAUTH_REQUIRE_APPROVAL=True`
   - `MCP_OAUTH_WRITE_SCOPE_ENABLED=False`
5. Ensures `keys/` exists with `chmod 700`
6. Restarts the service (which auto-generates the RS256 signing key)
7. Probes the discovery / JWKS / healthz endpoints to confirm they
   respond

**Total downtime:** one Gunicorn restart (~3 seconds).

### What's NOT enabled by default

- **`write:orders` scope** — the `MCP_OAUTH_WRITE_SCOPE_ENABLED=False`
  default keeps order placement OFF even after the master switch is
  on. MCP starts read-only. Flip the env var only after reading the
  threat-model section below.
- **DCR auto-approval** — `MCP_OAUTH_REQUIRE_APPROVAL=True` means the
  admin must explicitly approve every newly registered MCP client
  before it can complete the OAuth dance.

---

## Mode 2 — Subdomain (defense-in-depth)

If you want the MCP surface on a separate hostname (e.g.
`mcp.yourdomain.com`) so its cookies, CORS, and TLS lifecycle are
isolated from the dashboard, the steps below are the manual recipe.
This is **not** automated — but it's the same pattern as the existing
`install/install-docker-multi-custom-ssl.sh` flow.

### Why bother

- A bug at `/mcp` cannot read dashboard session cookies
  (cookies are scoped to their original domain)
- Tighter, MCP-specific CORS allowlist on the subdomain
- TLS cert lifecycle for MCP can be rotated independently
- Easier to drop just the MCP surface (DNS or nginx) without affecting
  the dashboard

### What you need first

- An A or CNAME record for the MCP hostname pointing at the same
  server as your dashboard
- A working dashboard install via `install/install.sh`

### Steps

1. **Run the same-domain enable first** so the env vars and signing
   key are in place:

   ```bash
   sudo ./install/enable-remote-mcp.sh
   # Use https://mcp.yourdomain.com when prompted for MCP_PUBLIC_URL
   ```

2. **Edit the existing nginx config** (the file written by
   `install.sh`, typically `/etc/nginx/sites-available/yourdomain.com.conf`
   or `/etc/nginx/conf.d/yourdomain.com.conf`). Add a second
   `server { listen 443 ssl; ... }` block for the MCP hostname:

   ```nginx
   server {
       listen 443 ssl;
       listen [::]:443 ssl;
       server_name mcp.yourdomain.com;

       ssl_certificate /etc/letsencrypt/live/mcp.yourdomain.com/fullchain.pem;
       ssl_certificate_key /etc/letsencrypt/live/mcp.yourdomain.com/privkey.pem;
       ssl_protocols TLSv1.2 TLSv1.3;

       # Hardening
       add_header X-Content-Type-Options nosniff;
       add_header Strict-Transport-Security "max-age=63072000" always;
       # No CSP needed — we only serve JSON / SSE here.

       # Only forward the OAuth + MCP paths to Gunicorn. Everything
       # else 404s — keeps the dashboard surface invisible from this
       # hostname.
       location ^~ /.well-known/oauth-authorization-server {
           proxy_pass http://unix:/var/run/openalgo/<DEPLOY_NAME>.sock;
           proxy_set_header Host $host;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
       location ^~ /.well-known/oauth-protected-resource {
           proxy_pass http://unix:/var/run/openalgo/<DEPLOY_NAME>.sock;
           proxy_set_header Host $host;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
       location ^~ /oauth/ {
           proxy_pass http://unix:/var/run/openalgo/<DEPLOY_NAME>.sock;
           proxy_set_header Host $host;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
       location = /mcp {
           proxy_pass http://unix:/var/run/openalgo/<DEPLOY_NAME>.sock;
           proxy_http_version 1.1;
           proxy_buffering off;
           proxy_read_timeout 300s;
           proxy_set_header Host $host;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
       location ^~ /mcp/ {
           proxy_pass http://unix:/var/run/openalgo/<DEPLOY_NAME>.sock;
           proxy_http_version 1.1;
           proxy_buffering off;
           proxy_read_timeout 300s;
           proxy_set_header Host $host;
           proxy_set_header X-Forwarded-Proto $scheme;
       }

       location / { return 404; }
   }
   ```

   Replace `<DEPLOY_NAME>` with the value `install.sh` printed at
   end of run (typically `${DOMAIN/./-}-${BROKER}`).

3. **Issue a cert** for the new hostname:

   ```bash
   sudo certbot --nginx -d mcp.yourdomain.com --non-interactive \
       --agree-tos --email admin@yourdomain.com
   ```

4. **Reload nginx**:

   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```

5. **Verify**:

   ```bash
   curl -s https://mcp.yourdomain.com/.well-known/oauth-authorization-server | jq
   curl -s -o /dev/null -w '%{http_code}\n' https://mcp.yourdomain.com/mcp/healthz
   ```

   The discovery JSON should advertise `mcp.yourdomain.com` URLs (it
   reads `MCP_PUBLIC_URL` from `.env`, which step 1 already set).

---

## Connecting a hosted MCP client (claude.ai)

1. In the client's MCP integration UI, point at:

   ```
   https://yourdomain.com/mcp     (or https://mcp.yourdomain.com/mcp)
   ```

2. The client probes the discovery endpoint, registers itself via DCR,
   and redirects you to OpenAlgo for OAuth approval.

3. **First-time approval gate** — because `MCP_OAUTH_REQUIRE_APPROVAL=True`,
   the new client lands in pending state and the OAuth flow refuses to
   complete until you approve. Until the admin UI for this lands you
   approve via:

   ```bash
   # Lookup the pending client_id
   sqlite3 db/openalgo.db \
       "SELECT client_id, client_name FROM oauth_clients WHERE approved=0;"

   # Approve it
   sqlite3 db/openalgo.db \
       "UPDATE oauth_clients SET approved=1 WHERE client_id='<from-above>';"
   ```

4. Sign in to your OpenAlgo dashboard if prompted, review the scopes,
   and click **Authorize**.

5. The client now has an access token and can call MCP tools. Watch
   `log/mcp.jsonl` to see every tool call audited.

## Operational tips

| Thing | Where |
|---|---|
| Audit log | `log/mcp.jsonl` (one JSON line per tool call) |
| Errors | `log/errors.jsonl` (write-tool pre-execution warnings show up here too) |
| Signing keys | `keys/mcp_oauth_<kid>.pem` (chmod 600) |
| OAuth client list | `sqlite3 db/openalgo.db 'SELECT * FROM oauth_clients'` |
| Active refresh tokens | `sqlite3 db/openalgo.db 'SELECT id, client_id, family_id, revoked_at FROM oauth_refresh_tokens'` |
| Kill switch (revoke everything) | `sqlite3 db/openalgo.db "UPDATE oauth_refresh_tokens SET revoked_at=CURRENT_TIMESTAMP WHERE revoked_at IS NULL"` |

## Threat model summary

(Full details in `docs/prd/remote-mcp.md`.)

| Defense | How |
|---|---|
| Stolen access token → unauthorized order | 15-min TTL; per-token rate limits; pre-write WARNING log; one-click kill switch |
| DCR abuse | Per-IP rate limit + admin approval default |
| Refresh token replay | Single-use rotation + family revocation on reuse |
| PKCE | S256 mandatory, `plain` not advertised |
| Open redirect | Exact `redirect_uri` match |
| CORS exfil | Strict allowlist (default: claude.ai, chatgpt.com) |
| Debug-mode token leak | Pre-flight RuntimeError if `FLASK_DEBUG=True` |
| Compromised signing key | `kid` rotation supported; one-window grace |
| Tool args leaking via logs | Audit log stores SHA-256 hash of args, not args themselves |

## Disabling

```bash
# Edit the .env, set:
#   MCP_HTTP_ENABLED = 'False'
sudo systemctl restart openalgo-<deploy-name>
```

That's it — the OAuth and MCP routes immediately stop responding.
Existing tokens become unreachable. Local stdio MCP is unaffected.
