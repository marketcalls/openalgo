# OpenAlgo — Public IP Security Audit

**Date:** 2026-04-16
**Version audited:** 2.0.0.4 (commit `9e742ee9a`)
**Scope:** Application-layer security for a self-hosted **single-user** deployment where the Flask app (port 5000) and WebSocket proxy (port 8765) are exposed on a **public IP** (common for TradingView / Chartink webhook users).
**Threat model:** Internet-reachable attacker. Broker static-IP whitelisting (SEBI mandate, effective 2026-04-01) blocks stolen credentials from attacker machines, but attacks routed *through* the OpenAlgo server (which owns the registered IP) are still viable.

---

## Executive Summary

OpenAlgo has **solid security fundamentals** — Argon2 password hashing, CSRF enabled with justified exemptions, SQLAlchemy parameterised queries, pinned dependencies, session cookies with `HttpOnly` + `SameSite=Lax`, AES-Fernet encryption for broker tokens, and `SensitiveDataFilter` redaction in logs.

However, when exposed on a public IP, the audit surfaced:

- **5 Critical** findings (WebSocket / ZeroMQ binding, debug-mode RCE risk, API-key leak via URL, session fixation, webhook integrity).
- **6 High** findings (X-Forwarded-For spoofing, timing attack, missing HMAC on webhooks, WS connection flooding, static encryption salt, missing input validation).
- **Systemic rate-limiting gap**: **~65% of authenticated routes have no `@limiter.limit()` decorator**, and the limiter is initialised without `default_limits`, so undecorated routes are effectively unlimited.
- **~44 REST API endpoints** rely on in-handler `apikey` extraction rather than a decorator, so "missing key" is only detected after partial processing.

Phase-1 fixes (login rate reduction, webhook HMAC, WebSocket/ZMQ binding, session rotation, `@require_api_key` decorator, rate-limit gaps on state-changing routes) are all small-to-medium effort and remove the highest-risk internet-exposure vectors.

---

## Part 1 — Application Security Findings

### CRITICAL

#### C1. ~~WebSocket (8765) and ZeroMQ (5555) bind to `0.0.0.0` by default~~ — **FIXED 2026-04-16**
- **Files:** `websocket_proxy/base_adapter.py:192–225`, `websocket_proxy/server.py:392–440`, `.sample.env:65–82`, `start.sh:75–85`, `install/install.sh`, `install/install-multi.sh`, `install/install-docker.sh`, `install/install-docker-multi-custom-ssl.sh`.
- **Original issue:** Defaults exposed both ports to every interface. Deeper finding during remediation: the ZMQ PUB socket in `base_adapter.py` was binding `tcp://*:PORT` regardless of the `ZMQ_HOST` env var, so the var was only honoured by the subscriber and loopback binding was never actually enforced.
- **Impact:** Unauthenticated clients could attach to port 8765 and linger in the client loop indefinitely; anyone reaching 5555 could subscribe to the raw tick feed.
- **Fix applied:**
  - `base_adapter.py`: ZMQ PUB now binds `tcp://{ZMQ_HOST}:{port}` (default `127.0.0.1`) — the env var is actually honoured.
  - `server.py` `handle_client`: unauthenticated clients are closed with code `4401` after `WS_AUTH_GRACE_SECONDS` (default 15 s).
  - `.sample.env`: `ZMQ_HOST='127.0.0.1'` documented as internal-only with explicit warning; `WS_AUTH_GRACE_SECONDS` added.
  - `install/install.sh`, `install/install-multi.sh`: removed the `sed` rewrites that forced `WEBSOCKET_HOST` and `ZMQ_HOST` to `0.0.0.0` — nginx is same-host, loopback suffices.
  - `install/install-docker.sh`, `install/install-docker-multi-custom-ssl.sh`: kept `WEBSOCKET_HOST=0.0.0.0` (Docker port mapping requires it inside the container) but **removed the `ZMQ_HOST` rewrite** — the ZMQ bus is same-container, loopback only.
  - `start.sh` (Railway auto-generated `.env`): kept `WEBSOCKET_HOST=0.0.0.0` (platform proxy requirement); changed `ZMQ_HOST` to `127.0.0.1`.

