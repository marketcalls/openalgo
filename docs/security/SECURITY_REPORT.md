# OpenAlgo Security Audit Report

Date: 2026-04-08
Commit: c71d875fe2ae6de4bb858d422da911cab4ad77ae
Auditor: Claude Code

## Summary

This audit covered authentication, session management, API security, input validation, broker credential handling (8 brokers), database storage, frontend security, infrastructure/deployment, and dependency analysis across OpenAlgo's 190,000+ lines of Python and TypeScript code. The audit combined manual code review with automated scanning (Bandit, pip-audit, npm audit).

**Single-user context:** OpenAlgo is a single-user self-hosted application. This significantly reduces the threat surface: there are no multi-user privilege escalation attacks, no user-to-user data leakage, and local file/memory access on the server already implies full control. 2 findings were removed as not applicable (VULN-006: user views own TOTP; VULN-011: auto-assign admin is correct when only one user exists) and 12 findings were downgraded because server-local risks (file permissions, log contents, memory dumps) provide no additional attack surface beyond what server access already grants.

The most impactful open findings fall into three categories: (1) **externally exploitable API/OAuth weaknesses** -- API key in URL query params (VULN-007), missing OAuth state validation (VULN-010, VULN-016), API key in localStorage exposed to XSS (VULN-015); (2) **plaintext credential storage** in SQLite -- Samco secret (VULN-008), Telegram bot token (VULN-012), Flow API key (VULN-013) are unencrypted, meaning a stolen backup or DB file exposes broker access without needing the encryption pepper; (3) **MCP server risks** -- API key visible in process list (VULN-017) and unrestricted AI-agent trading without confirmation (VULN-018).

All official install scripts auto-generate unique cryptographic secrets, and the insecure plain-HTTP install script (`ubuntu-ip.sh`) has been deleted.

**Current status:** 2 findings resolved, 2 mitigated, 2 removed (single-user N/A), 47 open. Of the 47 open, 10 are High, 23 are Medium, and 14 are Low.

| Severity | Total | Open | Resolved | Mitigated | Removed |
|----------|-------|------|----------|-----------|---------|
| Critical | 1 | 0 | 1 | 0 | 0 |
| High | 12 | 10 | 1 | 1 | 0 |
| Medium | 23 | 23 | 0 | 0 | 0 |
| Low | 15 | 14 | 0 | 1 | 0 |
| N/A | 2 | 0 | 0 | 0 | 2 |
| **Total** | **53** | **47** | **2** | **2** | **2** |

Note: 2 findings removed as not applicable to single-user architecture.
12 findings downgraded due to single-user context (no multi-user attacks, server access = full control).

### Tracking Status

| VULN | Original | Current | Status | Notes |
|------|----------|---------|--------|-------|
| VULN-001 | Critical | Low | Mitigated | All official install scripts auto-generate unique secrets |
| VULN-003 | Critical | Critical | Resolved | `install/ubuntu-ip.sh` deleted |
| VULN-004 | High | Low | Open | Single-user; requires MITM on TLS to exploit |
| VULN-005 | High | Low | Open | Single-user; user resets own password |
| VULN-006 | High | -- | Removed | Single-user; user views own TOTP secret |
| VULN-007 | High | High | Open | API key in URL query params; externally exploitable |
| VULN-008 | High | High | Open | Samco secret plaintext in DB; defense-in-depth |
| VULN-009 | High | High | Open | Hardcoded fallback encryption key |
| VULN-010 | High | High | Open | OAuth CSRF; externally exploitable |
| VULN-011 | High | -- | Removed | Single-user; only one user exists, auto-assign is correct |
| VULN-012 | High | High | Open | Telegram bot token plaintext in DB |
| VULN-013 | High | High | Open | Flow API key plaintext in DB |
| VULN-014 | High | Medium | Open | Single-user; DB theft already grants password hash access |
| VULN-015 | High | High | Open | API key in localStorage; XSS exploitable externally |
| VULN-016 | High | High | Open | Hardcoded Fyers OAuth state; externally exploitable |
| VULN-017 | High | High | Open | MCP API key in process args |
| VULN-018 | High | High | Open | MCP unrestricted trading; AI agent risk |
| VULN-019 | High | High | Resolved | `install/ubuntu-ip.sh` deleted |
| VULN-020 | High | High | Mitigated | ZMQ not exposed via firewall in install scripts |
| VULN-002 | Critical | Medium | Open | Pepper fallback dead code for install.sh; TELEGRAM_KEY_SALT hardcoded |
| VULN-021 | Medium | Low | Open | Single-user server; memory dump = full server access |
| VULN-022 | Medium | Medium | Open | Static KDF salt |
| VULN-023 | Medium | Medium | Open | CSRF disableable |
| VULN-024 | Medium | Medium | Open | Unbounded basket order list |
| VULN-025 | Medium | Medium | Open | Symbol/strategy field validation |
| VULN-026 | Medium | Medium | Open | SmartOrder position_size range |
| VULN-027 | Medium | Medium | Open | Webhook auth; externally exploitable |
| VULN-028 | Medium | Medium | Open | Error info leak to external callers |
| VULN-029 | Medium | Medium | Open | No request body size limit |
| VULN-030 | Medium | Medium | Open | CORS allows all origins |
| VULN-031 | Medium | Medium | Open | Chartink scan_name validation |
| VULN-032 | Medium | Low | Open | Single-user server; logs on own server |
| VULN-033 | Medium | Low | Open | Single-user server; logs on own server |
| VULN-034 | Medium | Medium | Open | XSS in Dhan OAuth redirect |
| VULN-035 | Medium | Medium | Open | No token expiry detection |
| VULN-036 | Medium | Medium | Open | Unbounded log retention |
| VULN-037 | Medium | Low | Open | Single-user server; typically one OS user |
| VULN-038 | Medium | Medium | Open | DuckDB SQL interpolation |
| VULN-039 | Medium | Low | Open | Single-user server; file access = full control |
| VULN-040 | Medium | Medium | Open | Weak PRNG for OAuth state |
| VULN-041 | Medium | Medium | Open | Open redirect in login |
| VULN-042 | Medium | Medium | Open | CSP connect-src too broad |
| VULN-043 | Medium | Medium | Open | CSP unsafe-inline |
| VULN-044 | Medium | Low | Open | Single-user; can only DoS themselves |
| VULN-045 | Medium | Low | Open | Single-user container; no other users |
| VULN-046 | Medium | Medium | Open | start.sh secrets to /tmp fallback |
| VULN-047 | Medium | Medium | Open | Install script .env permissions |
| VULN-048 | Medium | Medium | Open | HTTP requests without timeout |
| VULN-049 | Low | Low | Open | Redirect URL info leak |
| VULN-050 | Low | Low | Open | CSRF no time limit |
| VULN-051 | Low | Low | Open | Weak PRNG Pocketful |
| VULN-052 | Low | Low | Open | Missing security headers |
| VULN-053 | Low | Low | Open | Vite dev server CVEs |

## Critical Findings

### VULN-003: Install Script Deploys Production Trading Platform Over Plain HTTP Without TLS

Severity: Critical -- **RESOLVED** (ubuntu-ip.sh deleted)
File: install/ubuntu-ip.sh (removed)
CWE: CWE-319

What: The `ubuntu-ip.sh` install script deployed OpenAlgo bound directly to `0.0.0.0:80` over plain HTTP with no TLS, no reverse proxy, and no SSL certificate setup. The `HOST_SERVER` was set to `http://$SERVER_IP`, and the WebSocket URL was set to `ws://$SERVER_IP:8765`. All communication -- including broker API credentials during login, API key authentication, session cookies, trading orders, and market data -- was transmitted in plaintext. The firewall was configured to expose both port 80 and port 8765 to the internet.

Risk: All traffic between the user's browser and the server was transmitted unencrypted. An attacker on the same network or any network hop could intercept broker credentials, API keys, session tokens, and trading commands.

Fix: Script deleted. Users should use `install/install.sh` which includes Nginx reverse proxy and Certbot/SSL setup.

---

## High Findings

### VULN-004: Session Fixation - No Session Regeneration After Login

Severity: Low (single-user app; requires MITM on TLS to exploit)
File: blueprints/auth.py (lines 133-137), utils/auth_utils.py (lines 340-356)
CWE: CWE-384

What: When a user successfully authenticates at the `/auth/login` endpoint, the code sets `session["user"] = username` without regenerating the session ID. Similarly, `handle_auth_success()` in `utils/auth_utils.py` sets `session["logged_in"] = True` and other session keys without calling `session.regenerate()` or clearing and recreating the session. Flask's default server-side session does not automatically regenerate the session cookie upon privilege elevation.

