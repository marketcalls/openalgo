# OpenAlgo Security Audit — Consolidated Report

**Date:** 2026-02-19
**Branch:** `algorms`
**Scope:** Full codebase
**Audited by:** 4 parallel deep analysis agents covering Auth/Session, Input Validation/Injection, WebSocket/Network, Broker/Order Security

---

## Executive Summary

After deduplication across all 4 audit streams, **35 unique findings** were identified.

| Severity | Count |
|----------|-------|
| Critical | 5 |
| High | 11 |
| Medium | 13 |
| Low | 6 |

The codebase has strong foundations (Argon2 password hashing, Fernet token encryption, CSRF protection, rate limiting, IP banning, parameterized SQL queries). However, several critical access control gaps, credential exposure issues, and infrastructure misconfigurations need attention before production deployment.

---

## CRITICAL (5)

### C-1: IDOR on Strategy Toggle — Missing Ownership Check

**File:** `blueprints/strategy.py:445-472`

The `/strategy/toggle/<id>` route fetches and toggles a strategy without verifying `session.get("user")` matches `strategy.user_id`. Any authenticated user can toggle another user's strategy. The JSON API counterpart at line 824 correctly checks ownership.

**Impact:** Unauthorized activation/deactivation of other users' trading strategies.

**Fix:** Add `if strategy.user_id != session.get("user"): return jsonify({"status": "error", "message": "Unauthorized"}), 403`

---

### C-2: TOTP Secret Returned in Plaintext via Profile API

**File:** `blueprints/auth.py:792`

The `/auth/profile-data` endpoint returns the raw `totp_secret` (the TOTP seed) in the JSON response. If intercepted (XSS, session hijack, MITM on HTTP), an attacker gains permanent ability to generate valid TOTP codes.

**Impact:** Complete bypass of 2FA, permanent until secret is regenerated.

**Fix:** Remove `totp_secret` from the response. The QR code is sufficient for device enrollment.

---

### C-3: Broker API Key Exposed via `/auth/broker-config`

**File:** `blueprints/auth.py:57-80`

The full `BROKER_API_KEY` from `.env` is returned in plaintext to the browser. This is the actual broker credential.

**Impact:** Any compromised session exposes the broker API key, enabling independent broker API access outside OpenAlgo.

**Fix:** Remove `broker_api_key` from the response entirely. It is only needed server-side for OAuth flows.

---

### C-4: Flask-SocketIO Accepts Connections from Any Origin

**File:** `extensions.py:7`

```python
socketio = SocketIO(cors_allowed_origins="*", ...)
```

Cross-Site WebSocket Hijacking: any website can open a Socket.IO connection inheriting the user's session cookies.

**Impact:** Malicious third-party sites can silently subscribe to market data and query positions on behalf of logged-in users.

**Fix:** Replace with explicit allowed origins:
```python
socketio = SocketIO(
    cors_allowed_origins=os.getenv("SOCKETIO_ALLOWED_ORIGINS", "http://127.0.0.1:5000").split(","),
    ...
)
```

---

### C-5: API Key POST Accepts Arbitrary `user_id` from Request Body

**File:** `blueprints/apikey.py:81-100`

The POST handler takes `user_id` from `request.json` instead of `session["user"]`. Any authenticated user can regenerate another user's API key.

**Impact:** API key takeover — attacker gains the new key and revokes the victim's access.

**Fix:** Use `session["user"]` instead of `request.json.get("user_id")`.

---

## HIGH (11)

### H-1: Hardcoded Static PBKDF2 Salt in Fernet Key Derivation

**File:** `database/auth_db.py:58-65`

```python
salt=b"openalgo_static_salt"  # hardcoded, in source code
```

If `API_KEY_PEPPER` leaks, all encrypted broker tokens across every OpenAlgo deployment using this salt are decryptable offline.

**Fix:** Use a per-deployment random salt stored in `.env` (e.g., `FERNET_SALT`) or database.

---

### H-2: WebSocket Server (Port 8765) Has No Origin Validation

**File:** `websocket_proxy/server.py:153-159, 387-422`

No `origins` parameter on `websockets.serve()`, no IP allowlist. Unauthenticated clients can connect and call `get_supported_brokers` before authenticating.

**Fix:** Add `origins` parameter or `process_request` callback to validate Origin header.

---

### H-3: Hardcoded Secrets in `.sample.env`

**File:** `.sample.env:28, 36`

Real-looking 256-bit hex values for `APP_KEY` and `API_KEY_PEPPER`. No startup check if defaults are unchanged. An operator who copies without reading instructions runs with known secrets.

**Fix:** Replace with `CHANGE_ME_...` placeholders. Add startup validation in `env_check.py` comparing against known sample values.

---

### H-4: ZeroMQ Binds to All Interfaces

**File:** `websocket_proxy/base_adapter.py:203,219` and `connection_manager.py:110,123`

```python
self.socket.bind(f"tcp://*:{port}")  # 0.0.0.0
```

