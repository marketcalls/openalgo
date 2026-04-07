# OpenAlgo Security Audit Report

Date: 2026-04-08
Commit: c71d875fe2ae6de4bb858d422da911cab4ad77ae
Auditor: Claude Code

## Summary

[To be filled after all phases]

| Severity | Count |
|----------|-------|
| Critical | 1 |
| High | 4 |
| Medium | 10 |
| Low | 2 |

## Critical Findings

### VULN-001: Hardcoded Default SECRET_KEY and Pepper in Sample Environment File

Severity: Critical
File: .sample.env (lines 29, 37)
CWE: CWE-798

What: The `.sample.env` file ships with pre-generated, deterministic values for both `APP_KEY` (`3daa0403ce...`) and `API_KEY_PEPPER` (`a25d94718...`). These are not placeholder strings like `YOUR_BROKER_API_KEY` but fully valid hex secrets. If a user copies `.sample.env` to `.env` without changing these values (which the setup instructions say to do: `cp .sample.env .env`), the application will start successfully with publicly known secrets. There is no runtime check that `APP_KEY` or `API_KEY_PEPPER` still match the sample defaults.

Risk: Anyone who reads the open-source repository knows both secrets. An attacker can forge Flask session cookies (using the known `APP_KEY`), impersonate any user, and decrypt all stored broker auth tokens and API keys (using the known `API_KEY_PEPPER` via the Fernet KDF). This is a complete authentication bypass for any deployment using the default values.

Fix: Add a startup validation in `utils/env_check.py` that reads the hardcoded sample values and compares them to the loaded `.env` values. If `APP_KEY` or `API_KEY_PEPPER` matches the sample file defaults, refuse to start and print an error instructing the user to generate new values with `secrets.token_hex(32)`.

---

## High Findings

### VULN-002: Session Fixation - No Session Regeneration After Login

Severity: High
File: blueprints/auth.py (lines 133-137), utils/auth_utils.py (lines 340-356)
CWE: CWE-384

What: When a user successfully authenticates at the `/auth/login` endpoint, the code sets `session["user"] = username` without regenerating the session ID. Similarly, `handle_auth_success()` in `utils/auth_utils.py` sets `session["logged_in"] = True` and other session keys without calling `session.regenerate()` or clearing and recreating the session. Flask's default server-side session does not automatically regenerate the session cookie upon privilege elevation.

Risk: An attacker who can pre-set or learn a victim's session ID before login (e.g., via a network-level man-in-the-middle on HTTP deployments, or by injecting a session cookie) can hijack the authenticated session after the victim logs in. The attacker's pre-existing session cookie becomes authenticated without the attacker ever knowing the password.

Fix: Clear and regenerate the session immediately after successful authentication. Before setting `session["user"]`, call `session.clear()` then `session.regenerate()` (or manually create a fresh session by clearing and re-populating), ensuring the session ID changes upon login.

---

### VULN-003: Password Reset Token Has No Expiration and Is Stored Only in Session

Severity: High
File: blueprints/auth.py (lines 218-254, 260-297, 302-332)
CWE: CWE-640

What: Password reset tokens (generated via `secrets.token_urlsafe(32)`) are stored in the Flask session (`session["reset_token"]`) with no explicit expiration. The token remains valid for as long as the session exists, which can be up to the next 3:00 AM IST (potentially 24+ hours). Furthermore, when using the email-based reset flow, the reset link embeds the token in the URL, but validation only checks `session.get("reset_token")` -- meaning the reset link only works in the same browser session that requested it, which is a usability problem, and the token persists indefinitely within that session.

Risk: A password reset token obtained through any session leak (e.g., XSS, shared computer, session cookie theft) can be replayed hours later. There is no time-bound invalidation, and the token is not single-use since it persists in the session even after inspection via the email link route (`reset_password_email`) -- it is only cleared after the password is actually changed.

Fix: Add a timestamp to the reset token (`session["reset_token_created"]`) and enforce a short expiration window (e.g., 15 minutes). Validate the timestamp in the `step == "password"` handler. Additionally, invalidate the token immediately after successful password change (already done) and also on any failed attempt.

---

### VULN-004: TOTP Secret Exposed via Profile API Endpoint

Severity: High
File: blueprints/auth.py (lines 805, 816)
CWE: CWE-200

What: The `/auth/profile-data` endpoint returns the raw TOTP secret (`user.totp_secret`) in plaintext as part of the JSON response to any authenticated user. The TOTP secret is the seed from which all TOTP codes are derived. While the QR code is also returned (which encodes the same secret), explicitly returning the raw secret string in an API response increases the attack surface.