Risk: An attacker who can pre-set or learn a victim's session ID before login (e.g., via a network-level man-in-the-middle on HTTP deployments, or by injecting a session cookie) can hijack the authenticated session after the victim logs in. The attacker's pre-existing session cookie becomes authenticated without the attacker ever knowing the password.

Fix: Clear and regenerate the session immediately after successful authentication. Before setting `session["user"]`, call `session.clear()` then `session.regenerate()` (or manually create a fresh session by clearing and re-populating), ensuring the session ID changes upon login.

---

### VULN-005: Password Reset Token Has No Expiration and Is Stored Only in Session

Severity: Low (single-user app; user resets own password; session theft already grants full access)
File: blueprints/auth.py (lines 218-254, 260-297, 302-332)
CWE: CWE-640

What: Password reset tokens (generated via `secrets.token_urlsafe(32)`) are stored in the Flask session (`session["reset_token"]`) with no explicit expiration. The token remains valid for as long as the session exists, which can be up to the next 3:00 AM IST (potentially 24+ hours). Furthermore, when using the email-based reset flow, the reset link embeds the token in the URL, but validation only checks `session.get("reset_token")` -- meaning the reset link only works in the same browser session that requested it, which is a usability problem, and the token persists indefinitely within that session.

Risk: A password reset token obtained through any session leak (e.g., XSS, shared computer, session cookie theft) can be replayed hours later. There is no time-bound invalidation, and the token is not single-use since it persists in the session even after inspection via the email link route (`reset_password_email`) -- it is only cleared after the password is actually changed.

Fix: Add a timestamp to the reset token (`session["reset_token_created"]`) and enforce a short expiration window (e.g., 15 minutes). Validate the timestamp in the `step == "password"` handler. Additionally, invalidate the token immediately after successful password change (already done) and also on any failed attempt.

---

### VULN-007: API Key Exposed in URL Query Parameters Across Multiple Endpoints

Severity: High
File: restx_api/chart_api.py (line 37), restx_api/instruments.py (line 55), restx_api/ticker.py (line 156), restx_api/telegram_bot.py (lines 113, 356, 542, 573)
CWE: CWE-598

What: Multiple endpoints accept the API key via URL query parameter (`request.args.get("apikey")`). The chart GET endpoint, instruments GET endpoint, ticker GET endpoint, and several Telegram bot endpoints all read `apikey` from the query string. URL query parameters are logged in web server access logs, browser history, proxy logs, CDN logs, and HTTP Referer headers. Since the API key grants full trading authority (place orders, cancel orders, close positions), this exposure in logs creates a persistent credential leakage risk.

Risk: An attacker who gains access to any system that logs HTTP requests (web server logs, reverse proxy logs, load balancer logs, browser history, or network monitoring tools) can extract valid API keys and execute unauthorized trades on real brokerage accounts. This is especially severe because OpenAlgo is typically deployed behind reverse proxies like nginx which log full request URLs by default.

Fix: Move API key authentication to the `X-API-KEY` request header for all GET endpoints. For endpoints that must remain GET (like TradingView chart integration), use a short-lived session token instead of the raw API key. At minimum, add documentation warning users about the URL-logged credential risk and configure server-side log redaction.

---

### VULN-008: Samco Secret API Key Stored in Plaintext in Database

Severity: High
File: database/auth_db.py (lines 156, 751-767)
CWE: CWE-312

What: The Samco broker's permanent secret API key is stored unencrypted in the `secret_api_key` column of the `auth` table. The `samco_save_secret_key()` function at line 766 directly assigns the plaintext value `record.secret_api_key = secret_api_key` without calling `encrypt_token()`, even though the same file implements Fernet encryption for auth tokens and API keys. This secret key is a permanent credential used daily to generate access tokens for trading.

Risk: If an attacker gains read access to the SQLite database file `db/openalgo.db` (via backup exposure, directory traversal, or local file access), they obtain the permanent Samco secret API key in cleartext. Combined with the user ID and password (stored in `.env`), this provides persistent access to the Samco trading account. Unlike session tokens that expire daily, this secret key is permanent and does not rotate.

Fix: Encrypt the secret API key before storage using the existing `encrypt_token()` function, and decrypt it on retrieval using `decrypt_token()`. In `samco_save_secret_key()`, change `record.secret_api_key = secret_api_key` to `record.secret_api_key = encrypt_token(secret_api_key)`. In `samco_get_secret_key()`, change `return record.secret_api_key` to `return decrypt_token(record.secret_api_key)`.

---

### VULN-009: SMTP Encryption Uses Hardcoded Fallback Key "default-pepper-key"

Severity: High
File: database/settings_db.py (line 117)
CWE: CWE-798

What: The `_get_encryption_key()` function used to encrypt SMTP passwords falls back to the hardcoded string `"default-pepper-key"` when the `API_KEY_PEPPER` environment variable is not set: `pepper = os.getenv("API_KEY_PEPPER", "default-pepper-key")`. While `auth_db.py` correctly fails fast if the pepper is missing (lines 41-51), `settings_db.py` silently falls back to a publicly visible default. Additionally, the key derivation at line 119 uses `pepper.ljust(32)[:32]` (simple padding/truncation) instead of a proper KDF like PBKDF2, making it trivially reversible.

Risk: If the `API_KEY_PEPPER` environment variable is absent or fails to load for the settings module, all SMTP passwords are encrypted with a key derivable from the publicly known string `"default-pepper-key"`. An attacker with access to the database can decrypt SMTP credentials, potentially gaining access to the email account used for alerts and OTP delivery.

Fix: Remove the default fallback value and raise an error if `API_KEY_PEPPER` is missing, matching the behavior in `auth_db.py`. Replace the simplistic padding-based key derivation with the same PBKDF2HMAC approach used in `auth_db.py`'s `get_encryption_key()`.

---

### VULN-010: No OAuth State Parameter Validation Across All OAuth Broker Flows (CSRF)

Severity: High
File: blueprints/brlogin.py (lines 580-601, 756-758), broker/pocketful/api/auth_api.py (lines 152-156), frontend/src/pages/BrokerSelect.tsx (lines 186-191)
CWE: CWE-352

What: None of the OAuth broker callback handlers in `brlogin.py` validate the `state` parameter against a server-side stored value. For Pocketful, a state is generated and stored in `localStorage` on the client (line 188 of BrokerSelect.tsx) but is never validated on the server-side callback (line 601 of brlogin.py passes `state` to `auth_function` but `authenticate_broker` ignores it). For all other OAuth brokers (Zerodha, Upstox, Fyers, Flattrade, Zebu, Shoonya), no state parameter is generated or validated at all -- the callback handler on line 757 simply accepts the `code` parameter without any CSRF protection.

Risk: An attacker can craft a malicious OAuth callback URL with a stolen or replayed authorization code and trick an authenticated user into visiting it. This forces the victim's OpenAlgo session to be linked to the attacker's broker account (login CSRF), or allows the attacker to inject their own authorization code into the victim's session. Since this platform handles real money trades, a successful attack could result in unauthorized trading on the wrong account.

Fix: For all OAuth brokers: (1) generate a cryptographically random state using `secrets.token_urlsafe(32)` before redirecting to the broker OAuth page, (2) store it in the Flask session, (3) on callback, compare `request.args.get("state")` against `session.pop("state")` and reject the request if they do not match or if the state is missing.

---

### VULN-012: Telegram Bot Token Stored in Plaintext in Database

Severity: High
File: database/telegram_db.py (line 125)
CWE: CWE-312

What: The `BotConfig.token` column stores the Telegram bot token as plaintext `Text`. While user API keys in the same module are encrypted with Fernet (`encrypted_api_key` column), the bot token itself receives no encryption. The `update_bot_config()` function writes the value directly via `bot_config.token = value` and `get_bot_config()` returns it in plaintext.

Risk: The Telegram bot token grants full control over the bot -- allowing an attacker to impersonate it, read all messages users send to the bot (including commands with sensitive parameters), send arbitrary messages to all registered users, and exfiltrate user-to-bot communications. If the database file is compromised, this token is immediately exploitable.

Fix: Encrypt the bot token before storage using the existing `fernet` instance already initialized in the module, and decrypt on retrieval in `get_bot_config()`.

---

### VULN-013: Flow Workflow Stores API Key in Plaintext

Severity: High
File: database/flow_db.py (lines 73-75, 266-271)
CWE: CWE-312

What: The `FlowWorkflow.api_key` column is a `String(255)` that stores the user's OpenAlgo API key in plaintext. When `activate_workflow()` is called (line 266), the API key is passed through and stored unencrypted via `update_workflow()`. This key is later used for webhook execution.

Risk: The plaintext API key in the `flow_workflows` table has the same privileges as the user's full API key -- it can place orders, cancel orders, and perform all trading operations. Database theft exposes all active workflow API keys, giving an attacker full trading access.