#### C2. ~~Flask debug mode → Werkzeug console RCE~~ — **FIXED 2026-04-16**
- **Files:** `app.py` (dev-server `__main__` guard), `.sample.env` (warning block above `FLASK_DEBUG`).
- **Original issue:** If a user sets `FLASK_DEBUG=True` in `.env`, the Werkzeug interactive debugger is reachable. With the PIN leaked (debug trace, predictable machine-id), this is **remote code execution**.
- **Fix applied:**
  - `app.py`: Startup guard in the `if __name__ == "__main__"` block hard-refuses to start the dev server when `FLASK_DEBUG` is truthy *and* `FLASK_HOST_IP` is not in `{127.0.0.1, localhost, ::1}`. Prints a red, explicit error explaining the three ways to fix it and exits with status 1. The guard only runs on the dev-server path (`uv run app.py`) — Gunicorn production deployments are unaffected by design.
  - An opt-out knob `FLASK_DEBUG_ALLOW_EXTERNAL=true` exists for users who genuinely need the debugger on a trusted LAN, so the guard is strict but not hostile.
  - `.sample.env`: Loud SECURITY WARNING block above `FLASK_DEBUG` explains the RCE risk and the guard's behaviour.

#### C3. API key acceptable as URL query parameter → leaks to access logs
- **Files:** `restx_api/place_order.py:38`, most endpoints use `data.get("apikey")` from JSON but Flask-RESTX also reads from query args.
- **Issue:** `apikey` in the query string ends up in gunicorn/nginx/CDN access logs, browser `Referer`, shell history.
- **Fix:**
  - Reject keys in `request.args`: `if request.args.get("apikey"): return 400`.
  - Prefer `X-API-KEY` header over body. Document clearly.
  - Ensure gunicorn access-log format strips query strings.

#### C4. No session ID rotation on login → session fixation
- **File:** `blueprints/auth.py:179–244` (after `authenticate_user` returns True at ~line 219)
- **Issue:** `session["user"] = username` is set on the **existing** session cookie. An attacker who pre-seeds a known session cookie in the victim's browser (e.g., subdomain XSS, open Wi-Fi) can hijack the session after the victim logs in.
- **Fix:** Call `session.clear()` + regenerate the session ID **before** populating authenticated state.

#### C5. Webhooks have no HMAC signature verification
- **Files:** `blueprints/chartink.py:787`, `blueprints/strategy.py:~869`, `blueprints/flow.py:596 & 610`
- **Issue:** Authentication is by URL path `<webhook_id>`/`<token>`. That token ends up in strategy config screenshots, support tickets, GitHub issues, and reverse-proxy access logs. Once leaked, anyone can submit orders.
- **Fix:** On strategy creation, also generate a `webhook_secret` (`secrets.token_hex(32)`). Require `X-Signature: sha256=<hmac>` header; verify with `hmac.compare_digest`. Document the secret in Chartink/TradingView configuration guides.

---

### HIGH

#### H1. `X-Forwarded-For` trusted unconditionally → rate-limit bypass
- **Files:** `utils/ip_helper.py`, used throughout `auth.py`, limiter config.
- **Issue:** If the app runs directly on a public IP (no reverse proxy), an attacker can send `X-Forwarded-For: 1.2.3.4` and rotate it per request to bypass per-IP rate limits. `Flask-Limiter`'s `get_remote_address` is safe, but the custom `get_real_ip()` is not.
- **Fix:** Add a `TRUSTED_PROXIES` env var (CIDR list). Only consult forwarded headers when `request.remote_addr` is within that list. Apply `werkzeug.middleware.proxy_fix.ProxyFix` only when configured.

#### H2. API-key verification cache creates a timing oracle
- **File:** `database/auth_db.py:731–806`
- **Issue:** Valid keys are cached post-verify (fast path ≈1 ms), invalid keys hit Argon2 verification (≈50–100 ms). An attacker with any rate budget can distinguish valid vs invalid keys purely on response time.
- **Fix:** Pad responses to a minimum duration (e.g. 80 ms) on both hit and miss paths, or keep the Argon2 call in the hot path and cache only the derived key material, not the "is-valid" decision.

