# Flask → FastAPI Migration Plan & Risk Assessment

**Branch:** `claude/flask-openalgo-migration`
**Status:** Proposal / Pre-implementation
**Audience:** Maintainers evaluating whether (and how) to move OpenAlgo's web layer from Flask + Flask-SocketIO + eventlet/Gunicorn to FastAPI + python-socketio + Uvicorn ASGI.
**Scope of this document:** A grounded, file-referenced assessment of what a migration touches, the risks, and a phased procedure that keeps the UI, API contract, `.env`, logs, Docker, and install/upgrade paths byte-for-byte compatible for end users.

> **Bottom line up front.** OpenAlgo is *not* framework-bound at its core — the service layer, broker integrations, databases, logging, ZeroMQ bus, and React UI are all framework-agnostic. The Flask coupling is concentrated in a thin shell: the app factory, routing (blueprints + Flask-RESTX), CSRF/session, middleware, rate limiting, and SocketIO host. **The single highest-risk item is the production runtime model: eventlet + Gunicorn `-w 1`, which is fundamentally incompatible with asyncio.** FastAPI's entire value proposition is async; adopting it means replacing the runtime *and* the realtime host simultaneously. This is a high-effort, high-blast-radius change in a system that places live trading orders. A **strangler-fig / incremental** approach is strongly recommended over a big-bang rewrite.

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
| **Routing — UI/webhooks** | `blueprints/*.py` (49 files) | High — `Blueprint`, `@bp.route` | **Rewrite** → `APIRouter` |
| **Routing — REST API** | `restx_api/*.py` (49 files, 54 Resources, 46 namespaces) | High — Flask-RESTX `Namespace`/`Resource` | **Rewrite** → FastAPI routers + Pydantic |
| **Request validation** | `restx_api/*schema.py` (Marshmallow) | Medium — Marshmallow | **Port** → Pydantic v2 |
| **Service layer** | `services/*.py` (68 files) | **None** (pure functions, sync) | **Lift unchanged** |
| **Broker integrations** | `broker/*/` (33 brokers) | **None** (dynamic `importlib`) | **Lift unchanged** |
| **Databases** | `database/*.py` (34 modules, 6 DBs) | Low — `g`/teardown only | **Lift**; rewire teardown |
| **Engine/session factory** | `database/engine_factory.py` (NullPool) | **None** | **Lift unchanged** |
| **HTTP client** | `utils/httpx_client.py` (sync `httpx.Client`) | Low — `g.broker_api_time` | **Lift**; optionally add async client |
| **Logging** | `utils/logging.py` (stdlib) | **None** (reads Flask `request` ctx opportunistically) | **Lift unchanged** |
| **SocketIO (events)** | `extensions.py:6`, `subscribers/socketio_subscriber.py` | High — Flask-SocketIO host | **Re-host** → python-socketio ASGI |
| **WebSocket proxy (market data)** | `websocket_proxy/server.py` (asyncio + `zmq.asyncio`) | **None** (separate process/thread, already asyncio) | **Lift unchanged** |
| **ZeroMQ bus** | `websocket_proxy/base_adapter.py:187` (PUB), `server.py:110` (SUB) | **None** | **Lift unchanged** |
| **Broker streaming adapters** | `broker/*/streaming/*` | **None** (real OS threads) | **Lift unchanged** |
| **Schedulers** | `services/*scheduler*.py`, `blueprints/python_strategy.py` (APScheduler) | Low — passed `socketio` | **Lift**; rewire emit handle |
| **Security middleware** | `utils/security_middleware.py` (WSGI) | High — WSGI callable | **Port** → ASGI middleware |
| **Traffic logger** | `utils/traffic_logger.py` (WSGI) | High — WSGI callable | **Port** → ASGI middleware |
| **CSP / security headers** | `csp.py:155` (`after_request`) | Medium | **Port** → ASGI middleware |
| **CSRF** | Flask-WTF `CSRFProtect` (`app.py:145`), `/auth/csrf-token` | High — no FastAPI equivalent | **Replace** → custom/`starlette-csrf` |
| **Sessions / login** | `flask.session` cookie dict (no Flask-Login despite dep) | High | **Replace** → Starlette session middleware |
| **Rate limiting** | `limiter.py` (Flask-Limiter, in-memory moving-window) | High | **Replace** → SlowAPI |
| **CORS** | `cors.py` (Flask-CORS) | Medium | **Replace** → `CORSMiddleware` |
| **React SPA serving** | `blueprints/react_app.py` (index + hashed assets + br/gz negotiation) | Medium | **Port** → `StaticFiles` + custom routes |
| **Jinja templates** | **Only one** inline `render_template_string` (OAuth consent, `mcp_oauth.py`) | Low | **Port** → 1 Jinja2 template |

