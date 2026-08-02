# CLAUDE.md

Guidance for Claude Code working in this repository. This file carries what is
**not discoverable by reading the code**: product context, invariants, runtime
constraints, and conventions. Structure, commands, and config are discoverable —
read them from the repo.

## Overview

OpenAlgo is a production algorithmic trading platform: Flask backend, React 19
frontend. It is **several products in one self-hosted instance**, all sharing a
single broker session and WebSocket feed:

| Surface | Route | Purpose |
| --- | --- | --- |
| Unified Broker API | `/api/v1/` | External platforms (TradingView, Amibroker, ChartInk, Excel, Python, MCP) |
| Python Strategy Host | `/python` | In-browser editor; scripts scheduled on IST times, run as isolated subprocesses with live logs |
| Flow (No-Code Builder) | `/flow` | Node graph: market data to indicators to conditions to order execution |
| Options Trading Suite | `/tools` | 15 analytical tools (Strategy Builder, Option Chain, Option Greeks, OI Tracker, Max Pain, Vol Surface, GEX, IV Smile, Arbitrage, ...) |
| Charting Terminal | `/trading` | Line-based chart trading, powered by the `openalgo-charts` package |
| Scalping Terminal | `/scalping` | Keyboard-driven options scalping (`blueprints/scalping.py` resolves underlying/expiry/strike; index options only — NRML/MIS, never CNC) |

All surfaces share the Sandbox engine (1 Crore sandbox capital, exchange-aligned
auto square-off) and support Telegram alerts.

Repository: https://github.com/marketcalls/openalgo
Documentation: https://docs.openalgo.in

## Documentation Map

All project documentation lives under `docs/` as markdown (the single source of
truth). **Start from [`docs/INDEX.md`](docs/INDEX.md)** — it maps every area
(REST API, Python SDK, indicators, user guide, BDD specs, PRDs, design, scalping,
installation, audits) to its entry file.

Read `docs/INDEX.md` first, then open only the specific doc you need instead of
scanning the tree. Do **not** copy or restate docs into a second location — edit
the source file in `docs/` and every reader sees the change.

## Skills

Detailed procedures live in `.claude/skills/` and load on demand:

- **`fd-audit`** — run after any change touching DB, WebSockets/streaming, threads/executors, subprocesses, files, or sockets
- **`version-bump`** — releasing the platform, or bumping the pinned `openalgo` SDK (two unrelated version numbers)
- **`broker-integration`** — adding or modifying a broker plugin

## Security and Deployment Model

- **Single user per deployment** — no multi-user, no privilege escalation. One user, one broker session per instance.
- **Self-hosted on the user's own server** — server access equals full control. No SaaS component.
- All official install scripts (`install.sh`, `install-docker.sh`, `install-multi.sh`, `docker-run.sh`, `docker-run.bat`, `start.sh`) auto-generate unique `APP_KEY` and `API_KEY_PEPPER` via `secrets.token_hex(32)`.
- **SEBI static IP mandate** (effective April 1, 2026): transactional API orders require broker-side static IP whitelisting. Delta Exchange (crypto) enforces the same. Stolen broker credentials cannot be used from an attacker's machine — the broker rejects non-registered IPs. Attacks routed *through* the OpenAlgo server (which holds the registered IP) remain viable.
- External platforms (TradingView, GoCharting, Chartink) send API keys in the JSON body or URL query params — they cannot set custom HTTP headers. This is an accepted architectural trade-off.
- The stdio MCP server (`mcp/mcpserver.py`) is local-only and not remotely exposed. `blueprints/mcp_http.py` and `blueprints/mcp_oauth.py` are the remote-facing MCP surfaces.
- Indian broker tokens expire daily at ~3:00 AM IST. Session management is aligned to that schedule.

## Runtime Constraints

**Three runtimes, and code must work in all of them.** This is the single most
common way a change passes locally and fails on deploy.

| Runtime | Used by | Threading |
| --- | --- | --- |
| **eventlet** (`gunicorn --worker-class eventlet -w 1`) | Docker and Ubuntu server — **the default** | Green threads |
| **gthread** (`gunicorn --worker-class gthread --threads 64 -w 1`) | Opt-in, experimental (see below) | Real OS threads |
| **dev server** (`uv run app.py`) | Windows and macOS desktop | Real OS threads |

Write for the **strictest** of the three: assume real OS threads (so guard
shared state) *and* assume eventlet (so no `asyncio`).

### Eventlet + Gunicorn (the current default)