Fix: Import `encrypt_token`/`decrypt_token` from `auth_db` and encrypt the API key before storing in `activate_workflow()`. Decrypt it when reading in `get_workflow()` or at the point of use.

---

### VULN-014: TOTP Secret Stored in Plaintext in User Database

Severity: Medium (single-user app; DB theft already grants ability to modify password hash directly)
File: database/user_db.py (line 67)
CWE: CWE-312

What: The `User.totp_secret` column stores the TOTP seed as a plaintext `String(32)`. This seed is used for password reset functionality (`verify_totp` at line 94, `get_totp_uri` at line 88). No encryption is applied when the secret is created in `add_user()` at line 109 where `pyotp.random_base32()` is written directly.

Risk: If the database is stolen, an attacker possessing the TOTP secret can generate valid TOTP codes at any time, bypassing the second factor entirely. Combined with a brute-forced or phished password, this completely defeats the password reset protection.

Fix: Encrypt `totp_secret` using `encrypt_token()` from `auth_db` before storage, and decrypt when generating TOTP codes or URIs.

---

### VULN-015: API Key Persisted in localStorage via Zustand

Severity: High
File: frontend/src/stores/authStore.ts (lines 24-93), frontend/src/components/auth/AuthSync.tsx (line 41)
CWE: CWE-922

What: The `useAuthStore` uses Zustand's `persist` middleware with `name: 'openalgo-auth'`, which serializes the entire store -- including the `apiKey` field -- into `localStorage`. The `AuthSync` component calls `setApiKey(data.api_key)` on every session sync, writing the plaintext trading API key into `localStorage['openalgo-auth']`. There is no `partialize` option to exclude the key from persistence.

Risk: Any XSS vulnerability (including via browser extensions, injected scripts, or the `'unsafe-inline'` CSP policy) can trivially read `localStorage.getItem('openalgo-auth')` and extract the trading API key. This key grants full order placement, cancellation, and account query capabilities. Unlike session cookies (which have `httpOnly` protection), localStorage is fully accessible to JavaScript.

Fix: Add a `partialize` option to the `persist` config to exclude `apiKey` from localStorage persistence. The API key is already fetched from the server on each page load via `AuthSync`, so persistence is unnecessary.

---

### VULN-016: Hardcoded OAuth State Parameter for Fyers Broker Enables CSRF

Severity: High
File: frontend/src/pages/BrokerSelect.tsx (line 171)
CWE: CWE-352

What: The Fyers OAuth authorization URL uses a hardcoded, static `state` parameter value `2e9b44629ebb28226224d09db3ffb47c`. The OAuth `state` parameter exists specifically to prevent cross-site request forgery during the authorization code flow, and it must be a unique, unpredictable value per session that is validated on the callback.

Risk: An attacker can craft a malicious link that initiates the Fyers OAuth flow with the attacker's authorization code, causing the victim's OpenAlgo instance to authenticate with the attacker's brokerage account. This is a classic OAuth CSRF attack. Since this application handles real financial transactions, an attacker could trick a user into trading on a manipulated account, or intercept the legitimate user's authorization code via a race condition.

Fix: Generate a cryptographically random state per OAuth request using `crypto.randomUUID()`, store it in `sessionStorage`, and validate it on callback.

---

### VULN-017: MCP Server Accepts API Key via Command-Line Argument Visible in Process List

Severity: High
File: mcp/mcpserver.py (lines 9-16)
CWE: CWE-214

What: The MCP server reads the OpenAlgo API key directly from `sys.argv[1]`. When the MCP server is launched, the API key appears as a plaintext argument in the process list (visible via `ps aux`, `/proc/*/cmdline`, or task manager). Any user or process with access to the system's process list can read this key. This API key provides full trading capabilities -- the MCP server exposes tools for placing orders, modifying orders, canceling orders, closing all positions, and accessing account funds.

Risk: On multi-user or shared systems, any local user can harvest the API key from the process table and gain full trading control over the victim's brokerage account, including placing, modifying, and canceling orders with real money.

Fix: Read the API key from an environment variable (`OPENALGO_API_KEY`) or a configuration file with restrictive permissions (0600) instead of command-line arguments. Remove the `sys.argv` approach entirely.

---

### VULN-018: MCP Server Exposes Unrestricted Live Trading Operations Without Confirmation

Severity: High
File: mcp/mcpserver.py (lines 24-461)
CWE: CWE-862

What: The MCP server exposes 30+ tools via the Model Context Protocol, including `place_order`, `place_smart_order`, `place_basket_order`, `place_split_order`, `place_options_order`, `place_options_multi_order`, `modify_order`, `cancel_order`, `cancel_all_orders`, `close_all_positions`, and `analyzer_toggle`. These tools can execute real trades with real money. There is no secondary confirmation mechanism, no rate limiting, no order size validation, and no guard preventing the MCP client (an AI agent) from toggling from analyzer mode to live mode and then placing orders.

Risk: An AI agent interacting through MCP could inadvertently (through prompt injection or hallucination) place large orders, cancel all positions, or switch from paper trading to live trading, resulting in significant financial losses. The lack of any confirmation step or guardrail means a single misinterpreted instruction could trigger irreversible financial transactions.

Fix: Implement a confirmation mechanism for destructive operations (place orders, close positions, toggle analyzer mode). Add configurable order size limits, a configurable allowlist of permitted operations, and require explicit opt-in to live trading mode. Consider making the MCP server read-only by default.

---

### VULN-019: Install Script Exposes WebSocket Port 8765 Directly to the Internet

Severity: High -- **RESOLVED** (ubuntu-ip.sh deleted)
File: install/ubuntu-ip.sh (removed)
CWE: CWE-668

What: The `ubuntu-ip.sh` script explicitly opened port 8765 in the firewall with `sudo ufw allow 8765/tcp`. Combined with the lack of TLS (VULN-003), the WebSocket proxy server was directly exposed to the internet without any transport-layer security.

Risk: The WebSocket port was reachable from the internet without TLS encryption. API keys transmitted during authentication could be intercepted by network observers.

Fix: Script deleted. The `install/install.sh` script proxies WebSocket through Nginx with TLS.

---

### VULN-020: ZeroMQ Publisher Binds to All Interfaces Exposing Internal Message Bus

Severity: High
File: websocket_proxy/base_adapter.py (lines 203, 219)
CWE: CWE-668

What: The `BaseBrokerWebSocketAdapter._bind_to_available_port()` method binds the ZeroMQ PUB socket to `tcp://*:{port}`, which listens on all network interfaces. The install scripts explicitly set `ZMQ_HOST='0.0.0.0'`. The ZeroMQ message bus carries raw market data from broker adapters. The bare-metal installation scripts do not configure firewall rules to block the ZMQ port (typically 5555-5556), leaving it accessible from the network.

Risk: Any host on the network can connect a ZMQ SUB socket to the publisher and receive all raw market data being streamed from the broker. In bare-metal deployments without proper firewall rules, this leaks potentially sensitive real-time trading data. An attacker could also monitor subscriptions and infer trading strategies.

Fix: Change the bind address from `tcp://*:{port}` to `tcp://127.0.0.1:{port}` in `base_adapter.py`. The ZMQ publisher only needs to be reachable from the local WebSocket proxy server. The install scripts should also set `ZMQ_HOST='127.0.0.1'` instead of `0.0.0.0`.

---

## Medium Findings

### VULN-002: Telegram DB Encryption Uses Hardcoded Fallback Pepper and Salt

Severity: Medium (downgraded from Critical -- see deployment note)
File: database/telegram_db.py (lines 57-58)
CWE: CWE-798

What: The `get_encryption_key()` function uses `os.getenv("API_KEY_PEPPER", "default-pepper-change-in-production")` as a fallback. If the environment variable is unset, all Telegram user API keys are encrypted with the publicly known string `"default-pepper-change-in-production"`. The salt is also derived from a configurable environment variable with a weak default: `os.getenv("TELEGRAM_KEY_SALT", "telegram-openalgo-salt")`.

Risk: This is a compound failure: both the pepper and salt have hardcoded defaults. Since the repository is open source, any attacker who obtains the database can decrypt every Telegram user's API key using these known values. Each API key grants full trading access to that user's broker account.

Deployment note: `install/install.sh` auto-generates a unique `API_KEY_PEPPER` via `secrets.token_hex(32)`, so the fallback pepper (`"default-pepper-change-in-production"`) is dead code for install.sh deployments. However, `TELEGRAM_KEY_SALT` is **never set** by install.sh and has no entry in `.sample.env` -- it always falls back to the hardcoded `"telegram-openalgo-salt"` on every deployment. With a unique pepper the derived Fernet key is still unique per deployment, making this a static-salt weakness (same class as VULN-022) rather than a full key compromise. The fallback pepper remains a hygiene risk if any future deployment path omits `API_KEY_PEPPER`.

