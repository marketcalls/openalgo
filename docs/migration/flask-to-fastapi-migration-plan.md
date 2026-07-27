# Flask → FastAPI Migration Plan & Risk Assessment

**Branch:** `claude/flask-openalgo-migration`
**Status:** Proposal / Pre-implementation — **v2** (revised after independent second audit; see §1a)
**Tracker:** `docs/migration/flask-to-fastapi-migration-tracker.csv` (work items, phases, acceptance criteria)
**Audience:** Maintainers evaluating whether (and how) to move OpenAlgo's web layer from Flask + Flask-SocketIO + eventlet/Gunicorn to FastAPI + python-socketio + Uvicorn ASGI.
**Scope of this document:** A grounded, file-referenced assessment of what a migration touches, the risks, and a phased procedure that keeps the UI, API contract, `.env`, logs, Docker, and install/upgrade paths byte-for-byte compatible for end users.

> **Bottom line up front.** OpenAlgo's *bulk* business logic — most of the service layer, the sandbox/flow/historify engines, the ZeroMQ bus, the websocket proxy, the MCP engine, and the React UI — is framework-agnostic and lifts unchanged. **But the Flask coupling is NOT a clean thin shell** (this corrects the v1 framing; see §1a for the audit): 23 files outside the HTTP layer import Flask — including **11 broker API/mapping files** that use `flask.session` — and **44 files import `extensions.socketio` directly**, including all 33 broker `master_contract_db.py` modules. Session/auth product logic lives in `utils/`. **Therefore a mandatory pre-migration hardening phase on Flask (Phase 1) — request-context abstraction, a notifier abstraction, a single lifecycle owner, and broker decoupling — must precede any FastAPI code**, so that the framework swap itself touches only true shell code. **The single highest-risk item remains the production runtime model: eventlet + Gunicorn `-w 1`, fundamentally incompatible with asyncio.** FastAPI's value proposition is async; adopting it means replacing the runtime *and* the realtime host simultaneously — high-effort, high-blast-radius, in a system that places live trading orders. A **strangler-fig / incremental** approach with the hardening gate is strongly recommended over a big-bang rewrite.

---

## 0. Why consider this at all (and the honest counter-argument)

**Potential gains**
- Native `async def` + `httpx.AsyncClient` for concurrent broker I/O (multi-leg option strategies, option-chain fan-out across strikes).
- Pydantic v2 request/response models replacing Marshmallow schemas — typed end-to-end, faster validation.
- Native OpenAPI 3.1 docs (currently disabled — `restx_api/__init__.py:10` sets `doc=False`, so there is no live Swagger UI to preserve; FastAPI would *add* this capability).
- Better editor/type tooling across `services/`.

**The honest counter-argument**
- The framework is **not** the current performance ceiling. Broker API latency and the single-worker SocketIO constraint dominate. `utils/httpx_client.py` is already a pooled HTTP/2 client; eventlet already gives cooperative concurrency for I/O today.
- The migration replaces the runtime, the realtime layer, the middleware stack, CSRF/session, and rate limiting **at once**. Each is individually testable, but the production runtime swap (eventlet → asyncio) is all-or-nothing.
- This is live-trading software. Regressions in order routing, session/CSRF, or the realtime feed have direct financial consequences.

**Recommendation:** Treat this as a multi-phase program with a working fallback at every step, not a single PR. Keep the public surface (API JSON shape, `.env`, logs, Docker ports, install/upgrade commands) **identical** so end users notice nothing.

---

## 1. Deep-Sweep Audit Summary (what is and isn't coupled to Flask)

The table classifies every major subsystem by migration impact. "Framework-agnostic" = no Flask import in the hot path; lifts unchanged.

| Subsystem | Key locations | Flask coupling | Migration impact |
| --- | --- | --- | --- |
| **App factory / wiring** | `app.py:132` `create_app()` | High — `Flask(__name__)`, extension init order, blueprint registry | **Rewrite** → FastAPI app + `lifespan` |
| **Routing — UI/webhooks** | `blueprints/*.py` (48 files) | High — `Blueprint`, `@bp.route` | **Rewrite** → `APIRouter` |
| **Routing — REST API** | `restx_api/*.py` (49 files, 46 namespace files, 54 Resource classes) | High — Flask-RESTX `Namespace`/`Resource` | **Rewrite** → FastAPI routers + Pydantic |
| **Request validation** | `restx_api/*schema.py` (Marshmallow) | Medium — Marshmallow | **Port** → Pydantic v2 |
| **Service layer** | `services/*.py` (68 files) | **Bulk None**, but 2 files import Flask (`telegram_alert_service.py`, `whatsapp_alert_service.py`) + 7 import `extensions.socketio` | **Bulk lifts unchanged after Phase 1 decoupling** (P1-07/P1-12) |
| **Broker integrations** | `broker/*/` (33 brokers) | **NOT None** — 11 API/mapping files import `flask.session`; all 33 `master_contract_db.py` import `extensions.socketio` | **Lifts after Phase 1 decoupling** (P1-06/P1-08) |
| **Databases** | `database/*.py` (34 modules, 6 DBs) | Low — `g`/teardown + `auth_db.py` conditional Flask import + `master_contract_cache_hook.py` socketio | **Lift after** `g`/socketio removal (P1-04/P1-07); rewire teardown |
| **Engine/session factory** | `database/engine_factory.py` (NullPool) | **None** | **Lift unchanged** |
| **HTTP client** | `utils/httpx_client.py` (sync `httpx.Client`) | Low — `from flask import g` (`:55`) | **Lift after** `g`→ContextVar (P1-02) |
| **Logging** | `utils/logging.py` (stdlib) | Low — reads Flask `request` ctx opportunistically; Werkzeug-specific filters | **Lift after** ContextVar swap + filter retirement (P1-03/§3.9) |
| **SocketIO (events)** | `extensions.py:6`, `subscribers/socketio_subscriber.py`, **+44 direct importers** | High — Flask-SocketIO host **and scattered direct `socketio.emit` across core** | **Re-host** → python-socketio ASGI, **after** notifier abstraction collapses 44→1 (P1-05/06/07) |
| **WebSocket proxy (market data)** | `websocket_proxy/server.py` (asyncio + `zmq.asyncio`) | **None** (separate process/thread, already asyncio) | **Lift unchanged** |
| **ZeroMQ bus** | `websocket_proxy/base_adapter.py:187` (PUB), `server.py:110` (SUB) | **None** | **Lift unchanged** |
| **Broker streaming adapters** | `broker/*/streaming/*` | **None** (real OS threads; eventlet escape hatch only) | **Lift unchanged** (simplify eventlet escape in P5-03) |
| **Schedulers** | `services/*scheduler*.py`, `blueprints/python_strategy.py` (APScheduler) | Low — passed `socketio` | **Lift**; rewire emit via notifier; start via lifecycle owner |
| **Sandbox engine** | `sandbox/` (11 modules), `services/sandbox_service.py`, `database/sandbox_db.py`, `sandbox/squareoff_thread.py` | **None** (event bus + APScheduler + threads) | **Lift unchanged**; only `blueprints/sandbox.py` shell ports |
| **Security middleware** | `utils/security_middleware.py` (WSGI) | High — WSGI callable | **Port** → ASGI middleware |
| **Traffic logger** | `utils/traffic_logger.py` (WSGI) | High — WSGI callable | **Port** → ASGI middleware |
| **CSP / security headers** | `csp.py:155` (`after_request`) | Medium | **Port** → ASGI middleware |
| **CSRF** | Flask-WTF `CSRFProtect` (`app.py:145`), `/auth/csrf-token` | High — no FastAPI equivalent | **Replace** → custom/`starlette-csrf` |
| **Sessions / login** | `flask.session` cookie dict (no Flask-Login despite dep); `utils/session.py`, `utils/auth_utils.py` product logic | High — **session/auth logic in `utils/`, not just glue** | **Replace** → Starlette session middleware behind a session seam (P1-09); see §3.19 |
| **Rate limiting** | `limiter.py` (Flask-Limiter, in-memory moving-window) | High | **Replace** → SlowAPI |
| **CORS** | `cors.py` (Flask-CORS) | Medium | **Replace** → `CORSMiddleware` |
| **React SPA serving** | `blueprints/react_app.py` (index + hashed assets + br/gz negotiation) | Medium | **Port** → `StaticFiles` + custom routes |
| **Jinja templates** | 1 inline `render_template_string` (OAuth consent, `mcp_oauth.py:641`) + **42 dead `render_template()` calls across 20 blueprint files** (no `templates/` dir) | Low | **Port** the 1 live template; **dispose** the 42 dead calls (P1-11) |