Risk: If an attacker gains access to a single authenticated session (via session hijack, XSS, or a compromised browser extension), they can call `/auth/profile-data` and extract the TOTP secret. This allows the attacker to generate valid TOTP codes indefinitely, even after the session is terminated, enabling persistent password reset capability (since TOTP is used for password reset verification).

Fix: Do not return `totp_secret` in the API response. The QR code already contains the provisioning URI. If the user needs to manually enter the secret, mask it or require re-authentication (current password) before displaying it.

---

### VULN-010: API Key Exposed in URL Query Parameters Across Multiple Endpoints

Severity: High
File: restx_api/chart_api.py (line 37), restx_api/instruments.py (line 55), restx_api/ticker.py (line 156), restx_api/telegram_bot.py (lines 113, 356, 542, 573)
CWE: CWE-598

What: Multiple endpoints accept the API key via URL query parameter (`request.args.get("apikey")`). The chart GET endpoint, instruments GET endpoint, ticker GET endpoint, and several Telegram bot endpoints all read `apikey` from the query string. URL query parameters are logged in web server access logs, browser history, proxy logs, CDN logs, and HTTP Referer headers. Since the API key grants full trading authority (place orders, cancel orders, close positions), this exposure in logs creates a persistent credential leakage risk.

Risk: An attacker who gains access to any system that logs HTTP requests (web server logs, reverse proxy logs, load balancer logs, browser history, or network monitoring tools) can extract valid API keys and execute unauthorized trades on real brokerage accounts. This is especially severe because OpenAlgo is typically deployed behind reverse proxies like nginx which log full request URLs by default.

Fix: Move API key authentication to the `X-API-KEY` request header for all GET endpoints. For endpoints that must remain GET (like TradingView chart integration), use a short-lived session token instead of the raw API key. At minimum, add documentation warning users about the URL-logged credential risk and configure server-side log redaction.

---

## Medium Findings

### VULN-005: Plaintext API Key Used as Cache Key in `broker_cache`

Severity: Medium
File: database/auth_db.py (lines 589-600)
CWE: CWE-312

What: The `get_broker_name()` function uses the plaintext API key directly as the dictionary key for `broker_cache`: `broker_cache[provided_api_key] = auth_obj.broker`. This contrasts with `verify_api_key()` and `get_auth_token_broker()`, which correctly use `hashlib.sha256(provided_api_key.encode()).hexdigest()` as the cache key. Storing the plaintext API key in an in-memory cache dictionary means the actual API key value is held as a Python string object that could be exposed through memory dumps, debug endpoints, or process inspection.

Risk: If an attacker gains access to the process memory (via a debug endpoint, core dump, or memory disclosure vulnerability), they can extract plaintext API keys from the `broker_cache` dictionary keys. This undermines the otherwise careful hashing approach used elsewhere.

Fix: Change `get_broker_name()` to use a SHA256 hash of the API key as the cache key, consistent with the pattern used in `verify_api_key()` and `get_auth_token_broker()`.

---

### VULN-006: Static Salt in Fernet Key Derivation Reduces KDF Diversity

Severity: Medium
File: database/auth_db.py (lines 58-65)
CWE: CWE-760

What: The `get_encryption_key()` function derives a Fernet encryption key using PBKDF2HMAC with a hardcoded, static salt: `salt=b"openalgo_static_salt"`. This salt is the same across all deployments and is visible in the public source code. The purpose of a salt in a KDF is to ensure that the same password/pepper produces different derived keys across different installations; a static salt defeats this purpose entirely.

Risk: If two deployments use the same `API_KEY_PEPPER` (which is more likely given the hardcoded default in `.sample.env` per VULN-001), their Fernet encryption keys will be identical, enabling cross-deployment token decryption. Even with unique peppers, the static salt means pre-computed rainbow tables for common pepper values can be built once and applied to all OpenAlgo deployments.

Fix: Generate a random salt during initial setup, store it alongside the encrypted data or in the `.env` file as a separate configuration value (e.g., `ENCRYPTION_SALT`). Use this stored salt in the KDF instead of the hardcoded string.

---

### VULN-007: CSRF Protection Is Configurable and Can Be Disabled via Environment Variable

Severity: Medium
File: app.py (lines 279-280), .sample.env (line 235)
CWE: CWE-352