#### H3. WebSocket proxy has no per-client / per-API-key limits
- **File:** `websocket_proxy/server.py:392–427`
- **Issue:** Authenticated clients can open unbounded connections and subscribe to unbounded symbols, exhausting FDs and memory. Subscription floods starve legitimate clients.
- **Fix:** Enforce `MAX_CONNECTIONS_PER_USER` (default 5) and `MAX_SUBSCRIPTIONS_PER_CLIENT` (default 100). Track concurrent connections in a `defaultdict(list)` keyed by `user_id`.

#### H4. Broker-token encryption uses a static KDF salt
- **File:** `database/auth_db.py:56–65`
- **Issue:** `salt=b"openalgo_static_salt"` is identical across every deployment. If `API_KEY_PEPPER` leaks (debug dump, committed `.env`, backup copy), anyone can derive the Fernet key and decrypt all broker tokens — offline, no server access required.
- **Fix:** Generate a random 16-byte salt on first run; persist to `keys/encryption_salt.bin` (chmod 600). Document rotation procedure when pepper is compromised.

#### H5. No strict validation of order quantity / price
- **File:** `restx_api/place_order.py` + `restx_api/schemas.py`
- **Issue:** Marshmallow schemas accept negative quantities and extreme prices. Broker behaviour for negative qty is undefined — may flip side, may error, may silently execute wrong action. Extreme prices can exhaust margin or hit freeze-qty after-the-fact.
- **Fix:** `validate=validate.Range(min=1)` on quantity, `min=0.01` on price/trigger_price. Also enforce freeze-qty server-side before submitting to broker.

#### H6. Historify DuckDB export path validation is TOCTOU-prone
- **File:** `database/historify_db.py:2340–2367`
- **Issue:** `os.path.abspath(output_path).startswith(...)` does not follow symlinks. A malicious symlink inside the temp dir can redirect writes. A crafted race window between validation and file creation can escape.
- **Fix:** `Path(output_path).resolve(strict=False)` and compare against `Path(temp_dir).resolve()`. Open with `O_NOFOLLOW` where the platform supports it.

---

### MEDIUM

#### M1. CSP allows `'unsafe-inline'` for styles
- **File:** `csp.py:28–35`
- **Issue:** Style-only CSP relaxation is low impact (JS CSP is strict), but combined with any HTML-injection bug it lets attackers reshape the UI.
- **Fix:** Move inline styles to class-based styles or use per-response nonces.

#### M2. Password-reset email step leaks existence via response time
- **File:** `blueprints/auth.py:273–299`
- **Issue:** Valid emails write to session (`session["reset_email"] = email`); invalid emails don't. Timing distinguishes the two despite identical response bodies.
- **Fix:** Pad the unsuccessful branch to match the DB-write latency, or run the session write unconditionally on a throwaway key.

#### M3. Health/metrics endpoints are unauthenticated
- **Files:** `blueprints/health.py:256–337` (`/api/current`, `/api/history`, `/api/stats`)
- **Issue:** Expose CPU/memory/WS connection counts/cache size publicly. Useful for reconnaissance and pairing with other findings.
- **Fix:** Add `@check_session_validity`. Keep `/status` and `/check` public for load balancer probes.

---

### INFORMATIONAL (Positive findings)

- ✅ **Password hashing:** Argon2 + pepper.
- ✅ **CSRF:** Enabled by default, exemptions justified and enumerated in `app.py:275–293`.
- ✅ **Session cookies:** `HttpOnly`, `SameSite=Lax`, `Secure` when HTTPS, `__Host-` prefix where applicable.
- ✅ **SQL:** SQLAlchemy ORM throughout; no `f"... {user_input} ..."` SQL strings found.
- ✅ **Dependencies:** Pinned in `pyproject.toml`; pre-commit hooks for secret detection.
- ✅ **Logging:** `SensitiveDataFilter` redacts `api_key`, `apikey`, `token`, `password`, `Authorization` in all three handlers.
- ✅ **File uploads:** `secure_filename()` + path validation.
- ✅ **TOTP 2FA:** Implemented for password reset.
- ✅ **MCP server:** `mcp/mcpserver.py` speaks stdio only — no network listener.

---

## Part 2 — Page / Route Protection & Rate-Limiting Coverage

### 2.1 Flask-Limiter configuration