**Two facts that materially de-risk this migration and are worth stating up front:**
1. **The market-data path is already asyncio.** `websocket_proxy/server.py` uses `asyncio` + `zmq.asyncio` and runs as a **separate process** under Gunicorn/eventlet (`websocket_proxy/app_integration.py`). It does not depend on Flask at all. The migration does **not** touch market-data streaming, ZeroMQ, or broker streaming adapters.
2. **There are effectively zero server-rendered HTML templates.** The UI is a React SPA served from `frontend/dist/`. The only Jinja usage is a single inline OAuth-consent form. "Managing the UI the same" is therefore a static-file-serving problem, not a templating rewrite.

The dependencies for the target stack are **already in the tree**: `starlette==1.0.1`, `uvicorn==0.44.0`, `sse-starlette==2.4.1`, `httpx==0.28.1`, `pydantic==2.12.5`, `python-socketio==5.16.1` (`pyproject.toml`).

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
- API key in JSON body **and** `X-API-KEY` header must both keep working (external platforms can't set headers — see CLAUDE.md).
- Rate-limit 429 body (`{"status":"error","message":"Rate limit exceeded...","retry_after":60}`, `app.py:552`) must match.
- **Contract tests are mandatory**: snapshot every `/api/v1/` endpoint's response on Flask, replay on FastAPI, diff. This is the safety net for the whole migration.

### 3.8 `.env` structure (no user-facing change)
- `.sample.env` stays as-is. All variables are framework-agnostic or map cleanly.
- `FLASK_DEBUG`, `FLASK_ENV`, `FLASK_HOST_IP`, `FLASK_PORT` should be **kept as aliases** read by the new bootstrap (don't force users to edit `.env` on upgrade). Optionally add `APP_HOST`/`APP_PORT` synonyms but keep the `FLASK_*` names working. Document that `FLASK_DEBUG` now toggles Uvicorn `--reload` and the debug guard.
- WebSocket (`WEBSOCKET_HOST/PORT`), ZMQ (`ZMQ_HOST/PORT`), `LOG_*`, rate-limit, CORS/CSP/CSRF, MCP OAuth vars — all unchanged.

### 3.9 Log format (unchanged)
- `utils/logging.py` is pure stdlib and already framework-agnostic. The three handlers (colored console, daily-rotated file, `errors.jsonl`) and `SensitiveDataFilter` are untouched.
- One detail: the JSON error handler opportunistically reads Flask `request` context (`utils/logging.py:314`). Replace that block with an ASGI-compatible request-context lookup (e.g. a `ContextVar` set by middleware) so `errors.jsonl` keeps capturing method/path/IP. Keep the JSON schema identical.

### 3.10 Event-driven architecture
- The EventBus + subscribers pattern (`subscribers/socketio_subscriber.py`) is framework-agnostic; it just needs a working `emit` handle.
- Event names must stay identical (`order_event`, `analyzer_update`, `cache_loaded`, `force_logout`, `master_contract_download`, `historify_progress`, etc.) — the React client subscribes to these exact strings (`frontend/src/hooks/useSocket.ts`).
- python-socketio's `emit` is thread-safe from the threadpool when using the ASGI server's async manager; validate emit-from-sync-threadpool works (it does via `socketio.AsyncServer` + `start_background_task` or the sync `Server` mounted appropriately — pick one model and prove it).

### 3.11 ZeroMQ support (untouched)
- PUB at `base_adapter.py:187` (port 5555, loopback), async SUB at `server.py:110` (`zmq.asyncio`). Lives entirely in the websocket-proxy process. **No migration work.** Verify only that the proxy is still spawned correctly by the new entrypoint (it's started from `app.py` today via `start_websocket_proxy`; that call moves into the FastAPI `lifespan` startup).

### 3.12 Docker support (ports & behavior identical)
- Multi-stage `python:3.12` build, non-root `appuser`, ports **5000** (app) + **8765** (websocket). Keep both.
- Change: `start.sh` swaps `gunicorn --worker-class eventlet -w 1 ... app:app` → `uvicorn app:asgi_app --host 0.0.0.0 --port ${APP_PORT} --workers 1` (plus `--timeout-keep-alive` and graceful-shutdown tuning to match the current 300s/30s timeouts as closely as ASGI allows).
- Remove the `uv pip install ... eventlet` line from the Dockerfile.
- The websocket-proxy subprocess spawn logic simplifies (no eventlet branch) but keep it as a subprocess for isolation.

### 3.13 Ubuntu install procedure (commands unchanged for users)
- `install/install.sh` (systemd), `install-multi.sh`, nginx/SSL variants. The **user-facing commands stay the same**; only the systemd `ExecStart` changes from gunicorn to uvicorn. nginx reverse-proxy config is unaffected (still proxies to `:5000`, still passes WebSocket upgrade to `:8765`).
- `requirements-nginx.txt` drops `gunicorn`/`eventlet`, keeps the rest; add `uvicorn[standard]` (already pinned).

### 3.14 Update procedure (must remain `git pull` + `uv sync` + restart)
- The canonical upgrade path (`git pull` from main → `uv sync` → restart; `install/update.sh`) **must not change** for users. The only difference is the service restarts a Uvicorn process instead of Gunicorn — invisible to the operator running `update.sh`.
- The `frontend/dist` CI auto-commit flow is unchanged.

---

## 4. Phased Migration Procedure (strangler-fig)

Each phase is independently shippable and reversible. **Do not merge a phase until its contract tests are green against the Flask baseline.**

**Phase 0 — Safety net (no code change to the app).**
- Write API contract snapshot tests for all 46 `/api/v1/` namespaces against the running Flask app (record request → exact JSON + status).
- Establish performance + FD baselines (24h soak).
- Inventory: grep for `flask_sqlalchemy`/`db.Model`, direct `Flask-Bcrypt`, `from flask import g/request/session` across `database/`, `services/`, `utils/` to find every hidden coupling.

**Phase 1 — Extract the framework-agnostic core (de-risk in place, still on Flask).**
- Ensure `services/`, `database/`, `utils/httpx_client.py`, `utils/logging.py` have **zero** direct Flask imports in hot paths (replace `g.broker_api_time` with a `ContextVar`; replace `request`-context reads in logging with a `ContextVar`). Ship these on Flask — they're pure refactors and reduce later blast radius.

**Phase 2 — Stand up a parallel FastAPI app (proof of concept).**
- New ASGI entrypoint mounting: FastAPI + python-socketio `ASGIApp` + `StaticFiles` for the SPA.
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

---

## 6. Go / No-Go Recommendation

**Proceed only if** the goal is long-term maintainability + native async headroom and the team can fund a multi-phase program with full contract-test coverage. The architecture *supports* it cleanly — the core is already decoupled, the market-data path is already asyncio, and the target deps are already vendored.

**Do not proceed** if the immediate goal is "make orders/quotes faster." That is better served by Phase 6-style targeted `httpx.AsyncClient` adoption **inside the existing Flask app** (eventlet already cooperatively schedules I/O), or a standalone FastAPI microservice for one async-heavy surface — neither requires the full runtime cutover.

**Suggested first concrete step:** Execute **Phase 0** (contract tests + baselines + coupling inventory) and **Phase 2** (parallel FastAPI app serving one read-only namespace). These are low-risk, reversible, and will surface the real cost of the realtime + CSRF + session work before any irreversible commitment.

---

*Appendix — primary evidence (file:line) is embedded inline throughout. Audit performed against the working tree on branch `claude/flask-openalgo-migration`.*