**Two facts that materially de-risk this migration and are worth stating up front:**
1. **The market-data path is already asyncio.** `websocket_proxy/server.py` uses `asyncio` + `zmq.asyncio` and runs as a **separate process** under Gunicorn/eventlet (`websocket_proxy/app_integration.py`). It does not depend on Flask at all. The migration does **not** touch market-data streaming, ZeroMQ, or broker streaming adapters.
2. **There is one live server-rendered template, plus dead ones.** The UI is a React SPA served from `frontend/dist/`. The only **live** Jinja usage is the inline OAuth-consent form (`mcp_oauth.py:641`); the 42 other `render_template()` calls (across 20 blueprints) point at a non-existent `templates/` dir and are dead routes shadowed by React. "Managing the UI the same" is therefore a static-file-serving problem plus a one-template port plus an explicit dead-route disposition — not a templating rewrite.

Most target-stack dependencies are already in the tree: `starlette==1.0.1`, `uvicorn==0.44.0`, `sse-starlette==2.4.1`, `httpx==0.28.1`, `pydantic==2.12.5`, `python-socketio==5.16.1` (`pyproject.toml`). **However, `fastapi` itself is NOT a dependency yet** (verified: absent from `pyproject.toml`, `requirements*.txt`, and `uv.lock`) — it must be added with a pin compatible with the existing `starlette`/`pydantic` pins, and the Flask-Limiter/Flask-WTF replacements (`slowapi`, CSRF library) need explicit version decisions. Tracked as P2-01.

---

## 1a. Second-Audit Validation & Corrections (v2)

An independent static audit challenged several v1 claims. Every claim was re-verified against the working tree. **All eight substantive findings validated**, and the v1 "governing principle" was overstated. Corrections below override anything contradictory elsewhere in this document.

| # | Second-audit claim | Verdict | Evidence |
| --- | --- | --- | --- |
| 1 | Hidden Flask coupling exists in services, utils, **broker code**, and database helpers | **VALIDATED** — v1 undercounted | **23 files** outside `blueprints/`/`restx_api/` import Flask: **11 broker files** (`broker/pocketful/api/order_api.py:3` + `funds.py` use `flask.session`; same in wisdom, fivepaisaxts, rmoney, jainamxts, ibulls ×2, indmoney, iifl, compositedge), **9 utils** (`auth_utils.py:8-10` imports `current_app/jsonify/redirect/request/session/url_for`; `httpx_client.py:55` `from flask import g`; plus `session.py`, `ip_helper.py`, `latency_monitor.py`, `logging.py`, `plugin_loader.py`, and the two middleware), **2 services** (`telegram_alert_service.py`, `whatsapp_alert_service.py`), `database/auth_db.py` |
| 2 | Startup is import-time, not factory-time | **VALIDATED** | `app.py:812` `app = create_app()` at module import, followed by `setup_environment(app)`, background cache restore, scheduler/bot/proxy startup. `gunicorn app:app` relies on import side effects. FastAPI port requires a real **lifecycle owner** + `lifespan` |
| 3 | Socket.IO is deeply mixed into core logic, not centralized in EventBus | **VALIDATED** — v1's "~18 emit sites, mostly EventBus" was wrong | **44 files** import `extensions.socketio` outside `blueprints/`/`subscribers/` — including **33 broker `database/master_contract_db.py`** (one per broker), 7 services (`orderstatus_service.py:9`, `openposition_service`, `order_router_service`, `historify`, `telegram_bot`, `whatsapp_bot`), `utils/api_analyzer.py`, `utils/auth_utils.py`, `utils/session.py`, `database/master_contract_cache_hook.py:8` |
| 4 | Session/CSRF/request-context are product logic, not thin glue | **VALIDATED** | `utils/session.py:6` (Flask session + redirect; `check_session_validity` decorator used across **43 blueprint files**); `utils/auth_utils.py:352` `handle_auth_success()` writes `session["logged_in"]` etc. — auth flow logic living in utils |
| 5 | `fastapi` missing from dependencies | **VALIDATED** | Absent from `pyproject.toml`, `requirements*.txt`, `uv.lock`. v1's "target deps already vendored" was misleading |
| 6 | Template usage understated — many `render_template` calls | **VALIDATED** (nuanced) | **44 `render_template(` calls across 23 blueprint files**, all referencing templates that don't exist (no `templates/` dir) — dead routes shadowed by React, but **each needs an explicit disposition** (delete / convert to JSON / redirect) during the port; they cannot be silently ignored |
| 7 | API-key contract unclear: `X-API-KEY` vs body `apikey` | **VALIDATED** | Header `X-API-KEY` is honored **only** by `restx_api/telegram_bot.py` and `whatsapp_bot.py` (plus query-param fallback). **All core trading/data endpoints require `apikey` in the JSON body** (Marshmallow `required=True`). CLAUDE.md's "or in headers" overstates. Migration must preserve **per-endpoint** behavior — neither "fixing" body-only endpoints by adding header support nor dropping the header on bot endpoints |
| 8 | Safety net too weak — CI runs a small test subset | **VALIDATED** | `.github/workflows/ci.yml:47-49` runs exactly **5 test files** (log location, navigation, python editor, rate limits, logout CSRF). Nothing covers API contracts, SocketIO events, order lifecycle, or startup |

One additional fact surfaced during validation: **the React frontend pins Socket.IO to polling transport** — `transports: ['polling']` in `useSocket.ts:148` (comment: "WebSocket upgrade fails with threading async mode"), `useOrderEventRefresh.ts:75,130`, `ActionCenter.tsx:148`, `WhatsAppIndex.tsx:67`. The ASGI Socket.IO mount **must keep long-polling working** on day one. (Post-migration, ASGI may finally allow enabling the websocket upgrade — treat as an optional improvement, not part of parity.)