Fix: Remove the default values for both `API_KEY_PEPPER` and `TELEGRAM_KEY_SALT` and fail fast if they are not set, matching the pattern established in `auth_db.py`. Add `TELEGRAM_KEY_SALT` to `.sample.env` with a placeholder, and generate a unique value in `install/install.sh`.

---

### VULN-021: Plaintext API Key Used as Cache Key in `broker_cache`

Severity: Low (single-user server; memory dump requires server access which already grants full control)
File: database/auth_db.py (lines 589-600)
CWE: CWE-312

What: The `get_broker_name()` function uses the plaintext API key directly as the dictionary key for `broker_cache`: `broker_cache[provided_api_key] = auth_obj.broker`. This contrasts with `verify_api_key()` and `get_auth_token_broker()`, which correctly use `hashlib.sha256(provided_api_key.encode()).hexdigest()` as the cache key. Storing the plaintext API key in an in-memory cache dictionary means the actual API key value is held as a Python string object that could be exposed through memory dumps, debug endpoints, or process inspection.

Risk: If an attacker gains access to the process memory (via a debug endpoint, core dump, or memory disclosure vulnerability), they can extract plaintext API keys from the `broker_cache` dictionary keys. This undermines the otherwise careful hashing approach used elsewhere.

Fix: Change `get_broker_name()` to use a SHA256 hash of the API key as the cache key, consistent with the pattern used in `verify_api_key()` and `get_auth_token_broker()`.

---

### VULN-022: Static Salt in Fernet Key Derivation Reduces KDF Diversity

Severity: Medium
File: database/auth_db.py (lines 58-65)
CWE: CWE-760

What: The `get_encryption_key()` function derives a Fernet encryption key using PBKDF2HMAC with a hardcoded, static salt: `salt=b"openalgo_static_salt"`. This salt is the same across all deployments and is visible in the public source code. The purpose of a salt in a KDF is to ensure that the same password/pepper produces different derived keys across different installations; a static salt defeats this purpose entirely.

Risk: If two deployments use the same `API_KEY_PEPPER` (which is more likely given the hardcoded default in `.sample.env` per VULN-001), their Fernet encryption keys will be identical, enabling cross-deployment token decryption. Even with unique peppers, the static salt means pre-computed rainbow tables for common pepper values can be built once and applied to all OpenAlgo deployments.

Fix: Generate a random salt during initial setup, store it alongside the encrypted data or in the `.env` file as a separate configuration value (e.g., `ENCRYPTION_SALT`). Use this stored salt in the KDF instead of the hardcoded string.

---

### VULN-023: CSRF Protection Is Configurable and Can Be Disabled via Environment Variable

Severity: Medium
File: app.py (lines 279-280), .sample.env (line 235)
CWE: CWE-352

What: CSRF protection is controlled by the `CSRF_ENABLED` environment variable: `csrf_enabled = os.getenv("CSRF_ENABLED", "TRUE").upper() == "TRUE"`. Setting `CSRF_ENABLED=FALSE` in `.env` completely disables CSRF protection for the entire application. While the default is `TRUE`, making a critical security control configurable via an environment variable that any administrator might toggle for "debugging" purposes is risky. There is no warning logged when CSRF is disabled.

Risk: If an administrator sets `CSRF_ENABLED=FALSE` (perhaps during troubleshooting), the entire application becomes vulnerable to CSRF attacks. An attacker could craft malicious pages that submit orders, change passwords, modify settings, or revoke API keys using the victim's authenticated session.

Fix: Log a prominent warning at startup when CSRF is disabled. Consider removing the ability to fully disable CSRF, or at minimum require `FLASK_ENV=development` for CSRF to be disableable. Add a startup log message: "CRITICAL WARNING: CSRF protection is DISABLED. This should never be done in production."

---

### VULN-024: Unbounded Basket Order List Enables Resource Exhaustion

Severity: Medium
File: restx_api/schemas.py (lines 165-167)
CWE: CWE-770

What: The `BasketOrderSchema` defines `orders` as `fields.List(fields.Nested(BasketOrderItemSchema), required=True)` without any `validate=validate.Length(max=...)` constraint. An attacker can submit a basket order request containing thousands or millions of individual orders in a single request. Each order in the list undergoes schema validation, broker module loading, and potentially triggers a real order placement to the broker API. The `OptionsMultiOrderSchema` correctly limits legs to 20, and `MarginCalculatorSchema` limits positions to 50, but `BasketOrderSchema` has no such limit.

Risk: A malicious authenticated user can submit an extremely large basket order (e.g., 100,000 orders) in a single API call. This could exhaust server memory during deserialization, overwhelm the broker API with order submissions, create a denial-of-service condition for the application, and potentially result in massive unintended trading exposure. The rate limiter protects against repeated requests but not against a single oversized request.

Fix: Add `validate=validate.Length(min=1, max=50)` (or a suitable maximum) to the `orders` field in `BasketOrderSchema`, similar to how `OptionsMultiOrderSchema` limits legs and `MarginCalculatorSchema` limits positions.

---

### VULN-025: Symbol and Strategy Fields Lack Length and Character Validation

Severity: Medium
File: restx_api/schemas.py (lines 24-26, 57-59, 89-92, 136, 174)
CWE: CWE-20

What: Across all order schemas (`OrderSchema`, `SmartOrderSchema`, `ModifyOrderSchema`, `BasketOrderItemSchema`, `SplitOrderSchema`), the `symbol` field is defined as `fields.Str(required=True)` with no length constraint or character pattern validation. Similarly, the `strategy` field is `fields.Str(required=True)` without any constraints. An attacker can submit arbitrarily long strings (megabytes) in these fields, or include special characters, newlines, or control characters. These values are passed to broker API modules and logged throughout the system.

Risk: Oversized strings in `symbol` or `strategy` fields can cause log injection (inserting fake log entries via newline characters), excessive memory consumption in downstream processing, unexpected behavior in broker API calls that concatenate these values into URLs or request bodies, and potential database storage issues. While the `MarginPositionSchema` correctly validates `symbol` with `validate.Length(min=1, max=50)`, all order-critical schemas omit this validation.

Fix: Add `validate=validate.Length(min=1, max=50)` and a regex pattern validator (e.g., `validate.Regexp(r'^[A-Za-z0-9_\-:]+$')`) to all `symbol` fields. Add `validate=validate.Length(min=1, max=100)` to all `strategy` fields to prevent oversized payloads.

---

### VULN-026: SmartOrder position_size Has No Range Validation

Severity: Medium
File: restx_api/schemas.py (line 65)
CWE: CWE-20

What: The `SmartOrderSchema` defines `position_size = fields.Float(required=True)` with no range validation whatsoever. This field directly controls the target position size for smart order logic, which determines how many contracts/shares to buy or sell to reach a target position. An attacker can submit extreme values like `position_size=999999999` or `position_size=-999999999`, which the smart order service uses to calculate the order quantity by comparing against the current position. In contrast, all `quantity`, `price`, and `trigger_price` fields in the same schema have explicit `Range` validators.

Risk: An authenticated attacker can submit a smart order with an astronomically large `position_size`, causing the system to calculate and place orders for an extreme quantity of shares or contracts. This could result in massive unintended market exposure, margin violations, or financial loss. The broker may reject such orders, but not all brokers have safety limits, and the order would still be submitted.

Fix: Add `validate=validate.Range(min=-1000000, max=1000000)` (or appropriate bounds based on exchange position limits) to the `position_size` field in `SmartOrderSchema`.

---

### VULN-027: Webhook Endpoints Lack Per-Request Authentication

Severity: Medium
File: blueprints/strategy.py (lines 868-870), blueprints/chartink.py (lines 785-787)
CWE: CWE-306

What: The strategy webhook (`/strategy/webhook/<webhook_id>`) and Chartink webhook (`/chartink/webhook/<webhook_id>`) endpoints rely solely on the UUID `webhook_id` as authentication. There is no HMAC signature verification, no shared secret header check, and no IP whitelist. The webhook_id is a UUID4 which provides 122 bits of entropy, making brute-force impractical, but the UUID is transmitted in the URL and may be exposed through browser history, server logs, Referer headers, or the TradingView/Chartink platform configurations. Once known, anyone can trigger orders.

Risk: If a webhook_id is leaked (through log exposure, misconfigured TradingView alert sharing, screenshots, or SSRF), an attacker can send arbitrary order requests to the webhook endpoint. The webhook directly queues orders with the user's stored API key (retrieved via `get_api_key_for_tradingview`), meaning the attacker does not need to know the API key -- they only need the UUID. The rate limit of 100/minute provides some mitigation but still allows significant unauthorized trading activity.

Fix: Add an optional HMAC signature verification header (e.g., `X-Webhook-Secret`) that users can configure per strategy. Verify the signature against the request body using a shared secret. Additionally, consider adding IP whitelisting support for webhook sources (TradingView publishes their webhook IP ranges).