- **No `asyncio`.** Eventlet monkey-patches the stdlib and is incompatible with `asyncio.run()`, `async`/`await`, and `asyncio.get_event_loop()`. Async work must use eventlet green threads or run on a separate real OS thread — see `telegram_bot_service.py:_render_plotly_png` for the pattern.
- **Single worker (`-w 1`) is mandatory.** Flask-SocketIO state is in-process and cannot be shared across workers.
- **`threading.local()` maps to green threads**, which is why `scoped_session` works correctly under eventlet.
- **Never call `eventlet.monkey_patch()` from application code.** Eventlet is activated only by Gunicorn's worker class. Modules that `import eventlet` do so to *detect* patching (`eventlet.patcher.is_monkey_patched`) and must degrade cleanly when it is absent.

### gthread (opt-in, experimental)

Eventlet is retired and **Gunicorn 26 removes the worker entirely**, so the
platform is migrating to gthread. It is opt-in and **not the default**: setting
`OPENALGO_WORKER_CLASS = 'gthread'` in `.env` switches it, and removing the line
switches back. Resolution lives in `install/lib/gunicorn_runtime.sh`, which is
sourced by `start.sh`, both installers and `update.sh`.

- **Selecting gthread always implies a thread count** (64 by default, floored at 16). Gunicorn's own default of one thread deadlocks on the first SSE stream, so the two settings are deliberately coupled — never plumb them independently.
- **Gunicorn 25.3 ships both workers**, so the opt-in needs no dependency change. The pin stays `gunicorn>=25.0,<26` until the cutover.
- Status, open items and per-step notes: `docs/progress/gthread/README.md` and `docs/plans/2026-08-01-gthread-migration-tracker.csv`.

**The governing rule:** *under eventlet, code that does not yield is atomic
relative to other greenlets; under gthread it is not.* Every check-then-act on
shared state that was accidentally safe becomes a real race. Because the dev
server already uses real threads, those races are reachable on Windows and
macOS **today** — they are not hypothetical future bugs.

### Thread-safety patterns this migration established

Follow these when touching shared state; each was written after a real defect.

- **Bind one snapshot, then use it.** Never `if key in d: return d[key]` on state another thread can mutate — a swap between the two lines raises `KeyError`. Use `.get()`, or bind the container once (`snap = self._snap`). See `database/token_db_enhanced.py`.
- **Iterate a copy, never the live container.** `for k, v in D.items()` raises `RuntimeError` if another thread inserts mid-loop. Snapshot under the lock, iterate outside it. This applies to comprehensions too.
- **Publish by single rebind.** Build the replacement off to the side and assign once, so readers see the complete old generation or the complete new one. Where order matters, stamp a generation and refuse to publish an older one over a newer.
- **Never hold a lock across I/O** — a disk write, a process `wait()`, a broker call, or a `join()`. Snapshot under the lock, release, then do the slow thing.
- **Fixed lock order.** Where two locks exist, always take them in the same order; opposing order between two threads is a deadlock that hangs the worker permanently. Current order: `PROCESS_LOCK` before `_CONFIG_FILE_LOCK` (`blueprints/python_strategy.py`).
- **Locks belong on the class, not the instance.** Managers are constructed per request, so a per-instance lock guards nothing.
- **No `preexec_fn`.** It runs between `fork()` and `exec()` and is documented as unsafe with threads — ours called `logger.*`, and a fork while another thread held a logging lock produced a child that hung forever. Apply limits in the child after exec (`_RLIMIT_BOOTSTRAP`).
- **`socketio.emit()` is not thread-safe.** Use the single `extensions.socketio` (`SerializedSocketIO`) object; never construct another.

Two gate scripts enforce part of this: `scripts/gthread_check_then_act.py` and
`scripts/gthread_sleep_inventory.py`. **Both have known blind spots** — the
first only sees attribute guards (`self.foo`), not bare module-level names, and
does not detect check-then-*read* at all. A clean run is not proof.

### Development server differs

`uv run app.py` uses standard threading, not eventlet. `asyncio` works fine
there and **breaks under eventlet in production**. SQLite locking is also
stricter on Windows.

## Invariants — do not break these

### ZeroMQ bus: SUB binds, PUBs connect

The ZMQ market-data bus (`ZMQ_PORT`, default 5555) is **fan-in**: the proxy's SUB
(`websocket_proxy/server.py`) is the **single binder**, and **every publisher
CONNECTs to it** — the broker market-data adapters
(`base_adapter._connect_to_zmq_bus`, `connection_manager.SharedZmqPublisher.connect`)
and the cache-invalidation publisher (`database/cache_invalidation.py`).

- **Never make a publisher `bind()`.** ZMQ allows many PUBs to connect to one bound SUB, so publishers across processes share one fixed port with no contention.
- **`ZMQ_PORT` is fixed by config and never drifts.** No port scan, no `5555 -> 5556` fallback, no runtime mutation of `os.environ["ZMQ_PORT"]`. `install-multi.sh` gives each instance its own `ZMQ_PORT` (`5555 + i-1`) and each stays put.
- **Why:** under gunicorn+eventlet the proxy runs *out of process* (a subprocess via `install.sh`, or a separate `python -m websocket_proxy.server` on Docker `start.sh`) while the cache-invalidation publisher runs inside gunicorn. If a publisher binds, the two processes race for the port; the loser silently slides to the next port while the SUB stays put, so **`subscribe` succeeds but no ticks are delivered**. Works on the single-process dev server and breaks under Gunicorn — with either worker class, since the proxy is out of process in both — which is what made it historically very hard to spot. Broker-agnostic.