- **Location:** `limiter.py:7`, init at `app.py:143–144`.
- **Backend:** `memory://` with `moving-window` strategy.
- **Gap:** `limiter.init_app(app)` is called **without `default_limits`** → every route without an explicit `@limiter.limit(...)` is effectively unlimited.

Environment variables (`.env` defaults):

| Variable | Default | Assessment |
|---|---|---|
| `LOGIN_RATE_LIMIT_MIN` | `5 per minute` | Weak — recommend `3 per minute` |
| `LOGIN_RATE_LIMIT_HOUR` | `25 per hour` | Weak — recommend `15 per hour` |
| `RESET_RATE_LIMIT` | `15 per hour` | Adequate |
| `API_RATE_LIMIT` | `50 per second` | Very permissive (180k/hour) |
| `ORDER_RATE_LIMIT` | `10 per second` | High — appropriate for HFT but high for abuse |
| `SMART_ORDER_RATE_LIMIT` | `10 per second` | Same |
| `WEBHOOK_RATE_LIMIT` | `100 per minute` | Moderate |
| `STRATEGY_RATE_LIMIT` | `200 per minute` | High |

### 2.2 Coverage matrix (blueprints)

Counts are **total routes / authenticated / rate-limited**. "Auth" = `@check_session_validity` or equivalent manual check. Rate limit = explicit `@limiter.limit(...)`.

| Blueprint | Routes | Auth | Rate-limited | Missing rate limit |
|---|---:|---:|---:|---:|
| `admin.py` | 22 | 22 | 22 | 0 |
| `analyzer.py` | 6 | 0 | 0 | 6 |
| `apikey.py` | 2 | 2 | 0 | 2 |
| `auth.py` | 21 | 15 | 5 | 16 |
| `brlogin.py` | 8 | 6 | 0 | 8 |
| `broker_credentials.py` | 3 | 3 | 0 | 3 |
| `chartink.py` | 16 | 15 | 1 | 15 |
| `core.py` | 1 | 0 | 0 | 1 |
| `custom_straddle.py` | 3 | 0 | 0 | 3 |
| `dashboard.py` | 1 | 0 | 0 | 1 |
| `flow.py` | 25 | 23 | 2 | 23 |
| `gc_json.py` | 1 | 0 | 0 | 1 |
| `gex.py` | 1 | 0 | 0 | 1 |
| `health.py` | 8 | 2 | 8 | 0 |
| `historify.py` | 27 | 27 | 0 | **27** |
| `ivchart.py` | 3 | 0 | 0 | 3 |
| `ivsmile.py` | 1 | 0 | 0 | 1 |
| `latency.py` | 5 | 5 | 5 | 0 |
| `leverage.py` | 1 | 0 | 0 | 1 |
| `log.py` | 2 | 2 | 2 | 0 |
| `logging.py` | 1 | 1 | 1 | 0 |
| `master_contract_status.py` | 8 | 8 | 0 | **8** |
| `oiprofile.py` | 2 | 0 | 0 | 2 |
| `oitracker.py` | 2 | 0 | 0 | 2 |
| `orders.py` | 18 | 18 | 0 | **18** |
| `platforms.py` | 1 | 0 | 0 | 1 |
| `playground.py` | 4 | 4 | 0 | 4 |
| `pnltracker.py` | 3 | 0 | 0 | 3 |
| `python_strategy.py` | 22 | 22 | 0 | **22** |
| `react_app.py` | 64 | 0 | 0 | 64 (SPA, auth at API) |
| `sandbox.py` | 14 | 14 | 0 | 14 |
| `search.py` | 4 | 0 | 0 | 4 |
| `security.py` | 8 | 8 | 8 | 0 |
| `settings.py` | 2 | 0 | 0 | 2 |
| `straddle_chart.py` | 2 | 0 | 0 | 2 |
| `strategy.py` | 16 | 15 | 1 | 15 |
| `system_permissions.py` | 2 | 0 | 0 | 2 |
| `telegram.py` | 14 | 14 | 0 | **14** |
| `traffic.py` | 4 | 4 | 4 | 0 |
| `tv_json.py` | 1 | 0 | 0 | 1 |
| `vol_surface.py` | 1 | 0 | 0 | 1 |
| `websocket_example.py` | 13 | 13 (manual) | 0 | **13** |
| **Totals (blueprints)** | **~336** | **~280 (83%)** | **~80 (24%)** | **~220 (65%)** |