What: CSRF protection is controlled by the `CSRF_ENABLED` environment variable: `csrf_enabled = os.getenv("CSRF_ENABLED", "TRUE").upper() == "TRUE"`. Setting `CSRF_ENABLED=FALSE` in `.env` completely disables CSRF protection for the entire application. While the default is `TRUE`, making a critical security control configurable via an environment variable that any administrator might toggle for "debugging" purposes is risky. There is no warning logged when CSRF is disabled.

Risk: If an administrator sets `CSRF_ENABLED=FALSE` (perhaps during troubleshooting), the entire application becomes vulnerable to CSRF attacks. An attacker could craft malicious pages that submit orders, change passwords, modify settings, or revoke API keys using the victim's authenticated session.

Fix: Log a prominent warning at startup when CSRF is disabled. Consider removing the ability to fully disable CSRF, or at minimum require `FLASK_ENV=development` for CSRF to be disableable. Add a startup log message: "CRITICAL WARNING: CSRF protection is DISABLED. This should never be done in production."

---

### VULN-011: Unbounded Basket Order List Enables Resource Exhaustion

Severity: Medium
File: restx_api/schemas.py (lines 165-167)
CWE: CWE-770

What: The `BasketOrderSchema` defines `orders` as `fields.List(fields.Nested(BasketOrderItemSchema), required=True)` without any `validate=validate.Length(max=...)` constraint. An attacker can submit a basket order request containing thousands or millions of individual orders in a single request. Each order in the list undergoes schema validation, broker module loading, and potentially triggers a real order placement to the broker API. The `OptionsMultiOrderSchema` correctly limits legs to 20, and `MarginCalculatorSchema` limits positions to 50, but `BasketOrderSchema` has no such limit.

Risk: A malicious authenticated user can submit an extremely large basket order (e.g., 100,000 orders) in a single API call. This could exhaust server memory during deserialization, overwhelm the broker API with order submissions, create a denial-of-service condition for the application, and potentially result in massive unintended trading exposure. The rate limiter protects against repeated requests but not against a single oversized request.

Fix: Add `validate=validate.Length(min=1, max=50)` (or a suitable maximum) to the `orders` field in `BasketOrderSchema`, similar to how `OptionsMultiOrderSchema` limits legs and `MarginCalculatorSchema` limits positions.

---

### VULN-012: Symbol and Strategy Fields Lack Length and Character Validation

Severity: Medium
File: restx_api/schemas.py (lines 24-26, 57-59, 89-92, 136, 174)
CWE: CWE-20

What: Across all order schemas (`OrderSchema`, `SmartOrderSchema`, `ModifyOrderSchema`, `BasketOrderItemSchema`, `SplitOrderSchema`), the `symbol` field is defined as `fields.Str(required=True)` with no length constraint or character pattern validation. Similarly, the `strategy` field is `fields.Str(required=True)` without any constraints. An attacker can submit arbitrarily long strings (megabytes) in these fields, or include special characters, newlines, or control characters. These values are passed to broker API modules and logged throughout the system.

Risk: Oversized strings in `symbol` or `strategy` fields can cause log injection (inserting fake log entries via newline characters), excessive memory consumption in downstream processing, unexpected behavior in broker API calls that concatenate these values into URLs or request bodies, and potential database storage issues. While the `MarginPositionSchema` correctly validates `symbol` with `validate.Length(min=1, max=50)`, all order-critical schemas omit this validation.

Fix: Add `validate=validate.Length(min=1, max=50)` and a regex pattern validator (e.g., `validate.Regexp(r'^[A-Za-z0-9_\-:]+$')`) to all `symbol` fields. Add `validate=validate.Length(min=1, max=100)` to all `strategy` fields to prevent oversized payloads.

---

### VULN-013: SmartOrder position_size Has No Range Validation

Severity: Medium
File: restx_api/schemas.py (line 65)
CWE: CWE-20

What: The `SmartOrderSchema` defines `position_size = fields.Float(required=True)` with no range validation whatsoever. This field directly controls the target position size for smart order logic, which determines how many contracts/shares to buy or sell to reach a target position. An attacker can submit extreme values like `position_size=999999999` or `position_size=-999999999`, which the smart order service uses to calculate the order quantity by comparing against the current position. In contrast, all `quantity`, `price`, and `trigger_price` fields in the same schema have explicit `Range` validators.

Risk: An authenticated attacker can submit a smart order with an astronomically large `position_size`, causing the system to calculate and place orders for an extreme quantity of shares or contracts. This could result in massive unintended market exposure, margin violations, or financial loss. The broker may reject such orders, but not all brokers have safety limits, and the order would still be submitted.