Market data and cache invalidation messages reachable externally with no ZAP/CURVE auth.

**Fix:** Change to `tcp://127.0.0.1:{port}` or `tcp://{ZMQ_BIND_HOST}:{port}`.

---

### H-5: DuckDB SQL Injection via Unvalidated `compression` Parameter

**File:** `database/historify_db.py:2355-2395`
**Entry:** `blueprints/historify.py:440`

```python
compression = data.get("compression", "zstd")  # no validation
# ...
(FORMAT PARQUET, COMPRESSION '{compression}')   # f-string interpolation
```

An attacker could inject `zstd') TO '/etc/passwd' (FORMAT CSV` to write arbitrary files.

**Fix:** Allowlist validation: `if compression not in {"zstd", "snappy", "gzip", "none"}: return error`

---

### H-6: Webhook Endpoints Lack HMAC Signature Verification

**Files:** `blueprints/strategy.py:850`, `blueprints/chartink.py:785`

Only UUID-in-URL authentication. No HMAC signature, no IP allowlist.

**Fix:** Implement per-strategy HMAC-SHA256 signing secret and `X-Signature` header verification.

---

### H-7: No Webhook Replay Protection

**File:** `blueprints/chartink.py:785-944`

No timestamp validation, no nonce, no idempotency key. Same payload can trigger 100 orders/minute within rate limit.

**Fix:** Add timestamp check (reject events >60s old), unique event UUID deduplication, optional `idempotency_key` field.

---

### H-8: Debug Logs Emit Full Broker Tokens and API Secrets

**Files:** `broker/dhan/api/auth_api.py:118`, `broker/fivepaisa/api/auth_api.py:80`

At DEBUG level, full access tokens and the 5Paisa `EncryKey` (broker API secret) are logged. `SensitiveDataFilter` regex doesn't catch f-string interpolated values.

**Fix:** Never log full tokens. Use truncated representations: `token[:8] + "..."`. Add patterns to filter.

---

### H-9: Unrestricted Python Code Upload and Execution

**File:** `blueprints/python_strategy.py:1374-1498`

Any authenticated user can upload and execute arbitrary `.py` files as OS subprocesses. Resource limits applied but no network/file restrictions.

**Fix:** Restrict to admin role. Add code content scanning (AST analysis) to block dangerous imports. Consider sandboxing.

---

### H-10: Freeze Quantity Returns 1 for All Non-NFO Exchanges

**File:** `database/qty_freeze_db.py:178-179`

```python
if exchange not in ["NFO"]:
    return 1  # "to be implemented later"
```

If enforced by future code, a 100-lot BFO order splits into 100 single-lot orders.

**Fix:** Return a high safe default (e.g., 10000) that effectively disables splitting when data is unavailable.

---

### H-11: Missing HSTS, X-Content-Type-Options, X-Frame-Options Headers

**File:** `csp.py:124-170`

No `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, or `X-Frame-Options`. No HTTP→HTTPS redirect.

**Fix:** Add to `get_security_headers()`:
```python
if USE_HTTPS:
    headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