### Multi-session login must not tear down the shared broker feed

OpenAlgo is single-user, but the same user may be logged in from **multiple
devices at once** (`active_sessions`, cap `MAX_SESSIONS_PER_USER = 5`). All of
them share **one** server-side broker feed — a single pool keyed
`{broker}_{user_id}` in `websocket_proxy/broker_factory.py:_POOLED_ADAPTERS`,
fanned out by the proxy. A second device must stream without interrupting the first.

The hazard: a 2nd-device login resumes the existing broker session
(`blueprints/auth._try_resume_broker_session`) and re-persists the **same** token
through `database.auth_db.upsert_auth`. `upsert_auth` is also what tears the feed
down — it publishes a ZMQ `CACHE_INVALIDATE_ALL` (the out-of-process proxy's
`_handle_cache_invalidation` disconnects the adapter and pool) and calls
`cleanup_pools_for_user`. That teardown is **only correct when the token actually
changed** (real login, ~3 AM rollover, logout/revoke).

- **Gate the teardown on a real token change.** `upsert_auth` compares the new token / feed-token / broker / revoke flag against the stored row using **decrypted plaintext** — Fernet ciphertext is non-deterministic, so never compare encrypted blobs. If nothing material changed, clear the cheap in-process caches and return early, leaving the live feed up. Only a genuine change (or `revoke=True`) runs the ZMQ-publish + `cleanup_pools_for_user` path.
- **Why:** without the gate, a same-day 2nd-device login kills the 1st device's stream until it refreshes (Shoonya), and on single-active-session Finvasia/Noren brokers the disconnect churn drops the broker token entirely (Flattrade "broker session expired"). See issue #1591. The teardown itself is the #1394/#765/#851 fix — keep it, just keep it gated. Broker-agnostic.

### SQLite uses NullPool, never StaticPool

All SQLite engines are created via `database.engine_factory.create_db_engine()`,
which applies `NullPool` — a fresh connection per operation, closed immediately.
**Never use `StaticPool`**: a single shared connection has its cursor state
corrupted by concurrent requests, producing `"bad parameter or other API misuse"`
and `"cannot commit - SQL statements in progress"`. All platforms.

FD leak prevention rests on five session-cleanup layers: `app.py`
`teardown_appcontext`; `traffic_logger.py` explicit `logs_session.remove()` in a
`finally`; `security_middleware.py` for the banned-IP WSGI path; and teardown
handlers in `blueprints/traffic.py` and `blueprints/security.py`.

## Architecture

Six isolated databases: `openalgo.db` (main), `logs.db`, `latency.db`,
`health.db`, `sandbox.db` (fully isolated from live trading),
`historify.duckdb` (historical market data). Each has its own init function in
`database/`.

**Market data pipeline**, three layers:

1. **Broker adapters** (`broker/*/streaming/`) connect to the broker's proprietary feed and normalize ticks. Per-broker capacity is `MAX_SYMBOLS_PER_WEBSOCKET` (1000) x `MAX_WEBSOCKET_CONNECTIONS` (3) = 3000 symbols.
2. **ZeroMQ bus** (port 5555) decouples the feed from delivery — the adapter never blocks on a slow client.
3. **WebSocket proxy** (`websocket_proxy/server.py`, port 8765) manages client connections, subscriptions, and per-symbol throttling.

**Request pipeline.** WSGI middleware wraps in *reverse* registration order —
last registered is outermost. `app.py` calls `init_security_middleware(app)`
before `init_traffic_logging(app)`, so traffic logging wraps outside security:

```
Request -> TrafficLogger -> SecurityMiddleware (IP ban, 403) -> CSP
        -> Flask (routing, CSRF, session) -> API key auth (/api/v1/)
        -> Service layer -> Broker API
```

Session cleanup runs in `teardown_appcontext` after the response is sent.

**State changes broadcast over SocketIO**, not polling: `order_update`,
`analyzer_update`, `cache_loaded`. The React frontend subscribes to these for
live dashboards.

Ports: app 5000, WebSocket proxy 8765, ZeroMQ 5555.

Two built-in pages exercise the streaming stack end to end: **`/websocket/test`**
(market data; `/20`, `/30`, `/50` variants request those depth levels) and
**`/websocket/order`** (account-level order/trade update stream). Use them to
verify a broker feed rather than writing a throwaway client.