Fix: Add `validate=validate.Range(min=-1000000, max=1000000)` (or appropriate bounds based on exchange position limits) to the `position_size` field in `SmartOrderSchema`.

---

### VULN-014: Webhook Endpoints Lack Per-Request Authentication

Severity: Medium
File: blueprints/strategy.py (lines 868-870), blueprints/chartink.py (lines 785-787)
CWE: CWE-306

What: The strategy webhook (`/strategy/webhook/<webhook_id>`) and Chartink webhook (`/chartink/webhook/<webhook_id>`) endpoints rely solely on the UUID `webhook_id` as authentication. There is no HMAC signature verification, no shared secret header check, and no IP whitelist. The webhook_id is a UUID4 which provides 122 bits of entropy, making brute-force impractical, but the UUID is transmitted in the URL and may be exposed through browser history, server logs, Referer headers, or the TradingView/Chartink platform configurations. Once known, anyone can trigger orders.

Risk: If a webhook_id is leaked (through log exposure, misconfigured TradingView alert sharing, screenshots, or SSRF), an attacker can send arbitrary order requests to the webhook endpoint. The webhook directly queues orders with the user's stored API key (retrieved via `get_api_key_for_tradingview`), meaning the attacker does not need to know the API key -- they only need the UUID. The rate limit of 100/minute provides some mitigation but still allows significant unauthorized trading activity.

Fix: Add an optional HMAC signature verification header (e.g., `X-Webhook-Secret`) that users can configure per strategy. Verify the signature against the request body using a shared secret. Additionally, consider adding IP whitelisting support for webhook sources (TradingView publishes their webhook IP ranges).

---

### VULN-015: Error Responses Leak Internal Exception Details

Severity: Medium
File: blueprints/chartink.py (line 944), restx_api/ticker.py (lines 263, 267), restx_api/telegram_bot.py (lines 243, 273)
CWE: CWE-209

What: Multiple endpoints return `str(e)` (the raw Python exception message) directly in HTTP error responses to the client. In `chartink.py` line 944, the webhook error handler returns `jsonify({"status": "error", "error": str(e)})`. In `ticker.py` line 267, broker module errors are returned as `jsonify({"status": "error", "message": str(e)})`. In `telegram_bot.py` lines 243 and 273, bot start/stop errors include `f"Failed to start bot: {str(e)}"`. These exceptions can contain internal file paths, database connection strings, broker API error details, or stack trace fragments.

Risk: An attacker can trigger errors (by sending malformed data or invalid parameters) and collect internal implementation details from the error messages. This information aids in reconnaissance for further attacks -- revealing database types, broker API endpoints, internal module paths, and library versions. This is especially concerning on the publicly-exposed API endpoints that accept external webhook requests.

Fix: Replace all instances of `str(e)` in client-facing error responses with generic messages like `"An unexpected error occurred"`. Log the full exception details server-side using `logger.exception()` (which is already done in most cases) but never expose them to the client.

---

### VULN-016: No Global Request Body Size Limit

Severity: Medium
File: app.py (entire file - absent configuration)
CWE: CWE-400

What: The Flask application does not set `MAX_CONTENT_LENGTH`, which means there is no global limit on the size of incoming request bodies. Flask defaults to accepting unlimited request body sizes. A search of the entire codebase confirms `MAX_CONTENT_LENGTH` is never configured. While individual schemas validate field lengths (e.g., `apikey` max 256 chars), there is no protection against a malicious client sending a multi-gigabyte JSON payload. Flask will attempt to parse the entire body into memory before any schema validation occurs.

Risk: An attacker (authenticated or not, since the body is parsed before API key verification) can send extremely large HTTP request bodies to any API endpoint, consuming server memory and potentially causing an out-of-memory crash. This is a denial-of-service vector. Combined with the unbounded basket order list (VULN-011), a single request could consume gigabytes of memory.

Fix: Set `app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024` (10 MB or appropriate limit) in `app.py` to enforce a global request body size limit. Flask will automatically return a 413 (Request Entity Too Large) response for oversized payloads before attempting to parse them.

---

### VULN-017: CORS Default Allows All Origins When Not Explicitly Configured

Severity: Medium
File: cors.py (lines 16-20, 56)
CWE: CWE-942