headers["X-Content-Type-Options"] = "nosniff"
headers["X-Frame-Options"] = "SAMEORIGIN"
```

---

## MEDIUM (13)

### M-1: Plaintext API Key in Every Session-Status Response

**File:** `blueprints/auth.py:528-540`

`/auth/session-status` (polled by React SPA) returns the API key. Visible in DevTools, browser extensions, proxy logs.

**Fix:** Only return API key from the dedicated `/apikey` endpoint.

---

### M-2: Webhook Secret in URL Query Parameter (Flow)

**File:** `blueprints/flow.py:391`

Flow's `url` auth mode passes `?secret=...` in URL — leaks via server logs, Referer headers.

**Fix:** Prefer `payload` auth mode. Document URL mode risks.

---

### M-3: Password Reset Token in Redirect URL

**File:** `blueprints/auth.py:313-314`

Token and email in URL query params — visible in server logs and browser history.

**Fix:** Store token in server-side session; don't pass in URL.

---

### M-4: No `MAX_CONTENT_LENGTH`

**File:** `app.py` (absent)

Any endpoint accepts unlimited request bodies — memory exhaustion DoS.

**Fix:** `app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024`

---

### M-5: CORS Disabled Mode Defaults to Wildcard

**File:** `cors.py:16-56`

When `CORS_ENABLED=FALSE`, returns empty dict `{}` → Flask-CORS defaults to allow all origins.

**Fix:** Return `{"origins": []}` to deny all cross-origin requests.

---

### M-6: Rate Limiter Uses In-Memory Storage

**File:** `limiter.py:7`

Bypassed on restart, not shared across processes.

**Fix:** Support configurable Redis backend: `storage_uri=os.getenv("RATE_LIMIT_STORAGE", "memory://")`.

---

### M-7: SocketIO Subscribe Handler Has No Input Size Limit

**File:** `blueprints/websocket_example.py:351-368`

Unbounded `symbols` array enables resource exhaustion.

**Fix:** `symbols = data.get("symbols", [])[:MAX_SYMBOLS_PER_REQUEST]`

---

### M-8: SocketIO Data Handlers Lack Auth Recheck

**File:** `blueprints/websocket_example.py:391-436`

`get_ltp`, `get_quote`, `get_depth` handlers don't re-verify session. Stale connections work after expiry.

**Fix:** Add `get_username_from_session()` check with disconnect on failure.

---

### M-9: Sandbox/Live Mode Toggle Has 1-Hour Stale Cache

**File:** `database/settings_db.py:78-95`

Orders route to wrong destination (live vs sandbox) for up to 1 hour after toggle.

**Fix:** Reduce TTL to 30 seconds or use ZeroMQ cache invalidation bus.

---

### M-10: No Upper Bound on Order Quantity in Schema

**File:** `restx_api/schemas.py:10-12`

`validate.Range(min=1)` only — no max. A compromised key can attempt 10M lot orders.

**Fix:** Add configurable `MAX_ORDER_QUANTITY` validation.

---

### M-11: SMTP Password Uses Weak Key Derivation

**File:** `database/settings_db.py:113-119`

No KDF — simple string truncation. Fallback to `"default-pepper-key"` if env var missing.

**Fix:** Use same PBKDF2 approach as `auth_db.py`. Remove fallback default.

---

### M-12: Chartink `scan_name` Substring Matching Is Ambiguous

**File:** `blueprints/chartink.py:809-829`

`"BUYSELL"` matches BUY branch. No length limit on input.

**Fix:** Use exact matching or strict allowlist. Add max length check.

---

### M-13: Unlimited Search Results

**File:** `database/symbol.py:102`

`enhanced_search_symbols()` has no `LIMIT` clause — returns all matches for broad queries.

**Fix:** Add default limit (200 results) with pagination.

---

## LOW (6)

### L-1: `broker_cache` Uses Plaintext API Key as Dict Key

**File:** `database/auth_db.py:564-578`

Inconsistent with SHA256 pattern used in `verify_api_key` and `auth_cache`.

**Fix:** Use `hashlib.sha256(key.encode()).hexdigest()` as cache key.

---

### L-2: CSRF Can Be Fully Disabled via Env Var

**File:** `app.py:170-171`

`CSRF_ENABLED=FALSE` disables all CSRF protection — production footgun.

**Fix:** Log a warning if disabled. Consider removing the toggle entirely.

---

### L-3: Rate Limiter Keyed by Raw IP (Proxy Bypass)

**File:** `limiter.py:7`

Behind reverse proxy, `request.remote_addr` is the proxy IP — all clients share one bucket.

**Fix:** Use `utils.ip_helper.get_real_ip` as the key function.

---

### L-4: `debugpy` in Runtime Dependencies

**File:** `pyproject.toml:28`

Should be a dev-only dependency.

**Fix:** Move to `[dependency-groups] dev` section.

---

### L-5: CSV Upload Writes to Fixed `/tmp` Path

**File:** `blueprints/admin.py:277`

Race condition and symlink attack on shared systems.

**Fix:** Use `tempfile.NamedTemporaryFile()`.

---

### L-6: Dhan OAuth Callback Logs Full URL with tokenId at INFO Level

**File:** `blueprints/brlogin.py:333-336`

`SensitiveDataFilter` doesn't match `tokenId=` pattern.

**Fix:** Don't log `request.url` for OAuth callbacks. Add `tokenId` to filter patterns.

---

## Positive Security Observations

- **Password hashing**: Argon2id with pepper, auto-rehash on parameter upgrade
- **API key storage**: Dual pattern (Argon2 hash + Fernet encrypt)
- **Timing attack prevention**: `hmac.compare_digest` for webhook secrets
- **CSRF**: Flask-WTF enabled globally with correct `csrf.exempt()` on webhooks/APIs
- **Session cookies**: `HttpOnly`, `SameSite=Lax`, conditional `Secure`, `__Secure-` prefix
- **Rate limiting**: Login (5/min), webhooks (100/min), orders (10/sec)
- **IP banning**: WSGI-level `SecurityMiddleware` blocks before Flask processing
- **SQL injection absent**: All SQLAlchemy ORM queries parameterized (except DuckDB COPY)
- **No unsafe deserialization**: No `pickle`, `yaml.load()`, or `eval()` with user data
- **Path traversal guarded**: `secure_filename()` + `Path.resolve()` in Python strategy module

---

## Top 5 Priority Fixes

1. **C-1 & C-5**: Fix IDOR on strategy toggle and apikey POST — add ownership checks
2. **C-2 & C-3**: Stop returning TOTP secret and broker API key to the browser
3. **C-4**: Change SocketIO CORS from `"*"` to explicit allowed origins
4. **H-1**: Replace static PBKDF2 salt with per-deployment random salt
5. **H-5**: Add allowlist validation for DuckDB compression parameter
