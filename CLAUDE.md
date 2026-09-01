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
| Strategy Module & RMS | `/strategy` | Multi-leg options strategies with end-to-end risk management, plus a signal-driven mode for per-alert TradingView trading. Two kinds share one engine: `batch` enters and exits every leg together, `signal` moves one leg per alert. Risk rules come from the shared `services/risk/` core. See [`docs/prompt/strategy_rms_documentation.md`](docs/prompt/strategy_rms_documentation.md). |
| Options & Portfolio Suite | `/tools` | 18 tools. Options analytics (Option Chain, Greeks, OI Tracker, Max Pain, Vol Surface, GEX, IV Smile, Straddle, Arbitrage, ...) plus portfolio and investment tools (Portfolio Backtester, SIP Backtester, Portfolio Analyzer, Strategy Builder). The registry is `frontend/src/lib/tools.ts` — the home page derives its count from it, so add a tool there and both pages update. |
| Charting Terminal | `/trading` | Line-based chart trading, powered by the `openalgo-charts` package |
| Scalping Terminal | `/scalping` | Keyboard-driven options scalping (`blueprints/scalping.py` resolves underlying/expiry/strike; index options only — NRML/MIS, never CNC) |

All surfaces share the Sandbox engine (1 Crore sandbox capital, exchange-aligned
auto square-off) and support Telegram alerts.

Repository: https://github.com/marketcalls/openalgo
Documentation: https://docs.openalgo.in

## Documentation Map

All project documentation lives under `docs/` as markdown (the single source of
truth). **Start from [`docs/INDEX.md`](docs/INDEX.md)** — it maps every area
(REST API, Python SDK, indicators, strategy module and RMS, user guide, BDD
specs, PRDs, design, scalping, installation, audits) to its entry file.

Read `docs/INDEX.md` first, then open only the specific doc you need instead of
scanning the tree. Do **not** copy or restate docs into a second location — edit
the source file in `docs/` and every reader sees the change.

## Skills

Detailed procedures live in `.claude/skills/` and load on demand:

- **`fd-audit`** — run after any change touching DB, WebSockets/streaming, threads/executors, subprocesses, files, or sockets
- **`version-bump`** — releasing the platform, or bumping the pinned `openalgo` SDK (two unrelated version numbers)
- **`broker-integration`** — adding or modifying a broker plugin
- **`chart-indicator`** — building a custom indicator for the `/trading` chart. These are plain JavaScript descriptors on `openalgo-charts`, unrelated to the Python `openalgo.ta` indicators used from strategies and scanners.

## Security and Deployment Model

- **Single user per deployment** — no multi-user, no privilege escalation. One user, one broker session per instance.
- **Self-hosted on the user's own server** — server access equals full control. No SaaS component.
- All official install scripts (`install.sh`, `install-docker.sh`, `install-multi.sh`, `docker-run.sh`, `docker-run.bat`, `start.sh`) auto-generate unique `APP_KEY` and `API_KEY_PEPPER` via `secrets.token_hex(32)`.
- **SEBI static IP mandate** (effective April 1, 2026): transactional API orders require broker-side static IP whitelisting. Delta Exchange (crypto) enforces the same. Stolen broker credentials cannot be used from an attacker's machine — the broker rejects non-registered IPs. Attacks routed *through* the OpenAlgo server (which holds the registered IP) remain viable.
- External platforms (TradingView, GoCharting, Chartink) send API keys in the JSON body or URL query params — they cannot set custom HTTP headers. This is an accepted architectural trade-off.
- The stdio MCP server (`mcp/mcpserver.py`) is local-only and not remotely exposed. `blueprints/mcp_http.py` and `blueprints/mcp_oauth.py` are the remote-facing MCP surfaces.
- Indian broker tokens expire daily at ~3:00 AM IST. Session management is aligned to that schedule.

## Runtime Constraints

### Eventlet + Gunicorn (production)

Production (Ubuntu direct and Docker) runs `gunicorn --worker-class eventlet -w 1`:

- **No `asyncio`.** Eventlet monkey-patches the stdlib and is incompatible with `asyncio.run()`, `async`/`await`, and `asyncio.get_event_loop()`. Async work must use eventlet green threads or run on a separate real OS thread — see `telegram_bot_service.py:_render_plotly_png` for the pattern.
- **Single worker (`-w 1`) is mandatory.** Flask-SocketIO state is in-process and cannot be shared across workers.
- **`threading.local()` maps to green threads**, which is why `scoped_session` works correctly under eventlet.

### Development server differs

`uv run app.py` uses standard threading, not eventlet. Code must work in both.
`asyncio` works fine on the dev server and **breaks in production** — this is the
single most common way a change passes locally and fails on deploy. SQLite
locking is also stricter on Windows.

## Invariants — do not break these

### ZeroMQ bus: SUB binds, PUBs connect

The ZMQ market-data bus (`ZMQ_PORT`, default 5555) is **fan-in**: the proxy's SUB
(`websocket_proxy/server.py`) is the **single binder**, and **every publisher
CONNECTs to it** — the broker market-data adapters
(`base_adapter._connect_to_zmq_bus`, `connection_manager.SharedZmqPublisher.connect`)
and the cache-invalidation publisher (`database/cache_invalidation.py`).

- **Never make a publisher `bind()`.** ZMQ allows many PUBs to connect to one bound SUB, so publishers across processes share one fixed port with no contention.
- **`ZMQ_PORT` is fixed by config and never drifts.** No port scan, no `5555 -> 5556` fallback, no runtime mutation of `os.environ["ZMQ_PORT"]`. `install-multi.sh` gives each instance its own `ZMQ_PORT` (`5555 + i-1`) and each stays put.
- **Why:** under gunicorn+eventlet the proxy runs *out of process* (a subprocess via `install.sh`, or a separate `python -m websocket_proxy.server` on Docker `start.sh`) while the cache-invalidation publisher runs inside gunicorn. If a publisher binds, the two processes race for the port; the loser silently slides to the next port while the SUB stays put, so **`subscribe` succeeds but no ticks are delivered**. Works on the single-process dev server, broken only under eventlet — historically very hard to spot. Broker-agnostic.

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

### Risk rules live in services/risk/ and are never reimplemented

One place decides whether a position has hit its stop, taken its target, earned
a tighter trailing stop, or whether a set of positions has run past its combined
limits. The scalping terminal, the `/strategy` engine, Flow and a REST endpoint
all sit on it.

- **`services/risk/` performs no I/O of any kind.** No database, no broker, no
  market data, no clock, no logging. Every input arrives as an argument and every
  decision leaves as a return value. That is what makes it testable without a
  running platform, identical across consumers, safe to call from a green thread
  and from a real one, and exposable over HTTP without a service layer.
- **Consumers translate, they do not decide.**
  `services/strategy_module/risk_adapter.py` is the pattern: it maps a leg onto
  `PositionRisk`, calls the core, and writes the decision back. Adding a rule
  means changing the core, not adding a second evaluator beside it.
- **`test/risk/vectors.json` is the contract** between the Python core and the
  TypeScript copy in `frontend/src/hooks/useTrailingSL.ts`. Add a case whenever a
  rule changes, or the two drift.
- **Why this is an invariant and not a preference:** the module `/strategy` was
  ported from had its own evaluator, and four defects lived in it undetected -
  a leg with no recorded side evaluated as a short so its stop fired on a
  favourable move; an exit derived from configuration that doubled a short
  instead of covering it; an aggregate summed from a stale per-leg field; and a
  peak and trough persisted as zero on most stop paths. Each is pinned by a test
  marked `PORTED DEFECT`.

Full reference: [`docs/prompt/strategy_rms_documentation.md`](docs/prompt/strategy_rms_documentation.md).

### An order path decides once, under the lock, and never on a global switch

Every place that can send an order for a position somebody already holds is a
place where two decisions can become two orders. Three rules, each learned from
a defect that reversed a real position:

- **Claim under the same lock that checks.** `state.claim_leg_exit` does the
  duplicate check and writes the marker in one hold. The marker is `exit_kind`,
  written *before* the dispatch, never `exit_order_id`, which is not written
  until the order comes back: testing the latter let two rules firing on one leg
  send a covering order each, and left the guard unarmed whenever the audit row
  failed to write. A refused dispatch **releases** the claim, or that leg is
  skipped by its stop loss, its target and every square-off for the rest of the
  session while the broker still holds it.
- **Match a fill to the order it belongs to, not to the leg.** A signal flip
  squares one side and opens the other immediately, so one leg id names two
  positions until the closing order fills. Applying an exit fill by leg alone
  closed the position that had just been opened, and it then vanished from
  `open_legs` entirely: no stop, no square-off, still held.
- **A caller that has already decided the pipe says so.** `place_order_with_auth`
  reads the platform-wide analyzer toggle before anything else, so an operator
  switching to analyze mode while a live run held real positions sent every exit
  to the sandbox, which reports success. `force_live=True` opts out. Anything
  executing a position it opened must pass it.

The same shape applies wherever a stop is finalised: a stop whose exit orders
were refused must leave the run **open and managed**, because the position is
still there. Reporting success and clearing the state is how a position ends up
with nothing watching it.

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

### Nothing may block or be blocked across the eventlet boundary

Production is `gunicorn --worker-class eventlet -w 1`. Eventlet monkey-patches
the stdlib **before the app is imported**, so `threading.Lock`, `RLock`,
`Event`, `Condition` and `queue.Queue` are all **green**: they belong to the hub
and can only pass a waiter from one greenlet to another. A plain
`threading.Thread` is green too, and so is anything built on it, including
`ThreadPoolExecutor` and APScheduler's workers.

**A handful of threads are genuinely real**, and they are where this goes wrong:
the asyncio loop in `services/websocket_client.py` (asyncio cannot run on a
green thread), the Telegram bot thread and its Kaleido renderer, and the broker
snapshot feed threads in `broker/hdfcsecurities|hdfcsky/api/data.py`. Every
crossing that has ever bitten this project involved one of those.

Two directions, both fatal, both invisible on the dev server:

**A. A real thread touches a green primitive.** The hub tries to resume a waiter
belonging to another OS thread and raises `greenlet.error: Cannot switch to a
different thread` inside `fire_timers`, leaving that thread blocked **forever**.
Measured: the real thread never acquires the lock, not once, not ever.

**B. A greenlet blocks on a real primitive, or on any wait served by C code.**
The entire worker stops until it returns, because there is only one.

There is also a quieter third failure, which is the one that hides longest:
**the waiter is simply never woken**, so it sits out its whole timeout and then
succeeds or fails on data that was ready all along. A green `Event` set from a
real thread does this. So does `concurrent.futures.Future.result()`, which is
what `asyncio.run_coroutine_threadsafe` hands back: measured, an ack that
arrived in 0.3s still cost the caller its full 10s timeout.

**The rules:**

- **Do not run subscriber callbacks on a real thread.** `websocket_client` marshals them onto a real `Queue` that a green thread drains, because those callbacks reach SocketIO, the event bus, the sandbox engine and the database, all of which are eventlet-managed. Any new callback registered there inherits that safety; do not add one that is called inline.
- **Use `utils/real_threading` for anything both worlds touch.** It exports `Lock`, `RLock`, `Event`, `Condition`, `Queue`, `Empty`, `Thread`, plus `wait_for(event, timeout)` and `join(thread, timeout)`, which poll and yield instead of blocking. It resolves to the unpatched originals under eventlet and the stdlib otherwise.
- **Keep a real lock's critical section to in-memory bookkeeping.** A greenlet waiting on one blocks the hub, so copy what you need out of the dict and do the database and network work after the release.
- **Never wait on a C-served timeout.** `PRAGMA busy_timeout` was the worst case: SQLite waits inside C, so the greenlet holding the write lock could never be scheduled to commit, and the wait could only ever end in "database is locked". A holder needing 0.5s produced a 16s failure. `database/__init__.py` now waits 100ms in SQLite and retries from Python.
- **Never hand a result across with `run_coroutine_threadsafe`.** Use `WebSocketClient._run_on_loop`: a real `Event` the loop thread sets, polled by the caller. One boolean is the only thing that crosses.
- **Logging counts.** `logging.Handler` builds its lock in `__init__`, which happens after monkey-patching, so it is green, and every real thread in this project logs. `utils/logging.py` patches `Handler.createLock` on the class so ours and third-party handlers all get a real lock. The give-away that this has broken is `AttributeError: 'StreamHandler' object has no attribute 'lock'` appearing on unrelated requests, hours before the hard crash.