---

### VULN-028: Error Responses Leak Internal Exception Details

Severity: Medium
File: blueprints/chartink.py (line 944), restx_api/ticker.py (lines 263, 267), restx_api/telegram_bot.py (lines 243, 273)
CWE: CWE-209

What: Multiple endpoints return `str(e)` (the raw Python exception message) directly in HTTP error responses to the client. In `chartink.py` line 944, the webhook error handler returns `jsonify({"status": "error", "error": str(e)})`. In `ticker.py` line 267, broker module errors are returned as `jsonify({"status": "error", "message": str(e)})`. In `telegram_bot.py` lines 243 and 273, bot start/stop errors include `f"Failed to start bot: {str(e)}"`. These exceptions can contain internal file paths, database connection strings, broker API error details, or stack trace fragments.

Risk: An attacker can trigger errors (by sending malformed data or invalid parameters) and collect internal implementation details from the error messages. This information aids in reconnaissance for further attacks -- revealing database types, broker API endpoints, internal module paths, and library versions. This is especially concerning on the publicly-exposed API endpoints that accept external webhook requests.

Fix: Replace all instances of `str(e)` in client-facing error responses with generic messages like `"An unexpected error occurred"`. Log the full exception details server-side using `logger.exception()` (which is already done in most cases) but never expose them to the client.

---

### VULN-029: No Global Request Body Size Limit

Severity: Medium
File: app.py (entire file - absent configuration)
CWE: CWE-400

What: The Flask application does not set `MAX_CONTENT_LENGTH`, which means there is no global limit on the size of incoming request bodies. Flask defaults to accepting unlimited request body sizes. A search of the entire codebase confirms `MAX_CONTENT_LENGTH` is never configured. While individual schemas validate field lengths (e.g., `apikey` max 256 chars), there is no protection against a malicious client sending a multi-gigabyte JSON payload. Flask will attempt to parse the entire body into memory before any schema validation occurs.

Risk: An attacker (authenticated or not, since the body is parsed before API key verification) can send extremely large HTTP request bodies to any API endpoint, consuming server memory and potentially causing an out-of-memory crash. This is a denial-of-service vector. Combined with the unbounded basket order list (VULN-024), a single request could consume gigabytes of memory.

Fix: Set `app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024` (10 MB or appropriate limit) in `app.py` to enforce a global request body size limit. Flask will automatically return a 413 (Request Entity Too Large) response for oversized payloads before attempting to parse them.

---

### VULN-030: CORS Default Allows All Origins When Not Explicitly Configured

Severity: Medium
File: cors.py (lines 16-20, 56)
CWE: CWE-942

What: When `CORS_ENABLED` is not set to `TRUE` (which is the default), the `get_cors_config()` function returns an empty dictionary. This empty config is passed to `CORS(resources={r"/api/*": {}})`. With Flask-CORS, an empty config dictionary means the library uses its defaults, which allows all origins (`*`). Since `CORS_ENABLED` defaults to `FALSE`, a default deployment will have completely open CORS on all `/api/*` endpoints. The SocketIO extension also uses `cors_allowed_origins="*"` (extensions.py line 7).

Risk: Any website can make cross-origin API requests to the OpenAlgo API endpoints. If a user visits a malicious website while logged in or while their API key is accessible, the malicious site can use JavaScript to call trading endpoints (place orders, cancel orders, retrieve account data). While the API key is required in the request body, if the key is stored in the browser (localStorage, cookies), or if the user's browser auto-fills forms, this creates a cross-site request forgery-like attack vector.

Fix: Change the default behavior when `CORS_ENABLED` is `FALSE` to explicitly deny cross-origin requests by returning `{"origins": []}` or a restrictive default. At minimum, add a prominent warning in the setup documentation that CORS must be explicitly configured for production deployments. For SocketIO, replace `cors_allowed_origins="*"` with a configurable value.

---

### VULN-031: Webhook Queues Orders Using Unvalidated Scan Name as Action

Severity: Medium
File: blueprints/chartink.py (lines 808-829)
CWE: CWE-20

What: The Chartink webhook handler determines the trading action (BUY/SELL) by performing substring matching on the `scan_name` field from the incoming webhook payload: `if "BUY" in scan_name` / `elif "SELL" in scan_name`. The `scan_name` is provided by the external Chartink service in the webhook body and is not validated against a predefined set of expected values. If the scan_name contains both "BUY" and "SELL" (e.g., "BUY_THEN_SELL_STRATEGY"), only the first match wins due to if/elif ordering. More critically, anyone who knows the webhook_id can craft a request with any `scan_name` to trigger arbitrary BUY or SELL orders.

Risk: An attacker who obtains the webhook UUID can craft requests with manipulated `scan_name` values to trigger unintended buy or sell orders. The substring matching approach means ambiguous names like "BUYBACK_SELL" would match "BUY" instead of "SELL", potentially causing incorrect trade direction. Combined with the webhook-id-only authentication (VULN-027), this allows full control over trade direction.

Fix: Validate the `scan_name` against a strict allowlist or use exact-match patterns instead of substring matching. Consider requiring the action to be explicitly specified in the webhook payload with validation, rather than inferring it from a free-text scan name.

---

### VULN-032: Broker Auth Tokens and Credentials Logged in Plaintext Across Multiple Brokers