**REST API (`restx_api/`)**: ~44 endpoints. ~39 have rate limits; API-key auth is **done inside handlers**, not via decorator. 3–5 endpoints missing rate limits.

### 2.3 Critical gaps (state-changing + unlimited)

The following authenticated endpoints are **missing rate limits** and are either expensive, financially sensitive, or exec-control:

| Severity | File:Line | Route | Why it matters |
|---|---|---|---|
| **Critical** | `blueprints/python_strategy.py:1665` | `POST /python/start/<id>` | Spawns a subprocess — unbounded forks |
| **Critical** | `blueprints/python_strategy.py:1772` | `POST /python/stop/<id>` | Kills subprocess — racing stop/start floods |
| **Critical** | `blueprints/auth.py:407` | `GET /auth/reset-password-email/<token>` | Token brute-force; no limit |
| **Critical** | `blueprints/websocket_example.py:96–146` | `/api/websocket/subscribe`, `/unsubscribe`, `/unsubscribe-all` | Subscription bombing |
| **Critical** | `blueprints/master_contract_status.py:111,163` | `/cache/reload`, `/master-contract/download` | 10–60 s expensive ops, broker quota burn |
| **High** | `blueprints/flow.py:596,610` | `/flow/webhook/<token>[/<symbol>]` | Unlimited webhook flood |
| **High** | `blueprints/health.py:256–337` | `/api/current`, `/api/history`, `/api/stats` | Unauth + unlimited metrics disclosure |
| **High** | `blueprints/historify.py:120–1536` | `/api/download`, `/api/export`, `/api/export/bulk`, `/api/upload`, `/api/delete/bulk` | Resource exhaustion on large data ops |
| **High** | `blueprints/orders.py:*` | order/position read routes | No rate limit despite being authenticated |
| **Medium** | `blueprints/strategy.py:775`, `chartink.py:691`, `flow.py:60,127,159` | strategy/workflow CRUD | DB bloat on spam create |
| **Medium** | `blueprints/telegram.py:92,163,202,313` | bot start/stop/broadcast | Messaging spam |
| **Medium** | `blueprints/sandbox.py:*` | analyzer endpoints | 14 routes unlimited |

### 2.4 Recommended rate-limit decorator additions

Add these env vars to `.env` with sensible defaults:

```env
# Tighter login brute-force protection
LOGIN_RATE_LIMIT_MIN=3 per minute
LOGIN_RATE_LIMIT_HOUR=15 per hour

# New per-category limits
RESET_TOKEN_VALIDATE_LIMIT=5 per minute
STRATEGY_EXEC_LIMIT=5 per minute
WEBSOCKET_CONTROL_LIMIT=10 per minute
EXPENSIVE_OP_LIMIT=1 per minute      # master contract download, cache reload
EXPORT_RATE_LIMIT=5 per minute       # historify downloads/exports
TELEGRAM_RATE_LIMIT=10 per minute
ADMIN_WRITE_LIMIT=20 per minute
FILE_UPLOAD_LIMIT=2 per minute
```

And configure a global default so undecorated routes are not wide-open:

```python
# limiter.py
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://",
    strategy="moving-window",
    default_limits=["100 per minute"],
)
```

### 2.5 Enforce API-key auth with a decorator

Create `utils/auth_utils.py::require_api_key`:

```python
from functools import wraps
from flask import request, jsonify
from database.auth_db import verify_api_key

def require_api_key(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if request.args.get("apikey"):
            return jsonify({"status": "error", "message": "apikey in URL not allowed"}), 400
        data = request.get_json(silent=True) or {}
        key = request.headers.get("X-API-KEY") or data.get("apikey")
        if not key:
            return jsonify({"status": "error", "message": "Missing apikey"}), 401
        if not verify_api_key(key):
            return jsonify({"status": "error", "message": "Invalid apikey"}), 401
        return f(*args, **kwargs)
    return wrapper
```

Apply uniformly across `restx_api/*` resources:

```python
class PlaceOrder(Resource):
    @limiter.limit(ORDER_RATE_LIMIT)
    @require_api_key
    def post(self):
        ...
```

This closes the "key extracted after partial processing" gap and makes timing-uniform failures trivial.

---

## Part 3 — Public-IP Deployment Checklist

Required before exposing OpenAlgo on a public IP:

- [ ] Bind `WEBSOCKET_HOST=127.0.0.1` and `ZMQ_HOST=127.0.0.1`; front WebSocket with nginx + TLS + IP allowlist.
- [ ] `FLASK_DEBUG=False` — set as read-only environment variable in systemd unit / Dockerfile, not runtime-configurable.
- [ ] Unique `APP_KEY` and `API_KEY_PEPPER` via `secrets.token_hex(32)` — do not reuse `.sample.env` values.
- [ ] nginx in front with:
  - TLS 1.3 and HSTS.
  - IP allowlist for TradingView / Chartink source ranges on webhook paths.
  - `proxy_set_header X-Forwarded-For $remote_addr;` and `TRUSTED_PROXIES` configured in app.
  - Access log format that strips query strings.
- [ ] HMAC signatures on all webhooks (C5).
- [ ] Session ID rotation on login (C4).
- [ ] `@require_api_key` decorator applied across `/api/v1/*`.
- [ ] Random per-deployment Fernet salt (H4).
- [ ] Rate-limit additions from §2.4 applied; global `default_limits` configured.
- [ ] Monitor `log/errors.jsonl`; alert on repeated 401/403 from the same IP.
- [ ] Rotate broker tokens at the daily 03:00 IST expiry, not on-demand via unauthenticated path.

---

## Part 4 — Remediation Roadmap

**Phase 1 (this sprint, <1 day total):**
1. Global limiter `default_limits=["100 per minute"]`.
2. Reduce login limits to 3/min, 15/hr.
3. Add rate limits to the Critical rows in §2.3.
4. Reject `apikey` in query params at all `/api/v1/*` endpoints.
5. Session regeneration on login.
6. Bind ZMQ to loopback; update `.sample.env` and install scripts.

**Phase 2 (next 1–2 weeks):**
7. `@require_api_key` decorator rollout across `restx_api/*`.
8. Per-user WebSocket connection + subscription caps.
9. HMAC on strategy / Chartink / flow webhooks with backward-compatible migration.
10. Random per-deployment Fernet salt (with migration that re-encrypts existing broker tokens on first start).
11. Trusted-proxy handling for `X-Forwarded-For`.
12. Auth + rate limit on `/health/api/*` metrics endpoints.

**Phase 3 (next month):**
13. Timing-uniform API-key verification path.
14. Progressive login lockout + email alerts on repeated failures.
15. Redis-backed limiter storage (documented) for multi-instance deployments.
16. Marshmallow `validate.Range` on all order/price fields.

---

## Appendix — Files Most Relevant To Follow-up Work

- `limiter.py` — global limiter config
- `app.py:143–144` — limiter init (add `default_limits`)
- `app.py:275–293` — CSRF exemption list
- `blueprints/auth.py:179–244` — login flow (session rotation)
- `blueprints/auth.py:407` — reset-password-email GET (missing rate limit)
- `database/auth_db.py:56–65` — Fernet KDF (static salt)
- `database/auth_db.py:731–806` — API-key verify cache (timing)
- `restx_api/*.py` — 44 namespaces needing `@require_api_key`
- `websocket_proxy/server.py:392–427` — per-client limits
- `blueprints/websocket_example.py:61–186` — WS control-plane rate limits
- `blueprints/python_strategy.py:1665–1964` — strategy exec rate limits
- `blueprints/historify.py:120–1536` — export/import rate limits
- `blueprints/chartink.py:787`, `blueprints/strategy.py:~869`, `blueprints/flow.py:596,610` — webhook HMAC
- `utils/ip_helper.py` — `X-Forwarded-For` trust model
- `csp.py:28–35` — CSP style relaxation
- `start.sh:70–82`, `.sample.env` — WEBSOCKET_HOST / ZMQ_HOST defaults

---

*Audit conducted on branch `main` at commit `9e742ee9a`. This report describes the state at that commit; verify against `git log` before acting on specific line numbers.*