**React routes do not all have Flask routes**, and that is fine — the `app.py`
404 handler falls through to `serve_react_app()`, so React Router handles them.
The reason to still register a route in `blueprints/react_app.py` is that
unregistered paths hit `Error404Tracker` for *unauthenticated* visitors and
count toward an IP ban.

## Symbol Format

Standardized across all brokers; broker-specific symbols are mapped via
`broker/*/mapping/` and stored in `SymToken`.

- **Equity:** base symbol — `INFY`, `SBIN`, `TATAMOTORS`
- **Futures:** `[Base][Expiry]FUT` — `BANKNIFTY24APR24FUT`, `CRUDEOILM20MAY24FUT`
- **Options:** `[Base][Expiry][Strike][CE/PE]` — `NIFTY28MAR2420800CE`, `VEDL25APR24292.5CE`

**Exchanges:** `NSE`, `BSE` (equity), `NFO`, `BFO` (F&O), `CDS`, `BCD`
(currency), `MCX`, `NCDEX` (commodity), `NCO` (NSE commodities, Zerodha only),
`NSE_INDEX`, `BSE_INDEX` (indices), `GLOBAL_INDEX` (Zerodha only, quote-only —
US30/JAPAN225/HANGSENG plus `GIFTNIFTY` from NSE IFSC).

**Order constants:** product `CNC` / `NRML` / `MIS`; price type `MARKET` /
`LIMIT` / `SL` / `SL-M`; action `BUY` / `SELL`.

**`SymToken` schema:** `symbol` (OpenAlgo), `brsymbol` (broker), `exchange`,
`brexchange`, `token`, `expiry`, `strike`, `lotsize`, `instrumenttype`, `tick_size`.

API keys reach `/api/v1/` in the JSON body (preferred) or the `X-API-KEY` header;
they are generated at `/apikey` and hashed with pepper before storage.

## Conventions

**Always use uv.** Never global Python, never a hand-managed venv, never activate
anything: `uv run app.py`, `uv run python script.py`, `uv run pytest test/ -v`,
`uv add package`, `uv sync`. Python 3.12+.

**Logging.** `logger = get_logger(__name__)` from `utils/logging.py` in every
module. Error logging is always `logger.exception()` — it captures the traceback
and routes it to the JSON handler. Never `import traceback` /
`traceback.print_exc()` / `traceback.format_exc()`; those bypass centralized
logging. Never `print()`.

**When debugging, read `log/errors.jsonl` first.** One JSON object per line:
timestamp, logger, module, `file:line`, message, full traceback, and Flask
request context (method, path, IP) when available. Truncated to the last 1000
entries at startup.

**FD hygiene.** Every DB engine/session, file, socket, WebSocket, ZMQ socket,
subprocess pipe, thread, and executor is a file descriptor, and production is a
single Gunicorn worker that never restarts — a leak accumulates until "too many
open files". Preventing one at creation is far cheaper than hunting it later:

- SQLite engines via `database.engine_factory.create_db_engine()`
- Every `scoped_session` registered in the `app.py` teardown, or used as `with db_session() as session:`
- HTTP via the shared `utils/httpx_client.get_httpx_client()`, always with an explicit timeout
- WebSocket adapters close before reconnect
- Subprocesses write to a log file (not `PIPE`) and are `.wait()`-reaped
- Threads and executors are shared module-level singletons, never per-call

After a change touching any of these, run the **`fd-audit`** skill before calling
it done.

**Database access** goes through the SQLAlchemy ORM, not raw SQL.

**Style.** Python: Ruff (`uv run ruff check . --fix`, `uv run ruff format .`),
config in `pyproject.toml`; 4 spaces, Google-style docstrings. React/TypeScript:
Biome (`frontend/biome.json`), functional components with hooks, PascalCase
component files, TanStack Query for server state.

**Commits.** Conventional Commits: `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`.

**No icons or emojis anywhere** — source, comments, log messages, commit
messages, PR descriptions, changelogs, release notes, or any generated text
including drafts for Discord or Telegram. Use plain text labels.

## Frontend build

`frontend/dist/` is in `.gitignore` so contributors cannot commit half-built
artifacts — but on `main` it **is tracked**. The `commit-dist` job in
`.github/workflows/ci.yml` force-adds (`git add -f`) the freshly built dist back
to `main` after every successful push.

- **Production servers and backend-only contributors need no Node.js.** A plain `git pull` from `main` brings the latest UI. This is the canonical upgrade path.
- **React developers** run `cd frontend && npm install && npm run build` (or `npm run dev`) locally, since the local `.gitignore` will not track their output. Build only — tests run in CI.
- **Feature branches** CI has not built may carry stale or missing `dist/`. Build locally or rebase onto recent `main`.

Config lives in `.env` (copy from `.sample.env`); `VALID_BROKERS` gates which
broker plugins load, and plugins are discovered at startup only.