Severity: Low (single-user server; logs stored on user's own server)
File: broker/dhan/api/auth_api.py (line 118), broker/compositedge/api/auth_api.py (lines 38, 92), broker/fyers/api/auth_api.py (line 77), broker/kotak/api/auth_api.py (lines 86, 121, 147), broker/fivepaisaxts/api/auth_api.py (lines 34, 88), broker/iifl/api/auth_api.py (lines 34, 88), broker/ibulls/api/auth_api.py (lines 34, 88), broker/rmoney/api/auth_api.py (line 82)
CWE: CWE-532

What: Multiple broker authentication modules log sensitive credentials to application logs. Dhan logs the full access token at line 118: `logger.debug(f"Access Token obtained: {access_token}")`. Compositedge logs auth and feed tokens at lines 38 and 92. Fyers logs the complete auth API response including access_token and refresh_token at line 77. Kotak logs the full TOTP login response (which contains tokens) at line 86 and the MPIN validation response at line 121. The fivepaisaxts, iifl, ibulls, and rmoney brokers all log auth and feed tokens at `logger.info` level (not just debug). These logs are stored in `db/logs.db`.

Risk: Auth tokens in log files can be harvested by anyone with access to the log database, log aggregation systems, or backup files. Tokens logged at `info` level are particularly dangerous as they appear in normal production logging. A compromised log store gives an attacker valid session tokens for placing trades on the user's broker account.

Fix: Never log raw auth tokens, access tokens, or credentials. Replace all instances with redacted versions (e.g., `token[:8] + "..."` or simply `"[REDACTED]"`). For Fyers line 77, filter sensitive fields from `auth_data` before logging. Change all remaining `logger.info` token logs to not include the token value at all.

---

### VULN-033: Dhan API Secret Prefix Logged at INFO Level

Severity: Low (single-user server; logs stored on user's own server)
File: broker/dhan/api/auth_api.py (lines 42-43)
CWE: CWE-532

What: The `generate_consent()` function logs the first 8 characters of the `BROKER_API_SECRET` at INFO level: `logger.info(f"Using API Secret: {BROKER_API_SECRET[:8] if BROKER_API_SECRET else 'None'}...")`. While only a prefix is logged, this is done at INFO level (not debug), meaning it appears in production logs during every Dhan OAuth authentication attempt. This also logs the API key prefix at the same level (line 41).

Risk: Logging secret prefixes in production reveals enough information to significantly reduce the search space for brute-force attacks against the API secret. Combined with other leaked information, this could help an attacker reconstruct the full secret. The INFO level ensures these appear in all standard log configurations.

Fix: Remove the API secret logging entirely. If debugging is needed, log only that credentials were found (e.g., `logger.debug("API credentials configured: True")`), never any portion of the secret value.

---

### VULN-034: JavaScript Injection via Unescaped URL in Dhan OAuth Redirect Page

Severity: Medium
File: blueprints/brlogin.py (lines 843-855)
CWE: CWE-79

What: The `dhan_initiate_oauth()` function constructs an HTML page with an inline JavaScript redirect using an f-string that directly interpolates the `login_url` variable into a `<script>` tag without escaping: `window.location.href = "{login_url}"`. The `login_url` is constructed from `get_login_url(consent_app_id)` where `consent_app_id` comes from the Dhan API response. If the Dhan API response is compromised (e.g., via man-in-the-middle) or if the consent_app_id contains characters that break out of the JavaScript string context (such as `";alert(1);//`), arbitrary JavaScript could execute in the user's browser.

Risk: While the `consent_app_id` is typically a safe alphanumeric value from Dhan's API, the pattern of injecting server-controlled data into inline JavaScript without escaping is a persistent XSS vector. If the upstream API is compromised or manipulated, this could be used to steal session cookies, redirect to phishing pages, or perform actions on behalf of the authenticated user.

Fix: Replace the inline HTML/JavaScript redirect with a standard Flask `redirect()` call: `return redirect(login_url)`. This eliminates the XSS vector entirely and is the standard pattern used for other broker OAuth redirects in the same file.

---

### VULN-035: No Token Expiry Detection or Refresh Across All Brokers

Severity: Medium
File: database/auth_db.py (lines 143-153, 269-315), broker/*/api/order_api.py (all audited brokers)
CWE: CWE-613

What: The `Auth` database model has no `token_expiry` or `expires_at` column. When tokens are stored via `upsert_auth()`, no expiry time is recorded. The `get_auth_token()` function returns tokens regardless of how old they are, as long as `is_revoked` is False. None of the 8 audited broker order APIs check whether the stored token is still valid before sending it to the broker. While the Fyers auth response includes `expires_in` (auth_api.py line 95), this value is stored in a transient dict but never persisted. Most Indian broker tokens expire daily (at 3 AM IST), but the application has no mechanism to detect or handle this except through broker API error responses.

Risk: Stale tokens are silently used for order placement, leading to failed trades that are only detected after the broker rejects the request. In high-frequency or automated trading scenarios, this can cause cascading failures. The cache TTL is aligned to session expiry time (lines 73-111), but this is a cache expiry optimization, not a token validity check -- a cached stale token is simply replaced with the same stale token from the database.

Fix: Add an `expires_at` column to the `Auth` model. Populate it during `upsert_auth()` based on known broker token lifetimes (or the `expires_in` value from the auth response). In `get_auth_token()`, check `expires_at` before returning the token and return `None` (or trigger re-auth) if expired.

---

### VULN-036: Order Logs and Traffic Logs Accumulate Indefinitely

Severity: Medium
File: database/apilog_db.py (entire file), database/traffic_db.py (lines 45-96)
CWE: CWE-779

What: The `order_logs` table (in `apilog_db.py`) and `traffic_logs` table (in `traffic_db.py`) have no purge, retention, or cleanup mechanism. While `latency_db.py` has `purge_old_data_logs()` and `health_db.py` has `purge_old_metrics()`, both order logs and traffic logs grow without bound. Traffic logs also contain IP addresses and request paths which constitute retained PII without a defined retention policy.

Risk: On an active trading system processing many API calls per day, the unbounded log tables will cause the SQLite database files to grow continuously. This leads to disk exhaustion, degraded query performance, and potential denial of service.

Fix: Add `purge_old_logs(days=30)` functions to both `apilog_db.py` and `traffic_db.py`, similar to the existing pattern in `latency_db.py`. Wire them into the same periodic cleanup schedule used for health metrics and latency data.

---

### VULN-037: No File Permission Enforcement on SQLite Database Files

Severity: Low (single-user server; typically one OS user on the server)
File: database/ (multiple files), db/ (directory)
CWE: CWE-732

What: All database files in the `db/` directory (`openalgo.db`, `logs.db`, `latency.db`, `health.db`, `sandbox.db`, `historify.duckdb`) are created with default OS permissions. No code in the database layer sets restrictive permissions on these files after creation. The `os.makedirs(db_dir, exist_ok=True)` calls create directories with default permissions.

Risk: On a shared Linux server (common deployment), any local user can read the SQLite files, which contain encrypted auth tokens, hashed passwords, API keys, SMTP credentials, Telegram bot tokens, and all order/trading history. Even the encrypted values can be attacked offline since the encryption keys are derived from a single environment variable.

Fix: After creating database files and directories, explicitly set permissions to `0o700` for directories and `0o600` for files. Add a startup check that warns if database files are world-readable.

---

### VULN-038: DuckDB COPY TO Command with String-Interpolated File Path

Severity: Medium
File: database/historify_db.py (lines 2386-2396)
CWE: CWE-89

What: In the `export_to_parquet()` function, when there are no filter parameters, the DuckDB `COPY TO` command is built using f-string interpolation with `abs_output` and `compression` embedded directly into the SQL string. While `abs_output` has path validation (must be in temp directory), the path itself is not sanitized for SQL injection characters like single quotes. The `compression` parameter is a function parameter that could receive arbitrary input.

Risk: If a temp directory path contains a single quote or if the `compression` parameter is ever exposed to user input, an attacker could inject arbitrary DuckDB SQL commands. DuckDB SQL injection could read arbitrary files from the filesystem or write to arbitrary locations.

Fix: Escape single quotes in `abs_output` or validate that it contains only safe characters. Whitelist the `compression` parameter to only accept known values (`zstd`, `snappy`, `gzip`, `none`) at the top of the function.

---

### VULN-039: Strategy Encryption Key Stored as File on Disk

Severity: Low (single-user server; file access already grants full control)
File: database/python_strategy_db.py (key management functions)
CWE: CWE-922

What: The Python strategy encryption key is stored as a file on disk (`db/strategy_encryption.key`). While it is gitignored, there is no file permission enforcement on this key file. The key is used to encrypt/decrypt uploaded Python strategy source code.

Risk: If the key file is readable by other users on the system, they can decrypt all stored Python strategies. Combined with the world-readable database files (VULN-037), this allows extraction of proprietary trading algorithms.

Fix: Set file permissions to `0o600` when creating the key file. Consider deriving the key from `API_KEY_PEPPER` instead of storing a separate key file.

---

### VULN-040: Weak PRNG Used for Pocketful OAuth State Parameter

Severity: Medium
File: frontend/src/pages/BrokerSelect.tsx (lines 65-73)
CWE: CWE-330

What: The `generateRandomState()` function uses `Math.random()` to generate the OAuth state parameter for Pocketful broker authentication. `Math.random()` is not cryptographically secure -- its output can be predicted if an attacker observes a few values, and it has low entropy on some engines.

Risk: A predictable OAuth state parameter weakens the CSRF protection it is meant to provide. An attacker who can predict or brute-force the state value could perform an OAuth CSRF attack against Pocketful broker authentication.

Fix: Replace `Math.random()` with `crypto.randomUUID()` for cryptographically secure state generation.

---

### VULN-041: Server-Controlled Redirect Path Navigated Without Validation

Severity: Medium
File: frontend/src/pages/Login.tsx (lines 119-120, 127)
CWE: CWE-601

What: After login, the frontend calls `navigate(data.redirect)` using the `redirect` field from the server's JSON response without any client-side validation. While the backend currently only returns internal paths like `/setup`, `/broker`, or `/dashboard`, the value comes from a server response that could be manipulated if an attacker performs a man-in-the-middle attack, or if a future backend code change introduces a user-controlled redirect.

Risk: If the `data.redirect` value ever contains a URL like `//evil.com` or `https://evil.com`, the user would be redirected to an attacker-controlled site after a successful login. In the context of a financial application, this could be used for credential phishing.

Fix: Validate that `data.redirect` is a relative path starting with `/` and does not start with `//` before navigating.

---

### VULN-042: CSP connect-src Allows WebSocket Connections to Any Origin

Severity: Medium
File: csp.py (line 43), .sample.env (line 198)
CWE: CWE-942

What: The `connect-src` CSP directive defaults to `'self' wss: ws:` and the sample `.env` files set `CSP_CONNECT_SRC = "'self' wss: ws: https://cdn.socket.io"`. The bare `wss:` and `ws:` scheme-sources allow the application's JavaScript to establish WebSocket connections to any host on the internet, not just the application's own WebSocket server.

Risk: If an XSS vulnerability is exploited (made easier by `'unsafe-inline'` in `script-src`), the attacker's injected script can exfiltrate data -- including the API key from localStorage, session tokens, trading positions, and order data -- over a WebSocket connection to an attacker-controlled server.

Fix: Restrict `connect-src` to only the specific WebSocket origins the application actually needs (e.g., `wss://127.0.0.1:8765`).

---

### VULN-043: CSP script-src Includes 'unsafe-inline' Weakening XSS Protection

Severity: Medium
File: .sample.env (line 186), csp.py (line 28)
CWE: CWE-16

What: The recommended and default CSP configuration includes `'unsafe-inline'` in the `script-src` directive. This was noted as needed for Socket.IO, but it effectively disables the primary XSS mitigation that CSP provides. Any injected inline `<script>` tag or inline event handler will execute without being blocked by CSP.

Risk: The entire purpose of `script-src` in CSP is to prevent inline script execution -- the most common XSS attack vector. With `'unsafe-inline'` present, CSP provides no protection against reflected or stored XSS attacks. Combined with the API key in localStorage (VULN-015) and unrestricted `connect-src` (VULN-042), a single XSS injection could steal trading credentials and exfiltrate them.

Fix: Remove `'unsafe-inline'` from `script-src` and use nonces or hashes instead. Generate a per-request nonce and pass it to both the CSP header and any required inline scripts.

---

### VULN-044: WebSocket Proxy Has No Per-Client Subscription Limit

Severity: Low (single-user; only the user subscribes; stolen API key already grants full trading access)
File: websocket_proxy/server.py (lines 937-1047)
CWE: CWE-770

What: The `subscribe_client` method processes subscription requests without enforcing any limit on the number of symbols a single client can subscribe to. The server iterates over the `symbols` array in the request data and subscribes to each one with no cap on the array size. While the broker adapter has per-connection symbol limits (`MAX_SYMBOLS_PER_WEBSOCKET`), there is no server-side validation preventing a client from sending an arbitrarily large subscription request.

Risk: An authenticated client can subscribe to thousands of symbols in a single request, causing excessive memory consumption, exhausting the broker connection pool, and potentially triggering a denial of service that disrupts real-time market data for active trading strategies.

Fix: Add a per-request and per-client subscription limit check in `subscribe_client` before processing symbols. Reject requests where `len(symbols)` exceeds a configurable maximum.

---

### VULN-045: Dockerfile Sets World-Readable .env File Permissions

Severity: Low (single-user container; no other users inside container)
File: Dockerfile (line 51)
CWE: CWE-732

What: The Dockerfile creates the `.env` file with `chmod 666` permissions, making it readable and writable by any user inside the container. The `.env` file contains highly sensitive secrets including `APP_KEY`, `API_KEY_PEPPER`, `BROKER_API_KEY`, `BROKER_API_SECRET`, and database URLs.

Risk: Any process running inside the container (e.g., a compromised Python strategy script uploaded via the strategies feature) can read the `.env` file containing broker credentials and cryptographic secrets, potentially gaining full access to the user's brokerage account.

Fix: Change the Dockerfile from `chmod 666 /app/.env` to `chmod 600 /app/.env`, ensuring only the `appuser` owner can read and write the file.

---

### VULN-046: start.sh Writes Plaintext Secrets to .env File With Fallback to /tmp

Severity: Medium
File: start.sh (lines 34-140)
CWE: CWE-312

What: When `start.sh` runs in a cloud environment and detects `HOST_SERVER` is set, it writes all sensitive environment variables -- including `BROKER_API_KEY`, `BROKER_API_SECRET`, `APP_KEY`, `API_KEY_PEPPER` -- to a plaintext `.env` file on disk. If the primary write to `/app/.env` fails, it falls back to `/tmp/.env`, which is even more widely accessible.

Risk: Secrets that were previously only in memory (as environment variables) are persisted to disk in plaintext with overly permissive file permissions. The `/tmp/.env` fallback path is particularly dangerous as `/tmp` is typically world-readable.

Fix: Write the `.env` file with `chmod 600` permissions. Remove the `/tmp/.env` fallback -- if the app cannot write to `/app/.env`, it should fail rather than write secrets to a world-readable temp location.

---

### VULN-047: Install Scripts Write Secrets Into .env With Overly Broad File Permissions

Severity: Medium
File: install/install.sh (lines 694-709)
CWE: CWE-538

What: The install scripts write broker API keys and secrets directly into the `.env` file using `sed -i` substitution. The resulting `.env` file permissions are set to 755 applied recursively across the entire installation directory, making the `.env` file containing `BROKER_API_KEY`, `BROKER_API_SECRET`, `APP_KEY`, and `API_KEY_PEPPER` readable by any user on the system.

Risk: On shared hosting environments or systems with multiple users, any local user can read the `.env` file and obtain broker API credentials, enabling unauthorized access to the trading account.

Fix: After writing the `.env` file, set its permissions to `chmod 600` and ensure ownership is restricted to the service user only.

---

### VULN-048: HTTP Requests to Broker APIs Made Without Timeout

Severity: Medium
File: blueprints/chartink.py (lines 92, 128), blueprints/strategy.py (lines 114, 150), broker/aliceblue/streaming/aliceblue_client.py (lines 137, 151, 164, 198, 302), and 24+ additional locations across broker modules
CWE: CWE-400

What: Bandit scan identified 24+ instances of `requests.post()` and `requests.get()` calls without a `timeout` parameter across the codebase. Key locations include the strategy webhook handlers (which make internal API calls to place orders), the Chartink webhook handlers, and multiple broker streaming client implementations. Without a timeout, these HTTP calls will block indefinitely if the remote server does not respond, tying up the server thread.

Risk: If a broker API becomes unresponsive or a network issue occurs, the calling thread will hang indefinitely. In the strategy webhook handlers, this means incoming webhook requests from TradingView will queue up and eventually exhaust the server's thread pool, causing a denial of service for all trading operations. Since these are order-placement requests, hung threads could also prevent time-sensitive orders from being processed.

Fix: Add `timeout=30` (or appropriate value) to all `requests.post()` and `requests.get()` calls. For order-critical paths (strategy/chartink webhooks), use a shorter timeout (e.g., 10 seconds) and handle `requests.Timeout` exceptions gracefully.

---

## Low Findings

### VULN-001: Hardcoded Default SECRET_KEY and Pepper in Sample Environment File

Severity: Low (mitigated by all official install scripts)
File: .sample.env (lines 29, 37)
CWE: CWE-798

What: The `.sample.env` file ships with pre-generated, deterministic values for both `APP_KEY` (`3daa0403ce...`) and `API_KEY_PEPPER` (`a25d94718...`). These are not placeholder strings like `YOUR_BROKER_API_KEY` but fully valid hex secrets. If a user copies `.sample.env` to `.env` without changing these values, the application will start successfully with publicly known secrets. There is no runtime check that `APP_KEY` or `API_KEY_PEPPER` still match the sample defaults.

Risk: Anyone who reads the open-source repository knows both secrets. An attacker can forge Flask session cookies (using the known `APP_KEY`), impersonate any user, and decrypt all stored broker auth tokens and API keys (using the known `API_KEY_PEPPER` via the Fernet KDF). This is a complete authentication bypass for any deployment using the default values.

Deployment note: **All official install scripts** auto-generate unique values for both `APP_KEY` and `API_KEY_PEPPER` and substitute the sample defaults in `.env`:
- `install/install.sh` -- bare metal Linux (`secrets.token_hex(32)`)
- `install/install-docker.sh` -- single Docker instance (`secrets.token_hex(32)`)
- `install/install-docker-multi-custom-ssl.sh` -- multi Docker instance (`secrets.token_hex(32)`)
- `install/install-multi.sh` -- multi bare metal (`secrets.token_hex(32)`)
- `install/docker-run.sh` -- macOS/Linux Docker (`openssl rand -hex 32` with Python fallback)
- `install/docker-run.bat` -- Windows Docker (PowerShell GUID or `secrets.token_hex(32)`)
- `start.sh` -- cloud platforms (reads from platform env vars)

The risk applies only to manual deployments where users run `cp .sample.env .env` without regenerating secrets, bypassing all install scripts.

Fix: Add a startup validation in `utils/env_check.py` that reads the hardcoded sample values and compares them to the loaded `.env` values. If `APP_KEY` or `API_KEY_PEPPER` matches the sample file defaults, refuse to start and print an error instructing the user to generate new values with `secrets.token_hex(32)`.

---

### VULN-049: REDIRECT_URL Leaked to Unauthenticated Users

Severity: Low
File: blueprints/auth.py (lines 86-93)
CWE: CWE-200

What: The `/auth/broker-config` endpoint returns the full `REDIRECT_URL` (e.g., `http://127.0.0.1:5000/zerodha/callback`) to unauthenticated users. While `broker_api_key` is set to `None` for unauthenticated requests, the `redirect_url` field is always populated from the environment variable. The code comments say "return broker name only so the login button is visible" but the implementation also includes the redirect URL.

Risk: The redirect URL reveals the internal server address, port, and broker name to anyone who queries this endpoint without authentication. This is information disclosure that aids reconnaissance. For production deployments behind reverse proxies or with custom domains, it may expose the internal topology.

Fix: Set `redirect_url` to `None` in the unauthenticated response branch, matching the comment's stated intent. Only return the `broker_name` for unauthenticated users.

---

### VULN-050: CSRF Time Limit Defaults to None (No Expiration)

Severity: Low
File: app.py (lines 296-303), .sample.env (lines 239-240)
CWE: CWE-613

What: The CSRF token time limit is configured as: if `CSRF_TIME_LIMIT` is empty or unset, `WTF_CSRF_TIME_LIMIT` is set to `None`, meaning CSRF tokens never expire. The `.sample.env` ships with `CSRF_TIME_LIMIT = ''` (empty), so the default installation has indefinite CSRF tokens. While Flask-WTF ties tokens to the session, tokens that never expire increase the window for token theft and replay.

Risk: A stolen or leaked CSRF token remains valid for the entire duration of the user's session (which can be up to 24 hours until the 3:00 AM IST cutoff). This gives an attacker a wider window to use a captured CSRF token for cross-site request forgery attacks.

Fix: Set a reasonable default CSRF time limit (e.g., 3600 seconds / 1 hour) in the `.sample.env` file instead of leaving it empty. Change the fallback in `app.py` from `None` to a sensible default like `3600`.

---

### VULN-051: Pocketful OAuth State Generated with Non-Cryptographic PRNG

Severity: Low
File: broker/pocketful/api/auth_api.py (lines 153-156), frontend/src/pages/BrokerSelect.tsx (lines 65-73)
CWE: CWE-330

What: Both the server-side and client-side implementations of Pocketful's OAuth state parameter use non-cryptographic random number generators. The server-side uses Python's `random.choices()` (line 156), which is Mersenne Twister and predictable if the seed can be inferred. The client-side uses `Math.random()` (line 69 of BrokerSelect.tsx), which is also not cryptographically secure. The state parameter is meant to prevent CSRF attacks in OAuth flows.

Risk: An attacker who can observe a small number of generated state values may be able to predict future state values due to the weak PRNG, defeating the CSRF protection that the state parameter is intended to provide. This is a lower severity finding since (per VULN-010) the state is not actually validated on the server side, making this issue moot until VULN-021 is fixed.

Fix: On the server side, replace `random.choices()` with `secrets.token_urlsafe(32)`. On the client side, replace `Math.random()` with `crypto.getRandomValues()`. However, fixing VULN-010 (server-side state validation) should be prioritized first, as without validation, the state generation quality is irrelevant.

---

### VULN-052: Missing X-Content-Type-Options and Strict-Transport-Security Headers

Severity: Low
File: csp.py (lines 124-170)
CWE: CWE-693

What: The `get_security_headers()` function in `csp.py` only sets `Referrer-Policy` and `Permissions-Policy` headers. The application does not set `X-Content-Type-Options: nosniff` or `Strict-Transport-Security` (HSTS) anywhere in the codebase. While `frame-ancestors` in CSP covers clickjacking, these other standard security headers are absent.

Risk: Without `X-Content-Type-Options: nosniff`, browsers may MIME-sniff API responses (e.g., JSON containing user-controlled data) and interpret them as HTML, potentially enabling XSS via content-type confusion. Without HSTS, users connecting over HTTP (even temporarily) are vulnerable to SSL stripping attacks, which is critical for a financial application where an attacker on a shared network could intercept trading credentials.

Fix: Add these headers to `get_security_headers()` in `csp.py`: `X-Content-Type-Options: nosniff` unconditionally, and `Strict-Transport-Security: max-age=31536000; includeSubDomains` when `HOST_SERVER` starts with `https://`.

---

### VULN-053: Vite Dev Server Has Known File Read and Path Traversal Vulnerabilities

Severity: Low
File: frontend/package.json (vite 7.0.0 - 7.3.1)
CWE: CWE-22

What: npm audit identified 3 high-severity vulnerabilities in Vite 7.0.0-7.3.1: arbitrary file read via WebSocket (GHSA-p9ff-h696-f583), path traversal in optimized deps `.map` handling (GHSA-4w7w-66w2-5vf9), and `server.fs.deny` bypass with queries (GHSA-v2wj-q39q-566r). These are all in the Vite dev server, which is a devDependency used only during development (not included in production builds).

Risk: These vulnerabilities only affect developers running `npm run dev` locally. An attacker on the same network could read arbitrary files from the developer's machine via the Vite dev server. The production deployment is not affected since Vite is a build tool and its dev server is not deployed.

Fix: Run `cd frontend && npm audit fix` to update Vite to a patched version. While this is dev-only, developers should keep development tools updated to protect their local environments.

---

### Scan Results Summary

**Bandit (Python static analysis)**: 302 issues total. 2 High (both false positives: MD5 for test data generation in sandbox, Flask debug=True in example file). 34 Medium (requests without timeout -- 1 added as VULN-054; bind-all-interfaces and file permissions already covered). 266 Low (mostly try/except/pass patterns in cleanup code -- acceptable in __del__ and shutdown handlers).

**pip-audit (Python dependency vulnerabilities)**: No known vulnerabilities found in any of the 155 pinned dependencies.

**npm audit (Frontend dependency vulnerabilities)**: 1 high-severity package (Vite dev server) with 3 CVEs -- dev-only, added as VULN-055.

**Dependency pinning**: Python dependencies are pinned to exact versions in `pyproject.toml` with `uv.lock` for reproducible builds. Frontend dependencies use semver ranges in `package.json` with `package-lock.json` for lock-file reproducibility.

---

## Recommendations

### Immediate (fix before next release)

- ~~VULN-003: Add TLS requirement or prominent warning to ubuntu-ip.sh install script~~ -- **RESOLVED** (script deleted)
- VULN-009: Remove hardcoded "default-pepper-key" fallback in settings_db.py; fail fast if missing
- VULN-010: Implement OAuth state parameter validation across all broker callback handlers
- VULN-008, VULN-012, VULN-013, VULN-014: Encrypt Samco secret key, Telegram bot token, Flow API key, and TOTP secret at rest using existing encrypt_token()
- VULN-015: Exclude apiKey from Zustand localStorage persistence via partialize option
- VULN-016: Replace hardcoded Fyers OAuth state with crypto.randomUUID()
- VULN-017: Read MCP API key from environment variable instead of sys.argv
- VULN-018: Add confirmation mechanism and operation allowlist to MCP server
- ~~VULN-019: Remove ufw allow 8765/tcp from ubuntu-ip.sh; proxy WebSocket through Nginx~~ -- **RESOLVED** (script deleted)
- VULN-020: Bind ZeroMQ to 127.0.0.1 instead of 0.0.0.0

### Short-term (fix within 2-4 weeks)

**Credential handling:**
- VULN-002: Remove hardcoded fallback pepper/salt in telegram_db.py; fail fast if env vars missing; add TELEGRAM_KEY_SALT to install.sh
- VULN-007: Move API key from URL query parameters to X-API-KEY header for GET endpoints
- VULN-021: Hash API key before using as broker_cache key (consistency fix)
- VULN-022: Replace static KDF salt with per-deployment random salt
- VULN-032, VULN-033: Redact all auth tokens and credentials from log output across all brokers

**Input validation:**
- VULN-024: Add max length to basket order list (validate.Length(max=50))
- VULN-025: Add length and character pattern validation to symbol/strategy fields
- VULN-026: Add range validation to SmartOrder position_size
- VULN-029: Set Flask MAX_CONTENT_LENGTH to 10MB
- VULN-031: Validate Chartink scan_name against allowlist instead of substring matching

**Session and CSRF:**
- VULN-023: Log warning when CSRF is disabled; require FLASK_ENV=development

**Infrastructure:**
- VULN-027: Add optional HMAC signature verification for webhook endpoints
- VULN-030: Default CORS to deny all origins when CORS_ENABLED is FALSE
- VULN-034: Replace inline JavaScript redirect in Dhan OAuth with Flask redirect()
- VULN-037, VULN-039, VULN-045, VULN-046, VULN-047: Set restrictive file permissions (0600) on .env, database files, and encryption key files
- VULN-048: Add timeout parameter to all requests.post/get calls

### Long-term (ongoing improvements)

- VULN-001: Add startup check that refuses to start if APP_KEY or API_KEY_PEPPER matches sample defaults (defense-in-depth for manual deployments)
- VULN-004: Regenerate session ID after successful login (low priority for single-user)
- VULN-005: Add 15-minute expiration to password reset tokens (low priority for single-user)
- VULN-028: Replace str(e) in error responses with generic messages; log details server-side only
- VULN-035: Add token expiry tracking column and proactive re-auth
- VULN-036: Implement log retention policies for order_logs and traffic_logs tables
- VULN-040, VULN-051: Replace Math.random()/random.choices() with cryptographic PRNGs for OAuth state
- VULN-041: Validate server-provided redirect paths on the frontend before navigating
- VULN-042: Restrict CSP connect-src to specific WebSocket origins instead of bare wss:/ws: schemes
- VULN-043: Remove 'unsafe-inline' from CSP script-src; migrate to nonce-based inline scripts
- VULN-044: Add per-client subscription limits to WebSocket proxy
- VULN-052: Add X-Content-Type-Options and Strict-Transport-Security headers
- VULN-038: Parameterize DuckDB COPY TO paths and whitelist compression values
- VULN-049, VULN-050: Set CSRF time limit default to 3600s; restrict redirect_url to authenticated users
- VULN-053: Update Vite to patched version via npm audit fix