What: When `CORS_ENABLED` is not set to `TRUE` (which is the default), the `get_cors_config()` function returns an empty dictionary. This empty config is passed to `CORS(resources={r"/api/*": {}})`. With Flask-CORS, an empty config dictionary means the library uses its defaults, which allows all origins (`*`). Since `CORS_ENABLED` defaults to `FALSE`, a default deployment will have completely open CORS on all `/api/*` endpoints. The SocketIO extension also uses `cors_allowed_origins="*"` (extensions.py line 7).

Risk: Any website can make cross-origin API requests to the OpenAlgo API endpoints. If a user visits a malicious website while logged in or while their API key is accessible, the malicious site can use JavaScript to call trading endpoints (place orders, cancel orders, retrieve account data). While the API key is required in the request body, if the key is stored in the browser (localStorage, cookies), or if the user's browser auto-fills forms, this creates a cross-site request forgery-like attack vector.

Fix: Change the default behavior when `CORS_ENABLED` is `FALSE` to explicitly deny cross-origin requests by returning `{"origins": []}` or a restrictive default. At minimum, add a prominent warning in the setup documentation that CORS must be explicitly configured for production deployments. For SocketIO, replace `cors_allowed_origins="*"` with a configurable value.

---

### VULN-018: Webhook Queues Orders Using Unvalidated Scan Name as Action

Severity: Medium
File: blueprints/chartink.py (lines 808-829)
CWE: CWE-20

What: The Chartink webhook handler determines the trading action (BUY/SELL) by performing substring matching on the `scan_name` field from the incoming webhook payload: `if "BUY" in scan_name` / `elif "SELL" in scan_name`. The `scan_name` is provided by the external Chartink service in the webhook body and is not validated against a predefined set of expected values. If the scan_name contains both "BUY" and "SELL" (e.g., "BUY_THEN_SELL_STRATEGY"), only the first match wins due to if/elif ordering. More critically, anyone who knows the webhook_id can craft a request with any `scan_name` to trigger arbitrary BUY or SELL orders.

Risk: An attacker who obtains the webhook UUID can craft requests with manipulated `scan_name` values to trigger unintended buy or sell orders. The substring matching approach means ambiguous names like "BUYBACK_SELL" would match "BUY" instead of "SELL", potentially causing incorrect trade direction. Combined with the webhook-id-only authentication (VULN-014), this allows full control over trade direction.

Fix: Validate the `scan_name` against a strict allowlist or use exact-match patterns instead of substring matching. Consider requiring the action to be explicitly specified in the webhook payload with validation, rather than inferring it from a free-text scan name.

---

## Low Findings

### VULN-008: REDIRECT_URL Leaked to Unauthenticated Users

Severity: Low
File: blueprints/auth.py (lines 86-93)
CWE: CWE-200

What: The `/auth/broker-config` endpoint returns the full `REDIRECT_URL` (e.g., `http://127.0.0.1:5000/zerodha/callback`) to unauthenticated users. While `broker_api_key` is set to `None` for unauthenticated requests, the `redirect_url` field is always populated from the environment variable. The code comments say "return broker name only so the login button is visible" but the implementation also includes the redirect URL.

Risk: The redirect URL reveals the internal server address, port, and broker name to anyone who queries this endpoint without authentication. This is information disclosure that aids reconnaissance. For production deployments behind reverse proxies or with custom domains, it may expose the internal topology.

Fix: Set `redirect_url` to `None` in the unauthenticated response branch, matching the comment's stated intent. Only return the `broker_name` for unauthenticated users.

---

### VULN-009: CSRF Time Limit Defaults to None (No Expiration)

Severity: Low
File: app.py (lines 296-303), .sample.env (lines 239-240)
CWE: CWE-613

What: The CSRF token time limit is configured as: if `CSRF_TIME_LIMIT` is empty or unset, `WTF_CSRF_TIME_LIMIT` is set to `None`, meaning CSRF tokens never expire. The `.sample.env` ships with `CSRF_TIME_LIMIT = ''` (empty), so the default installation has indefinite CSRF tokens. While Flask-WTF ties tokens to the session, tokens that never expire increase the window for token theft and replay.

Risk: A stolen or leaked CSRF token remains valid for the entire duration of the user's session (which can be up to 24 hours until the 3:00 AM IST cutoff). This gives an attacker a wider window to use a captured CSRF token for cross-site request forgery attacks.

Fix: Set a reasonable default CSRF time limit (e.g., 3600 seconds / 1 hour) in the `.sample.env` file instead of leaving it empty. Change the fallback in `app.py` from `None` to a sensible default like `3600`.

---

## Recommendations