### Corrected governing principle
> The *bulk* of business logic (sandbox engine, flow/historify engines, options analytics, websocket proxy, ZMQ, schedulers, MCP engine) is framework-agnostic and lifts unchanged. **But the boundary is not clean at the edges:** 23 files outside the HTTP shell import Flask (including 11 broker API/mapping files), 44 files import `extensions.socketio` directly (including every broker's master-contract module), and session/auth product logic lives in `utils/`. **A pre-migration hardening phase on Flask (Phase 1) is therefore mandatory, not optional** — decouple these via a request-context abstraction (`contextvars`), a notifier abstraction for events, and a single lifecycle owner *before* introducing FastAPI, so the framework swap itself touches only true shell code.

---

## 2. The Async Runtime Problem (the crux)

This is the load-bearing risk. Read it carefully before committing to the program.

### 2.1 Current model
- Production: `gunicorn --worker-class eventlet --workers 1` (`start.sh:332`, `Dockerfile` CMD → `start.sh`).
- Flask-SocketIO is deliberately configured `async_mode="threading"` (`extensions.py:8`) to *avoid* eventlet greenlet crashes — a hard-won workaround (GitHub #1419).
- `-w 1` is mandatory: SocketIO/Flask state is in-process and cannot be shared across workers.
- eventlet monkey-patches the stdlib; `asyncio.run()` / `async/await` break under it. The codebase already isolates async-needing code (Telegram bot, websocket proxy) onto **real OS threads or subprocesses** via `eventlet.patcher.original("threading")` (see `services/telegram_bot_service.py`, `websocket_proxy/app_integration.py`).

### 2.2 Target model
- FastAPI is ASGI. The natural host is **Uvicorn** (already a dependency).
- python-socketio supports an **ASGI** mode (`socketio.ASGIApp`) that mounts alongside FastAPI — same client protocol, so the React `useSocket.ts` hook needs no protocol change.
- eventlet is **removed entirely**. Code currently using `eventlet.patcher.original(...)` to escape monkey-patching simply uses stdlib `threading` directly (no monkey-patching to escape).

### 2.3 Why this is the crux
- You cannot run FastAPI *under* the eventlet worker. The runtime swap is **atomic**: the moment you switch the entrypoint to Uvicorn/ASGI, every piece that assumed eventlet green threads must already be validated under asyncio + threadpool.
- Sync service functions (all 68 of them) will run in FastAPI's threadpool when called from `async` routes via `run_in_threadpool` (or by declaring the route `def` instead of `async def`, which FastAPI auto-offloads to the threadpool). **This preserves behavior** without rewriting services to async on day one — a critical de-risking lever (see Phase 4).
- SQLite + NullPool behavior must be re-validated under the threadpool concurrency model (it should be fine — NullPool opens/closes per operation and `check_same_thread=False` is set in `engine_factory.py` — but it must be load-tested).

### 2.4 Worker count caveat
Even on ASGI you likely stay at **one Uvicorn worker** because Flask-SocketIO's successor (python-socketio) still keeps room/connection state in-process unless you add a message-queue backplane (e.g. Redis). Do **not** assume the migration unlocks multi-worker scaling for free — that is a separate project (add a socketio Redis manager).

---

## 3. Dimension-by-Dimension Assessment

### 3.1 Security (must remain at parity or improve)
Current hardening that **must be reproduced exactly**:
- APP_KEY fail-fast (`app.py:174`): refuse to boot if `< 32` chars.
- Session cookie flags: `HTTPONLY`, `SameSite=Lax`, `Secure` when `USE_HTTPS` (`app.py:189-198`).
- CSRF cookie `__Secure-` prefix on HTTPS (`app.py:222`).
- API key auth: Argon2 hash + pepper + Fernet token encryption, with verify/invalid caches (`database/auth_db.py:764,876,942`). **Unchanged** — lives in `database/auth_db.py`, framework-agnostic; FastAPI calls it from a `Depends()` dependency.
- IP ban enforcement *before* app logic (`utils/security_middleware.py`) → must become ASGI middleware that runs **outermost**, preserving the 403-before-Flask semantics.
- `FLASK_DEBUG=True` + non-loopback host = refuse to start (`app.py:914`). Reproduce as an equivalent Uvicorn-side guard.
- `SensitiveDataFilter` log redaction (`utils/logging.py:149`) — unchanged.

**New security surface to get right:**
- CSRF: Flask-WTF is replaced. The `/auth/csrf-token` endpoint contract (returns `{"csrf_token": ...}`, validated via `X-CSRFToken` header) must be reimplemented faithfully — the React client (`frontend/src/api/client.ts`) depends on it. Use `starlette-csrf` or a small custom double-submit-cookie dependency. **This is a top audit item** — a subtly weaker CSRF implementation is a real regression.
- Session signing: Flask's `itsdangerous`-signed cookie must be replaced with Starlette `SessionMiddleware` (also `itsdangerous`-based) keyed on the same `APP_KEY`. Verify cookie name/flags match so existing logged-in users aren't force-logged-out on upgrade (or accept a one-time re-login and document it).
- Run a fresh `bandit` + `pip-audit` + `detect-secrets` sweep on the new shell (the repo already wires these in the `dev` group).

### 3.2 Library replacement map
| Remove | Replace with | Notes |
| --- | --- | --- |
| `Flask` | `fastapi` + `starlette` (present) | — |
| `flask-restx` | FastAPI routers + Pydantic | OpenAPI now auto-generated |
| `Flask-SocketIO` | `python-socketio` ASGI (present) | Same wire protocol |
| `Flask-WTF` | `starlette-csrf` / custom | CSRF parity is critical |
| `Flask-Limiter` | `slowapi` | Same moving-window semantics |
| `Flask-Cors` | `starlette.middleware.cors` | Map `cors.get_cors_config()` |
| `Flask-Login` (unused) | — | Drop; manual session already |
| `Flask-SQLAlchemy` | plain `SQLAlchemy` (present, 2.0.49) | Code already uses bare `scoped_session`, not the Flask extension's `db.Model` in most modules — **verify per module** |
| `Flask-Bcrypt` | `bcrypt` / Argon2 (already Argon2 in auth_db) | Audit any direct Flask-Bcrypt use |
| `Werkzeug` | Starlette equivalents | WSGI middleware → ASGI |
| `gunicorn` + `eventlet` | `uvicorn` (present) | Runtime swap |
| `greenlet` | (drop unless a dep needs it) | SQLAlchemy async would re-add it |

**Keep unchanged:** `httpx`, `APScheduler`, `SQLAlchemy`, `pyzmq`, `python-dotenv`, `pydantic`, `uvicorn`, `starlette`, `sse-starlette`, `python-engineio`.

> **Audit caution — Flask-SQLAlchemy:** Most `database/*.py` modules use bare `scoped_session(sessionmaker(...))`, which is framework-independent. But Flask-SQLAlchemy is in the dependency list, so **grep every model module for `db.Model` / `flask_sqlalchemy` imports before assuming a clean lift.** Any module using the Flask extension's declarative base needs porting to a plain SQLAlchemy `DeclarativeBase`.

### 3.3 Performance
- Expectation: **neutral-to-positive on throughput, neutral on the metric users feel** (broker round-trip latency dominates). Do not sell this migration on raw RPS.
- Real upside requires converting hot broker paths to `httpx.AsyncClient` + `async def` (Phase 5, optional). Until then, sync services run in the threadpool — same effective concurrency profile as eventlet for I/O-bound work.
- Establish a **baseline benchmark before any change** (the repo has `docs/benchmarks/`). Track: order placement p50/p99, quote latency, option-chain build time, SocketIO event delivery latency, memory + FD count over a 24h soak. Gate each phase on "no regression vs baseline."
- FD hygiene (a first-class concern per CLAUDE.md): the threadpool model + NullPool must be soak-tested for descriptor growth on a long-running single Uvicorn worker, exactly as today.

### 3.4 Cross-platform support (Windows / Mac dev, Linux prod)
- Today: dev server uses threading (no eventlet); prod uses eventlet. Code must work in both.
- After: **Uvicorn works identically on Windows/Mac/Linux** — this is actually *simpler* than today (no eventlet, which is Linux-centric for production). Dev (`uv run app.py`) and prod (`uvicorn`) converge on the same ASGI runtime, removing the dev/prod behavioral gap that currently exists around asyncio.
- Validate: APScheduler timezone (IST) behavior, SQLite file-locking on Windows, subprocess spawning of the websocket proxy on all three OSes.

### 3.5 Async
- Phase in, don't big-bang. Routes can be `def` (auto-threadpooled, behavior-preserving) or `async def` (native). Start everything as `def`, convert selectively.
- Only convert a service to `async` once its entire downstream (broker module + httpx call) is async-capable. Mixing `asyncio.run()` inside a threadpool worker is an anti-pattern — avoid.

### 3.6 Managing the UI the same
- The React SPA is unchanged. `blueprints/react_app.py` logic ports to FastAPI:
  - Mount hashed assets (`/assets/*`, 1-year immutable cache) via `StaticFiles`.
  - Reproduce **Brotli/gzip pre-compressed negotiation** (`.br`/`.gz` next to assets, `Accept-Encoding` aware) — Starlette `StaticFiles` doesn't do this out of the box, so port the custom negotiation route.
  - `index.html` served with `Cache-Control: no-cache`.
  - SPA catch-all → return `index.html` for unmatched non-API routes (port the 404→React fallback).
- CI `commit-dist` job and the `frontend/dist` force-commit flow are **unaffected** — they produce the same artifact the new server serves.

### 3.7 API format (must be byte-identical)
- Response envelope `{"status": "success"|"error", "data": ..., "message": ...}` must be preserved exactly. Implement a shared response model/helper; **do not** let FastAPI's default validation-error shape (`{"detail": [...]}`) leak — install a custom `RequestValidationError` handler that emits the existing envelope and HTTP codes (400 validation, 403 invalid apikey, 404, 429, 500).
- API key handling must be preserved **per endpoint, exactly as-is** (see §1a claim 7): core trading/data endpoints accept `apikey` **in the JSON body only** (Marshmallow `required=True`); only the telegram/whatsapp bot endpoints additionally honor the `X-API-KEY` header and query param. Build a per-endpoint apikey-source matrix in Phase 0 and assert it in contract tests — do not "fix" this asymmetry during the port (external platforms depend on body-key behavior; changing acceptance surface area is a security decision, not a migration side effect).
- Rate-limit 429 body (`{"status":"error","message":"Rate limit exceeded...","retry_after":60}`, `app.py:552`) must match.
- **Contract tests are mandatory**: snapshot every `/api/v1/` endpoint's response on Flask, replay on FastAPI, diff. This is the safety net for the whole migration.

### 3.8 `.env` structure (no user-facing change)
- `.sample.env` stays as-is. All variables are framework-agnostic or map cleanly.
- `FLASK_DEBUG`, `FLASK_ENV`, `FLASK_HOST_IP`, `FLASK_PORT` should be **kept as aliases** read by the new bootstrap (don't force users to edit `.env` on upgrade). Optionally add `APP_HOST`/`APP_PORT` synonyms but keep the `FLASK_*` names working. Document that `FLASK_DEBUG` now toggles Uvicorn `--reload` and the debug guard.
- WebSocket (`WEBSOCKET_HOST/PORT`), ZMQ (`ZMQ_HOST/PORT`), `LOG_*`, rate-limit, CORS/CSP/CSRF, MCP OAuth vars — all unchanged.

### 3.9 Centralized logging & error traceback (must be byte-compatible)
The logging architecture is a hard parity requirement, not an afterthought — operators and the docs rely on `log/errors.jsonl` as the first debugging stop.

**What lifts unchanged** — `utils/logging.py` is pure stdlib: the three handlers (colored console via `ColoredFormatter`, daily-rotated `log/openalgo_YYYY-MM-DD.log`, always-on `log/errors.jsonl` JSON Lines), `get_logger(__name__)` everywhere, the `logger.exception()` convention (auto-captured tracebacks routed into the JSON error handler), `LOG_LEVEL`/`LOG_TO_FILE`/`LOG_DIR`/`LOG_FORMAT`/`LOG_RETENTION`/`LOG_COLORS`/`FORCE_COLOR` env vars, and the 1000-entry startup truncation. None of this changes.

**What must be actively ported** (this is where v1 was too thin):
1. **`errors.jsonl` request context** — the JSON handler reads Flask request context opportunistically (`utils/logging.py:314-324`). Replace with the Phase 1 `ContextVar` lookup so every error line keeps its `method`/`path`/`IP` fields with an **identical JSON schema** (assert schema in a Phase 0 test).
2. **Werkzeug-specific filters become dead code** — `WerkzeugErrorFilter` (`utils/logging.py:75`) and its wiring to the `werkzeug`/`werkzeug._internal`/Flask-internal loggers (`utils/logging.py:424-436`), plus `WebSocketHandshakeFilter` (`:113`), target a server that no longer exists. Retire them and add equivalent noise filters for uvicorn's known non-actionable messages.
3. **Uvicorn loggers must be captured, not parallel** — uvicorn ships its own `uvicorn.access`/`uvicorn.error` loggers with their own handlers. Left at defaults, access lines **bypass the central handlers entirely** — meaning no `ColoredFormatter`, no file rotation, and critically **no `SensitiveDataFilter`**. Since some endpoints accept `apikey` as a **query parameter** (telegram/whatsapp bot routes, §1a claim 7), an unfiltered access log would write API keys to disk — a security regression. Configure uvicorn with `log_config=None` (or explicit propagation) so all its records flow through the existing root handlers and redaction filter; add a Phase 0 redaction test that requests a URL with `?apikey=...` and asserts it never appears un-redacted in any log output.
4. **Traceback convention enforcement** — the "always `logger.exception()`, never `traceback.format_exc()`" rule survives unchanged; the new ASGI exception handlers (Phase 2) must call `logger.exception()` before returning the error envelope so `errors.jsonl` captures the same full tracebacks it does today.

### 3.10 Event-driven architecture
- The EventBus + subscribers pattern (`subscribers/socketio_subscriber.py`) is framework-agnostic; it just needs a working `emit` handle.
- The EventBus executor (ThreadPoolExecutor, ~10 workers) lifts unchanged; its startup/shutdown moves into the Phase 1 lifecycle owner so subscriber registration order, delivery semantics, and clean drain-on-shutdown match today's behavior. Domain events (`events/*.py` dataclasses: order, sandbox, alert events) are pure Python and untouched.
- Event names must stay identical (`order_event`, `analyzer_update`, `cache_loaded`, `force_logout`, `master_contract_download`, `historify_progress`, etc.) — the React client subscribes to these exact strings (`frontend/src/hooks/useSocket.ts`).
- python-socketio's `emit` is thread-safe from the threadpool when using the ASGI server's async manager; validate emit-from-sync-threadpool works (it does via `socketio.AsyncServer` + `start_background_task` or the sync `Server` mounted appropriately — pick one model and prove it).

### 3.10a Sandbox engine (kept as-is — lifts unchanged)
**Short answer: yes, the Sandbox is kept the same.** ~95% of it is framework-agnostic and migrates untouched; only the thin HTTP shell (`blueprints/sandbox.py`) ports like every other blueprint.

What lifts **unchanged**:
- **The entire `sandbox/` package** (11 modules, ~6,400 lines): `execution_engine.py`, `execution_thread.py`, `websocket_execution_engine.py`, `squareoff_thread.py`, `squareoff_manager.py`, `order_manager.py`, `position_manager.py`, `fund_manager.py`, `holdings_manager.py`, `catch_up_processor.py`. Zero Flask imports, zero eventlet.
- **`services/sandbox_service.py`** — pure functions returning the same `tuple[bool, dict, int]` as the live trading services; no Flask, no direct `socketio.emit`. It publishes via the framework-agnostic event bus (`bus.publish(SandboxOrderFilledEvent(...))`, `sandbox/execution_engine.py:221`).
- **`database/sandbox_db.py`** — plain SQLAlchemy `scoped_session` + models for `sandbox.db` (₹1 Cr capital). Only change: its entry in the `teardown_appcontext` session-cleanup list (`app.py:860`) moves to the FastAPI per-request dependency / `lifespan` (same as every other DB module).
- **Auto-squareoff scheduler** (`sandbox/squareoff_thread.py`) — APScheduler `BackgroundScheduler` with exchange-aligned cron jobs (NSE/BSE 15:15, CDS/BCD 16:45, MCX 23:30, NCDEX 17:00, T+1 @ 00:00 IST). Framework-agnostic; start call moves from `app.py` startup into the FastAPI `lifespan`.
- **Execution engine threading** (`sandbox/execution_thread.py`) — a daemon `threading.Thread` polling/subscribing for fills; WebSocket-driven via `MarketDataService` with a polling fallback through `services/quotes_service.py`. No eventlet, no Flask — works identically under ASGI.
- **Sandbox events** (`events/sandbox_events.py`: `SandboxOrderFilledEvent`, `SandboxAutoSquareOffEvent`, `SandboxT1SettlementEvent`) → already decoupled; they reach the UI through the same EventBus → SocketIO subscriber path, which re-hosts on python-socketio with **identical `analyzer_update` event names**.

What **ports** (thin shell only, same effort as any blueprint):
- `blueprints/sandbox.py` JSON routes (`/sandbox/api/configs`, `/sandbox/update`, `/sandbox/reset`, `/sandbox/squareoff-status`, `/sandbox/mypnl/api/data`, CSV exports) → `APIRouter`; `session.get("user")` → auth dependency; Flask `Response`/CSV → `StreamingResponse`.
- Note: `blueprints/sandbox.py` still imports `render_template` and calls `render_template("sandbox.html")` (lines 86, 778), **but no `templates/` directory exists** — these are **dead/vestigial paths**; the live `/sandbox` UI is the React SPA. Drop them during the port (don't recreate templates).

Net: the Sandbox **engine, capital model, margin/leverage, auto-squareoff timing, and isolation from live trading are preserved byte-for-byte.** It is one of the lowest-risk parts of the migration.

### 3.10b Every other feature — engines kept as-is (only HTTP shells port)
The Sandbox finding generalizes — with the §1a caveat — to the **entire feature set**. I audited Flow, Historify, Playground, the ngrok/ZMQ/WebSocket config, the Telegram/WhatsApp bots, MCP, Action Center, the Options Tools suite, monitoring, and the integration webhooks.

> **Corrected governing principle (supersedes the v1 wording, aligned with §1a):** the *engines* — `sandbox/`, `websocket_proxy/`, `mcp/`, and most of `services/` and `database/` — are framework-agnostic and kept byte-for-byte. **But the boundary is not clean: the edges import Flask.** 23 files outside the HTTP shell import Flask (incl. 11 broker files using `flask.session`), **44 files import `extensions.socketio` directly** (incl. all 33 broker `master_contract_db.py` modules — NOT the ~18 v1 claimed), and session/auth product logic lives in `utils/`. So the per-feature tables below show "engine kept as-is" **on the explicit precondition that Phase 1 hardening first severs those edge imports** (notifier abstraction for the 44 emit sites, `flask.session` removal from broker code, context/session seams). After Phase 1, the user-visible behavior (routes, JSON, event names, schedules, webhooks) stays identical and only the HTTP shell is rewritten.

| Feature | Engine / logic (kept as-is) | Thin shell that ports | Config |
| --- | --- | --- | --- |
| **Flow (no-code builder)** | `services/flow_executor_service.py`, `flow_price_monitor_service.py`, `flow_scheduler_service.py` (APScheduler), `database/flow_db.py` — pure Python, JSON-stored graphs | `blueprints/flow.py` routes + webhook + `socketio.emit` | env/JSON, unchanged |
| **Python Strategy Host** | subprocess-isolated strategy runners, `database/strategy_db.py`, shared APScheduler, market-calendar checks — all pure Python | `blueprints/python_strategy.py` (~21 routes); log streaming via **SSE** (`text/event-stream`) → FastAPI `StreamingResponse`/`sse-starlette` (already a dep); `request.files` upload → `UploadFile` | unchanged; **subprocess isolation preserved** |
| **Historify (DuckDB)** | `services/historify_service.py` (~2,200 lines), `database/historify_db.py` (**pure DuckDB**, no SQLAlchemy/Flask), `historify_scheduler_service.py` (APScheduler) | `blueprints/historify.py` (59 routes) + `historify_progress`/`job_complete` emits | `HISTORIFY_DATABASE_URL`, unchanged |
| **Playground (API tester)** | `parse_bru_file()` / `load_bruno_endpoints()` (pure parsers) | `blueprints/playground.py` 3 JSON routes; its `render_template("playground.html")` is a **dead path** (no templates dir) — drop it | — |
| **ngrok** | `utils/ngrok_manager.py` — spawns tunnel via pyngrok, signal/atexit cleanup, **zero Flask coupling** | just the `start_ngrok_tunnel(port)` call moves into `lifespan` | `NGROK_ALLOW`, `NGROK_AUTH_TOKEN`, `HOST_SERVER` via `os.getenv` — unchanged |
| **ZMQ / WebSocket config** | `websocket_proxy/*`, broker `streaming/*` — all read `ZMQ_HOST/PORT`, `WEBSOCKET_HOST/PORT/URL`, `MAX_SYMBOLS_*` via `os.getenv` (never Flask `app.config`) | nothing — proxy already separate process | `.env`, unchanged |
| **Telegram bot** | `services/telegram_bot_service.py` (real-OS-thread, python-telegram-bot) | `blueprints/telegram.py` + 1 `app_mode_changed` emit | bot token/db, unchanged |
| **WhatsApp bot** | `services/whatsapp_bot_service.py` (real-OS-thread) | `blueprints/whatsapp.py` + `whatsapp_qr/paired/status` emits | unchanged |
| **MCP (HTTP/OAuth)** | `mcp/mcpserver.py` (`FastMCP` engine, pure) — already uses `sse-starlette` | `blueprints/mcp_http.py`, `mcp_oauth.py`, `database/oauth_db.py` | `MCP_*` vars, unchanged |
| **Action Center** | `services/action_center_service.py`, `database/action_center_db.py`, `order_router_service.py` | `pending_order_created/updated` emits in `orders.py` | unchanged |
| **Master contract** | `database/master_contract_cache_hook.py` logic | `cache_loaded` / `master_contract_download` emits | unchanged |
| **Options Tools (/tools, 12 tools)** | `services/iv_chart_service.py`, `oi_tracker_service.py`, `gex_service.py`, `vol_surface_service.py`, `iv_smile_service.py`, `oi_profile_service.py`, `option_chain_service.py`, `custom_straddle_service.py`, `strategy_chart_service.py` — all pure pandas/math | the matching `blueprints/*.py` JSON endpoints | unchanged |
| **Latency / Health monitoring** | `database/latency_db.py`, `health_db.py`, `utils/health_monitor.py` | `blueprints/latency.py`, `health.py` (+ per-blueprint teardown handlers) | `LATENCY_/HEALTH_DATABASE_URL`, unchanged |
| **Chartink / Strategy webhooks** | `database/chartink_db.py`, `strategy_db.py`; queue+APScheduler order processing | `blueprints/chartink.py`, `strategy.py` webhooks (CSRF-exempt) | unchanged |
| **Traffic / Security** | `database/traffic_db.py` (`TrafficLog`/`IPBan`/trackers) | `blueprints/traffic.py`, `security.py` + their teardown handlers; WSGI→ASGI middleware | unchanged |
| **TradingView / GoCharting / ChartInk adapters** | service layer | `blueprints/tv_json.py`, `gc_json.py` (CSRF-exempt, API-key-in-body) | unchanged |

**The one genuinely shared migration task across all of the above is SocketIO — and it is bigger than v1 estimated** (corrected in §1a claim 3): **44 files** import `extensions.socketio` directly outside the shell layers, including **all 33 broker `master_contract_db.py` modules**, 7 services, and 3 utils. Order events flow through the framework-agnostic EventBus (`utils/event_bus.py` + `subscribers/`), but master-contract progress, historify jobs, WhatsApp pairing, and order-status emits do **not** — they call `socketio.emit` inline. The fix is the Phase 1 **notifier abstraction**: these modules publish domain events to a notifier interface; a single subscriber owns the actual Socket.IO emit. After that, the framework swap touches one file instead of 44. **Event names and payloads stay identical** (the React client subscribes to fixed strings), so the UI sees no change. The ASGI mount must also keep **long-polling transport** working — the frontend pins `transports: ['polling']` (§1a).

**Two small accuracy notes from the sweep (pre-existing, independent of migration):**
- Several blueprints (`playground.py:287`, and the dead `render_template` paths) reference Jinja templates that don't exist — vestigial code to drop during the port, not recreate.
- `database/auth_db.py` has the only conditional Flask import outside blueprints (`has_request_context`/`request`), used purely to opportunistically attach request context — trivially swapped for a `ContextVar` (already called out in Phase 1).

### 3.11 ZeroMQ support (untouched)
- PUB at `base_adapter.py:187` (port 5555, loopback), async SUB at `server.py:110` (`zmq.asyncio`). Lives entirely in the websocket-proxy process. **No migration work.** Verify only that the proxy is still spawned correctly by the new entrypoint (it's started from `app.py` today via `start_websocket_proxy`; that call moves into the FastAPI `lifespan` startup).

### 3.12 Docker support (TCP mode — ports preserved, EXPOSE wording corrected)
- Multi-stage `python:3.12` build, non-root `appuser`. **Precise port facts:** the `Dockerfile` only `EXPOSE 5000` (single line, verified); port **8765** is published by `docker-compose.yaml:10-11` (`${FLASK_PORT:-5000}:5000` and `${WEBSOCKET_PORT:-8765}:8765`) and the install scripts — **not** by the Dockerfile. Migration keeps this exactly; if a second `EXPOSE 8765` is desired for documentation it's an optional, separate change — do not claim the Dockerfile exposes 8765 today.
- Change: `start.sh` swaps `gunicorn --worker-class eventlet -w 1 ... app:app` → `uvicorn <asgi target> --host 0.0.0.0 --port ${APP_PORT} --workers 1` (TCP bind), with `--timeout-keep-alive` + graceful-shutdown tuning approximating the current 300s/30s timeouts.
- **Preserve pre-start migrations:** `start.sh` runs `upgrade/rotate_pepper.py` (`:273`) and `upgrade/migrate_all.py` (`:292-294`) **before** launching the server. The cutover must keep these steps and their ordering (migrations → app start) intact — they are not framework-specific and must not be dropped (P5-01).
- Remove the `uv pip install ... eventlet` line from the Dockerfile (P5-03). The websocket-proxy subprocess spawn simplifies (no eventlet branch) but stays a subprocess for isolation.

### 3.13 Ubuntu install procedure — TWO transport modes, documented separately
The single-instance Docker/`start.sh` path binds **TCP** (`:5000`), but the Linux systemd + nginx installers proxy to a **Unix domain socket**, not TCP — this distinction was glossed in v1 and matters for the cutover:

- **TCP mode** (Docker, `start.sh`, dev): uvicorn binds `0.0.0.0:${APP_PORT}`. nginx (where present) proxies to `:5000`. Straightforward gunicorn→uvicorn swap.
- **UDS mode** (systemd + nginx, multi-instance): `install/install-multi.sh:279` and `install/change-domain.sh:106,156` create `openalgo.sock`, and nginx uses `proxy_pass http://unix:$SOCKET_FILE` (`install-multi.sh:536`, `change-domain.sh:585,609`). Gunicorn binds that socket today. **uvicorn must bind the same socket via `--uds $SOCKET_FILE`** so the existing nginx config keeps working untouched; otherwise the nginx `proxy_pass` must change. The migration's systemd `ExecStart` rewrite (P5-02) must explicitly use `--uds` to match, and the WebSocket upgrade to `:8765` (TCP) is unaffected in both modes.
- `requirements-nginx.txt` drops `gunicorn`/`eventlet`, keeps the rest; `uvicorn[standard]` is already pinned. **User-facing install/upgrade commands stay the same.**

### 3.14 Update procedure (must remain `git pull` + `uv sync` + restart)
- The canonical upgrade path (`git pull` from main → `uv sync` → restart; `install/update.sh`) **must not change** for users. The only difference is the service restarts a Uvicorn process instead of Gunicorn — invisible to the operator running `update.sh`.
- The `frontend/dist` CI auto-commit flow is unchanged.

### 3.15 Running the application (commands identical, dev and prod)
- **Dev:** `uv run app.py` keeps working on Windows/Mac/Linux exactly as today. Internally `socketio.run(app, ...)` (`app.py:1011`) becomes `uvicorn.run(...)`, but the operator-visible behavior is preserved: same startup banner (host/port/WebSocket/docs/status block), `FLASK_DEBUG=True` still enables auto-reload, the debug+non-loopback **refusal guard** (`app.py:914-937`) is reproduced, and the access points are unchanged (app on `FLASK_PORT`/5000, WebSocket proxy on 8765, React at `/`).
- **Prod:** `start.sh`/systemd swap gunicorn→uvicorn (§3.12/§3.13); operators run the same scripts. A side benefit: dev and prod converge on **one runtime** (today dev=threading, prod=eventlet — a real behavioral gap that disappears).
- **No new commands, no new flags, no `.env` edits** required of any operator at any phase.

### 3.16 Webhook features & security (byte-identical contract)
External platforms cannot adapt — the webhook surface must be preserved exactly. Verified inventory and auth models:

| Webhook | Route | Auth model | Notes |
| --- | --- | --- | --- |
| Strategy (TradingView etc.) | `POST /strategy/webhook/<webhook_id>` (`blueprints/strategy.py:869`) | **UUID4 secret in URL path** (`uuid.uuid4()` at creation, `strategy.py:816`); invalid → 404 `{"error": "Invalid webhook ID"}`, inactive → 400 | Plus intraday **time-window enforcement** (IST entry/exit logic, LONG/SHORT exit detection) — product logic that must port byte-for-byte |
| ChartInk | `POST /chartink/webhook/...` (`blueprints/chartink.py`) | Same UUID-in-path model | Queue + APScheduler order processing behind it |
| Flow | `POST /flow/.../webhook` | **Richer:** per-workflow `webhook_token`, `webhook_secret`, `webhook_auth_type` (`blueprints/flow.py:88-91`) | Multiple auth types — enumerate and test each in P0-11 |
| TradingView JSON / GoCharting | `blueprints/tv_json.py`, `gc_json.py` | `apikey` in JSON body (platforms cannot set headers) | — |

Security properties that must survive the port, in order: **IP-ban middleware still applies** (outermost, before any webhook code), **rate limits** apply, **CSRF-exempt** (these are the canonical exemptions in `app.py:386-408`), error shapes/status codes identical, and webhook IDs/secrets never logged (covered by `SensitiveDataFilter` parity, §3.9). The UUID-in-URL model means webhook URLs are credentials — confirm the traffic logger continues to store paths only where it does today, no expansion of logging surface.

### 3.17 CI pipeline (kept green at every phase, three jobs untouchable)
The pipeline (`.github/workflows/ci.yml` + `security.yml`) has **9 jobs**: `backend-lint` (ruff check + format), `backend-test` (currently 5 CI-safe files), `frontend-lint`, `frontend-build`, `frontend-test` (+ Playwright e2e), `security-scan` (bandit + pip-audit), `commit-dist` (force-commits built dist to `main`), `docker-build` (Docker Hub push by digest + Kaleido/Chromium smoke test).

- **Untouchable:** `commit-dist`, `frontend-*` jobs — the React build flow is orthogonal to this migration and must not be modified. Docker-build changes only via the Dockerfile CMD swap in Phase 5 (its smoke test must still pass).
- **Extended:** `backend-test` grows the Phase 0 contract/webhook/logging suites as **required checks**, phase by phase — this is how each phase gate is enforced mechanically rather than by discipline.
- **Watched:** `backend-lint` (ruff) must pass on all new ASGI code; `security-scan` re-baselines when dependencies change in P2-01/P5-03 (new `fastapi`/`slowapi` pins go through pip-audit).

### 3.18 Operator migration & rollback runbook (the user-facing "migration procedure")
For the operator running an existing Flask-based instance, the cutover release must look like **any other release**:

1. **Upgrade** — `cd openalgo && git pull && uv sync && restart` (or `install/update.sh`, or `docker pull` + recreate). No `.env` edits, no DB migrations (all 6 databases and `db/historify.duckdb` are untouched by the framework swap), no Node.js needed.
2. **What the operator may notice** — a **one-time forced re-login should be treated as the LIKELY default, not a maybe.** Starlette's `SessionMiddleware` does not use Flask's session serializer, so matching cookie name/flags/`APP_KEY` is **not sufficient** for Starlette to read an existing Flask session cookie — the signing/serialization formats differ. Reading old cookies would require intentionally implementing a Flask-compatible serializer (extra scope + security review). Plan for re-login on upgrade and say so in release notes (decision in P2-06; R4). Broker re-auth follows the normal daily flow. Everything else is unchanged: same ports, URLs, API keys, webhooks, logs.
3. **Rollback** — because there are no schema changes, rollback is symmetric: `git checkout <previous-tag> && uv sync && restart` (or redeploy the previous Docker image tag). Databases, `.env`, and webhook URLs all remain valid in both directions. The release that ships the cutover must pin a **known-good rollback tag** in its notes.
4. **Recommended rollout** — ship the cutover as a major platform version (per the version-bump procedure in CLAUDE.md), hold it in a release-candidate window with the soak/regression evidence from P5-04 attached, and keep the previous minor as the documented rollback for one full token-expiry cycle (≥1 trading day, given the ~3 AM IST token reset).

### 3.19 Login flow & smart master contract download (the trickiest stateful flow — mapped exactly)
This is the most intricate state machine in the app, it lives partly in `utils/auth_utils.py` (one of the 23 Flask-coupled files, §1a), and it must be reproduced **state-for-state**. Verified behavior:

**The two-step login state machine** (`blueprints/auth.py:253-352`):
1. **App login** (`POST /auth/login`): username/password via `authenticate_user()`. If the user has TOTP enabled for login, `session["user"]` is **deliberately NOT set** — the username is parked on a transient `session["pending_totp_user"]` + `pending_totp_started_at`, and only `POST /auth/login/totp` consumes it on success (with timeout/failure clearing). **This gate is a security property: an attacker with only the password must not reach broker login.**
2. **Session-state semantics are subtle and load-bearing:** `session["user"]` alone means *password step done, broker step pending* (GET routing sends this state to `/broker`). Only `session["logged_in"] = True` — set by `handle_auth_success()` (`utils/auth_utils.py:352`) after broker auth — means fully authenticated (routed to `/dashboard`). A migration that collapses these two states into one breaks the flow.
3. **Broker-session resume — the "second login" behavior:** after password (+TOTP), `_try_resume_broker_session(username)` (`auth.py:317`) checks for a still-valid broker token in the DB (Indian broker tokens live until ~3 AM IST). If found, **broker login is skipped entirely** — the user goes straight to the dashboard, and the attempt is logged with `login_type="resume"` (vs `"password"`). This is why a re-login on an already-authenticated instance (including publicly-hosted ones) presents **only the app login, no broker login**. If no valid token exists → redirect `/broker` → per-broker OAuth/credential flow (`blueprints/brlogin.py`, 30+ broker callbacks) → `handle_auth_success()`.
4. **Expiry path:** on GET with `logged_in` but an invalid session window, the app calls `revoke_user_tokens()` + `session.clear()` — token revocation coupled to session expiry, not just cookie deletion.
5. **Single-user model:** `/setup` redirect when no user exists; one user, one broker session per instance (no multi-user paths to port, but the setup-vs-login-vs-broker routing must be exact).

**Smart master contract download** (`utils/auth_utils.py:80-120`, triggered asynchronously by `handle_auth_success`):
- `should_download_master_contract(broker)` rules, all of which must port unchanged: never downloaded → download; **last download was by a different broker → force fresh** (SymToken table would be stale); downloaded **today after the cutoff → skip and use cache**; downloaded before today's cutoff or on a previous day → fresh download.
- Cutoffs are **per-broker-class**: Indian brokers 08:00 **IST**; crypto brokers (Delta) 00:00 **UTC** — with explicit timezone normalization of stored timestamps (`get_master_contract_cutoff`, naive-timestamp IST localization).
- `async_master_contract_download()` runs on a background thread, tracks status transitions in `master_contract_status_db` (`downloading`/`error`/success with duration + per-exchange stats), dynamically imports `broker.{broker}.database.master_contract_db`, and completion fans out to the UI via the `master_contract_download`/`cache_loaded` events (the 33 broker emit sites → notifier abstraction, P1-06) plus strategy restoration via `master_contract_cache_hook`.

**Migration treatment:** the decision logic and status tracking are pure Python and lift unchanged; the session writes and the resume gate are exactly what the Phase 1 session seam (P1-09) must preserve. Phase 0 gains dedicated state-machine tests (P0-12: every login state transition incl. TOTP park/consume/timeout, resume vs fresh-broker-login, expiry revocation; P0-13: smart-download decision matrix incl. cutoff boundaries, broker-change invalidation, IST/UTC handling) so the port is verified against executable truth, not prose.

### 3.20 DB-readiness gate (startup-ordering parity)
A subtle but load-bearing behavior: `app.py` installs a `@app.before_request` gate (`wait_for_db_ready`, `app.py:426-440`) that **blocks every non-static request for up to 30s** on a `threading.Event` (`app.db_ready`, set at `app.py:660` once the background DB/scheduler init thread finishes; the main thread also `app.db_ready.wait()`s at `:822`). This prevents requests from hitting half-initialized databases during the async startup window. The FastAPI port must reproduce it: the lifecycle owner (P1-10) owns the `db_ready` event, and an **ASGI middleware/dependency must enforce the same 30s wait-then-proceed gate** on non-static paths — not just rely on `lifespan` completion, because today's design intentionally starts serving (static) while DBs warm up in the background. Tracked under lifecycle/middleware parity (P1-10, P2-05, P4-11) with an explicit assertion in the startup test (P0-07).

### 3.21 FastAPI auto-docs (`/docs`, `/redoc`, `/openapi.json`) — parity decision required
Flask-RESTX docs are **disabled** today (`restx_api/__init__.py:10` `doc=False`) — there is no public Swagger UI. FastAPI **enables `/docs`, `/redoc`, and `/openapi.json` by default.** Shipping the migration as-is would **add a new public surface** that exposes the full API schema — a security/parity regression for a single-user self-hosted trading app. **Decision: disable them by default** (`FastAPI(docs_url=None, redoc_url=None, openapi_url=None)`) to match current behavior, OR gate them behind authentication if the project deliberately wants docs. This must be a conscious choice in P2-02, asserted by a Phase 0/2 test that `/docs` returns 404 (or 401) unless explicitly enabled. (Native OpenAPI remains available internally for contract tests even with the public routes off.)

---

## 4. Phased Migration Procedure (strangler-fig)

Each phase is independently shippable and reversible. **Do not merge a phase until its contract tests are green against the Flask baseline.**

**Phase 0 — Safety net (no app code change).** CI today runs only 5 test files (§1a claim 8) — this phase builds the net the whole program hangs on.
- API contract snapshot tests for all 46 `/api/v1/` namespaces (request → exact JSON shape + status code), including validation-error shapes, CSV/file responses, and webhook CSRF exemptions.
- **Per-endpoint apikey-source matrix** (body vs `X-API-KEY` vs query) asserted in tests (§1a claim 7).
- Auth/session/CSRF behavior tests (login, TOTP flow, `/auth/csrf-token`, cookie flags, session expiry) and Socket.IO event tests (event names, payloads, **polling transport**).
- Order-lifecycle contract tests in sandbox mode (place → fill → squareoff → settlement).
- Startup behavior test (what `import app` does today — guard against lifecycle regressions).
- Performance + FD baselines (24h soak). Coupling-inventory **CI guard**: a grep gate that fails on *new* `from flask import` / `from extensions import socketio` outside the shell layers, so Phase 1 progress can't regress.
- **Logging/traceback baseline** (P0-10): `errors.jsonl` schema + redaction tests incl. apikey-in-query in access logs (§3.9). **Webhook security suite** (P0-11): every auth model, error shape, and middleware-order property (§3.16). **Login state-machine suite** (P0-12) and **smart master-contract decision matrix** (P0-13) — see §3.19.

**Phase 1 — Pre-migration hardening (decouple in place, still on Flask).** Expanded post-§1a: this is now the largest de-risking phase, and it ships value even if the FastAPI cutover never happens.
- **Request-context abstraction** (`contextvars`): user, API key, client IP, broker API timing, latency tracking, session metadata. Replace `flask.g` in `utils/httpx_client.py:55`, request-context reads in `utils/logging.py`, `utils/latency_monitor.py`, `utils/ip_helper.py`, and the conditional import in `database/auth_db.py`.
- **Notifier abstraction for events**: broker/database/service code publishes domain events; one subscriber owns `socketio.emit`. Rewire all **44** direct importers — the 33 broker `master_contract_db.py` modules (mechanical, one pattern), 7 services, `utils/api_analyzer.py`, `database/master_contract_cache_hook.py`.
- **Remove `flask.session` from broker code** (11 files across 9 brokers — pocketful, wisdom, fivepaisaxts, rmoney, jainamxts, ibulls, indmoney, iifl, compositedge): pass auth/user via function parameters or the context abstraction. Broker modules must be importable with no web framework present.
- **Extract session/auth product logic**: `utils/session.py` (`check_session_validity`, used by 43 blueprint files) and `utils/auth_utils.py` (`handle_auth_success` session writes) get a thin session-interface seam so the decorator/dependency can be re-targeted without touching the 43 call sites' semantics.
- **Single lifecycle owner**: move `app.py`'s import-time side effects (`app.py:812` onward — DB init, cache restore, schedulers, bots, analyzer engine, EventBus executor, httpx client, websocket proxy, ngrok) into one startup/shutdown registry module callable from Flask today and FastAPI `lifespan` tomorrow.
- **Disposition all 44 dead `render_template` calls** (23 files): delete, convert to JSON, or redirect — each explicitly decided, none silently carried over.
- Decouple `services/telegram_alert_service.py`, `whatsapp_alert_service.py`, `utils/plugin_loader.py` from Flask imports.
- **Gate:** re-run the full Phase 0 contract suite — must be byte-identical before any FastAPI code is introduced.

**Phase 2 — Stand up a parallel FastAPI app (proof of concept).**
- **Add `fastapi` to dependencies** (it is not present today — §1a claim 5) with pins compatible with existing `starlette`/`pydantic`; decide and pin `slowapi` + CSRF library.
- New ASGI entrypoint mounting: FastAPI + python-socketio `ASGIApp` (**long-polling transport verified against the React client**) + `StaticFiles` for the SPA; `lifespan` calls the Phase 1 lifecycle owner.
- Port middleware: IP-ban (outermost) → traffic logger → CSP → CORS → session. Port CSRF dependency + `/auth/csrf-token`.
- Migrate **one read-only** namespace first (e.g. `quotes` / `funds`) as `def` routes calling the existing sync service. Run contract tests. This validates auth dependency, envelope, rate limiting, and threadpool DB access end-to-end.

**Phase 3 — Migrate the REST API surface namespace-by-namespace.**
- Convert Marshmallow schemas → Pydantic models, route-by-route, keeping the envelope identical. Order placement / modify / cancel migrate **last** and with the most testing (financial blast radius).
- Each namespace gated on its contract snapshot.

**Phase 4 — Migrate UI/webhook blueprints + realtime host.**
- Port `blueprints/*` → routers (SPA serving with br/gz negotiation, webhooks with CSRF-exempt, OAuth consent Jinja template).
- Cut SocketIO over to python-socketio ASGI; verify every event name with the React client. Move `start_websocket_proxy` and scheduler init into the FastAPI `lifespan`. Wire DB session cleanup into a per-request dependency/`lifespan` (replacing `teardown_appcontext`).

**Phase 5 — Runtime cutover + cleanup (the atomic step).**
- Swap `start.sh`, Dockerfile, systemd `ExecStart`, `install/*.sh` to Uvicorn. Remove eventlet/gunicorn and all Flask-* deps from `pyproject.toml`/`requirements*.txt`. Run `uv sync`.
- Full regression: order lifecycle in sandbox, SocketIO events, market-data feed, schedulers, all three OSes, Docker, nginx, soak/FD test.

**Phase 6 (optional, post-migration) — selective async.**
- Convert the hottest broker read paths (option chain, multi-quote) to `httpx.AsyncClient` + `async def`. Benchmark each against baseline; only keep wins.

---

## 5. Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- | --- |
| R1 | Runtime cutover (eventlet→asyncio) breaks realtime/feed | Med | **Critical** | Phase 4 isolates realtime before Phase 5 cutover; keep proxy as subprocess; soak test |
| R2 | API response shape drifts (FastAPI default error envelope leaks) | High | High | Custom exception handlers + mandatory contract snapshot tests (Phase 0) |
| R3 | CSRF reimplementation weaker than Flask-WTF | Med | High | Use vetted `starlette-csrf`/double-submit; security review + bandit; parity tests |
| R4 | Session cookie change force-logs-out users on upgrade | High | Med | Match cookie name/flags/secret(`APP_KEY`); or document one-time re-login |
| R5 | Hidden Flask coupling (`g`, `request`, Flask-SQLAlchemy `db.Model`) | Med | Med | Phase 0 grep inventory; Phase 1 ContextVar refactors |
| R6 | FD/connection leak under threadpool + NullPool on long-run worker | Med | High | 24h soak with FD monitoring before and after; NullPool unchanged |
| R7 | Order placement regression | Low | **Critical** | Migrate order endpoints last, sandbox-test exhaustively, staged rollout |
| R8 | Users assume multi-worker scaling now works | Med | Med | Document: still `-w 1` unless Redis socketio backplane added |
| R9 | SQLite locking differs under new concurrency on Windows | Low | Med | Cross-platform test matrix (Phase 5) |
| R10 | Scope creep — "rewrite while we're here" | High | High | Strict "behavior parity only" rule; async work deferred to Phase 6 |
| R11 | Hidden coupling broader than estimated (validated §1a: 23 Flask-importing files incl. 11 broker; 44 socketio importers incl. 33 brokers) | **Confirmed** | High | Phase 1 hardening is mandatory; CI grep gate prevents regression |
| R12 | Import-time side effects (`app.py:812`) silently lost in lifespan port — schedulers/bots/proxy not started | Med | **Critical** | Phase 1 lifecycle-owner extraction + Phase 0 startup test |
| R13 | Socket.IO polling transport breaks on ASGI (frontend pins `transports:['polling']`) | Med | High | Explicit polling-transport test in Phase 0; validate ASGI engineio long-polling in Phase 2 |
| R14 | Contract tests built on the small existing CI suite give false confidence | High | High | Phase 0 builds dedicated snapshot/contract suites; CI gate per phase |
| R15 | Per-endpoint apikey-source behavior accidentally "fixed" (header support added/removed) | Med | High | Phase 0 apikey matrix asserted in contract tests |

---

## 6. Go / No-Go Recommendation

**Proceed only if** the goal is long-term maintainability + native async headroom and the team can fund a multi-phase program with full contract-test coverage. The architecture supports it — the *engines* are decoupled and the market-data path is already asyncio — **but the edges are not clean** (§1a: 23 Flask-importing files, 44 socketio importers, session logic in `utils/`), so the pre-migration hardening phase is mandatory, and `fastapi` itself is not yet a dependency.

**Do not proceed** if the immediate goal is "make orders/quotes faster." That is better served by Phase 6-style targeted `httpx.AsyncClient` adoption **inside the existing Flask app** (eventlet already cooperatively schedules I/O), or a standalone FastAPI microservice for one async-heavy surface — neither requires the full runtime cutover.

**Suggested first concrete step:** Execute **Phase 0** (contract/webhook/login/logging tests + baselines + coupling-inventory CI gate) followed by **Phase 1** (the hardening: request-context + notifier abstractions, lifecycle owner, broker decoupling, dead-template disposition). Both ship value on Flask and are fully reversible. **Phase 2 (the first FastAPI code) begins only after the Phase 1 hardening gate (P1-13) is green** — do not stand up the parallel FastAPI app before the edges are decoupled, since its dependencies (P2-* depend on P1-13 in the tracker) assume a clean shell. This sequencing surfaces the real cost of realtime + CSRF + session work without any irreversible commitment.

---

*Appendix — primary evidence (file:line) is embedded inline throughout. Audit performed against the working tree on branch `claude/flask-openalgo-migration`.*