**What is exempt.** Under eventlet `app.py` starts the websocket proxy as a
**child process**, so everything in `websocket_proxy/` and `broker/*/streaming/`
runs unpatched and its `threading.Lock` is already real. Do not "fix" those.

**It cannot be caught locally.** `uv run app.py` never patches anything, so every
one of these behaves correctly on the dev server whatever the primitive is made
of. This is the same trap as `asyncio` above, and it is why
`test/test_eventlet_cross_thread_locks.py` and
`test/test_sqlite_lock_cooperative.py` run eventlet **in a subprocess**
(`monkey_patch()` is global and cannot be undone) and assert on **elapsed time
and hub liveness**, not just return values, which were always right. Each file's
first test asserts the defect itself so it cannot pass vacuously. Add to them
rather than starting a third.

Reported as issues #1402, #1473 and #1569; the symptom users describe is the
first order working and the next one hanging the app, with the order itself
having taken milliseconds.

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

### Custom chart indicators are loaded at runtime, never bundled

User indicators live in `strategies/indicators/*.js` (gitignored, mirroring
`strategies/scripts/` for Python strategies, and inside the same Docker volume).
`blueprints/custom_indicators.py` serves them; the chart fetches the index and
`import()`s each one after the built-in tier
(`frontend/src/lib/trading/customIndicators.ts`).

- **Never bundle them.** `frontend/dist/` is built by CI from what is committed, so a bundled indicator would need committing first and the next `git pull` would erase it. Runtime loading keeps them outside the build: no Node.js, no rebuild, untouched by upgrades.
- **They register after the built-ins**, so a custom id that collides with one of the 102 built-ins overrides it.
- **They are not sandboxed.** An indicator runs on the app origin with the logged-in session and can reach `/api/v1/`. That matches the trust model of the Python strategy host, which already runs arbitrary user code, but it means an indicator from an untrusted source is as dangerous as any script.
- Use the **`chart-indicator`** skill to write one. It validates against the real library and refuses to install a file that errors.

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

**Schema changes need a migration script, not just a startup hook.** Users
upgrade with `cd upgrade && uv run migrate_all.py`, so every schema change ships
as a script in `upgrade/` registered in that file's `MIGRATIONS` list. Applying
the change from `init_db()` alone is *not* enough: seeding functions typically
only run against an empty table, so an existing installation keeps the old
schema forever and the change silently never reaches the ~290k live deployments.

- **Idempotent, and safe to re-run.** Check whether the change is already
  present (`PRAGMA table_info`) and return quietly if so.
- **Support `--status`** to report what would change without changing it.
- **Never clobber a value the user may have customised.** Guard the update on
  the old value, so an admin who has already set their own is left alone.
- **Backfill from the data, not from a default.** A new column defaulted
  uniformly is usually wrong for existing rows; derive each row's value from
  what the row already says.
- **SQLite limits shape the approach.** It cannot alter a `CHECK` constraint or
  add a `UNIQUE` column in place: rebuild the table (see
  `migrate_sandbox_trigger_pending.py`) or add a partial unique index instead.

Test it against a *copy of a real database forced back to the old schema*, not
only a fresh one. A migration that works on an empty database and fails on a
populated one is the common failure.

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
