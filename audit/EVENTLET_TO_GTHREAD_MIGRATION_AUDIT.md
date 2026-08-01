# OpenAlgo Eventlet-to-gthread Migration Audit

> **Validation notice (2026-08-01):** This report was independently validated against the tree. 15 of 18 findings were confirmed as stated. **Two contain errors — do not action them as written:**
>
> - **GT-07** is overstated. `PROCESS_LOCK = threading.RLock()` does exist at `blueprints/python_strategy.py:64` and guards the lifecycle entry points (start at `:423`, stop at `:606`, plus three more). The real finding is reader-coverage, not absent synchronization; severity P1, not P0.
> - **GT-14** states no caller of `clear_strikes_cache()` was found. One exists: `broker/paytm/database/master_contract_db.py:395`. The unbounded-key-space concern still stands.
> - Inventory counts are inflated: `socketio.emit` is **123 occurrences across 46 files** excluding tests, not 132/49.
> - Coverage gaps: the Sandbox/Analyzer engine, `utils/httpx_client.py`, `limiter.py`, rollback planning, and broker rate-limiter thread costs are not covered here.
>
> Corrections and gap closure live in [`docs/plans/2026-08-01-eventlet-to-gthread-migration-plan.md`](../docs/plans/2026-08-01-eventlet-to-gthread-migration-plan.md) §8. Use the plan as the work list; use this report as the evidence base.

> **Generated:** August 1, 2026  
> **Scope:** Retain Flask and Flask-SocketIO; replace Gunicorn's eventlet worker with its gthread worker. This audit covers deployment, Socket.IO/WebSocket behavior, MCP HTTP/SSE, `websocket_proxy/`, Telegram and WhatsApp, broker streaming clients, background threads/executors, shared in-memory state, SQLite, resource usage, tests, and operational diagnostics.  
> **Method:** Static code and lifecycle review of the current `main` tree at `6577c782a`, inspection of the installed dependency implementations, repository-history review, and comparison with current official Gunicorn, Flask-SocketIO, python-engineio, python-socketio, and cachetools documentation. No live broker, concurrency load, or 24-hour soak test was run.  
> **Verdict:** **gthread is a viable long-term Flask runtime for OpenAlgo's current single-user, one-worker deployment, but the current tree is not ready for a one-flag production switch.** Complete the correctness gates in this report, then canary and soak-test the migration.

---

## 1. Executive summary

The runtime choice is sound:

- OpenAlgo remains a WSGI Flask application.
- `extensions.py:6-18` already forces Flask-SocketIO's `async_mode="threading"`.
- `simple-websocket==1.1.0` is already pinned in `pyproject.toml:127` and both requirements files, which is the package used to provide WebSocket support in threading mode.
- Gunicorn 26.0.0 retains gthread and removed the eventlet worker, explicitly directing users to gthread, gevent, or another supported worker.
- Flask-SocketIO's current deployment guide explicitly supports Gunicorn's threaded worker with `simple-websocket`, using one worker and a large thread pool.

The migration is nevertheless more than changing one CLI flag because eventlet currently suppresses or serializes real OS-thread concurrency across large parts of the process. gthread exposes existing shared-state assumptions and gives every long-lived WSGI stream a finite thread cost.

### Production decision

| Decision | Assessment |
| --- | --- |
| Keep Flask | Correct for the requested scope |
| Use Gunicorn gthread | Recommended |
| Keep Flask-SocketIO | Supported and appropriate |
| Keep `-w 1` | Required until a Socket.IO message-queue backplane and sticky sessions are added |
| Move to Uvicorn | Not part of this migration; it would require an ASGI/realtime-layer migration |
| Switch immediately by changing only `--worker-class` | **No-go** |
| Switch after the P0 gates and load tests below | **Go** |

### Highest-risk gaps

1. A gthread worker defaults to one thread unless `--threads` is set. OpenAlgo has two infinite SSE endpoints, Socket.IO long-poll/WebSocket clients, and internal HTTP loopbacks. One or a small number of threads can deadlock or starve the application.
2. `socketio.emit()` is called concurrently from request threads, a 10-worker EventBus, schedulers, and bot/background workers. The underlying python-socketio API states that concurrent emits to a client are not thread-safe.
3. The symbol master cache is rebuilt in place without synchronization. Reordering `cache_loaded = False` is not a complete fix.
4. Twelve active modules use shared `cachetools.TTLCache` objects without locks even though cachetools explicitly documents that these cache classes are not thread-safe. The auth/token caches are on the live-order path.
5. SQLite has WAL and `busy_timeout=15000`, but there is no `SQLITE_BUSY_SNAPSHOT` transaction retry. Native request and background threads increase concurrent writers.
6. Native Ubuntu installs silently move `websocket_proxy/` from a subprocess into the Gunicorn worker when eventlet disappears. That also exposes unlocked proxy registries to Flask request threads.
7. Python Strategy process/config registries are shared between request and scheduler threads without a lifecycle lock.
8. MCP's per-token quota, audit-log rotation, infinite SSE stream, and same-server HTTP loopback all need gthread-specific hardening.

---

## 2. Authoritative support position

The long-term support case does not depend on inference:

- [Flask-SocketIO deployment documentation](https://flask-socketio.readthedocs.io/en/stable/deployment.html) describes Gunicorn's threaded worker plus `simple-websocket` as a supported production option and gives `gunicorn -w 1 --threads 100 module:app` as its example.
- [Flask-SocketIO requirements documentation](https://flask-socketio.readthedocs.io/en/latest/intro.html) describes standard threading as the easiest and most compatible mode, with both long-polling and WebSocket transport support, and notes that eventlet is no longer actively maintained.
- [python-engineio server documentation](https://python-engineio.readthedocs.io/en/latest/server.html) states that `simple-websocket` supports WebSocket on Gunicorn's threaded worker and that the configured thread count bounds concurrent clients.
- [Gunicorn's current changelog](https://gunicorn.org/news/) records that 26.0.0 removed the eventlet worker and directs migrations to gthread, gevent, or tornado.
- [Gunicorn's gthread design](https://gunicorn.org/design/) retains gthread as its standard WSGI thread-pool worker.

This is enough to treat gthread as a durable Flask runtime rather than a temporary bridge. The limiting architecture remains the one-process Socket.IO state and SQLite write concurrency, not WSGI itself.

---

## 3. Current runtime inventory

Static inventory of the current tree:

| Surface | Count | Observation |
| --- | ---: | --- |
| Python files containing `eventlet` references | 40 | Many are compatibility comments or guarded fallbacks; production behavior changes wherever detection becomes false |
| `socketio.emit` occurrences | 132 across 49 files | Multiple independent producer threads can emit concurrently |
| `socketio.start_background_task` occurrences | 7 across 3 files | Each becomes a new daemon OS thread in threading mode |
| `ThreadPoolExecutor` occurrences | 56 across 25 files | Several module-level pools become real native pools; some request paths create nested pools |
| `threading.Thread` occurrences | 181 across 80 files | Includes lifecycle declarations and actual creation sites |
| SSE endpoints | 2 | `/python/api/events` and `GET /mcp`; each connection is infinite |
| Frontend Socket.IO constructors | 4 | All force `transports: ['polling']` and `upgrade: false` |
| Active modules with unprotected shared `TTLCache` objects | 12 | Cachetools does not make these mappings thread-safe |

The numbers are an inventory, not a claim that every occurrence is defective.

---

## 4. Blocking findings

### [GT-01] Thread-pool starvation is a hard capacity constraint

**Severity:** P0, required before cutover  
**Locations:**

- `blueprints/python_strategy.py:2325-2370`
- `blueprints/mcp_http.py:671-709`
- `frontend/src/hooks/useSocket.ts:149-157`
- `frontend/src/hooks/useOrderEventRefresh.ts:125-133`
- `frontend/src/pages/ActionCenter.tsx:142-150`
- `frontend/src/pages/whatsapp/WhatsAppIndex.tsx:61-73`
- `blueprints/mcp_http.py:203-269`

`--worker-class gthread` without `--threads` is effectively a one-request worker. Each open SSE response holds a request thread forever. A Socket.IO WebSocket holds a thread; long-polling also keeps request threads outstanding for much of each connection's lifetime. MCP tool dispatch additionally calls the OpenAlgo SDK back through `HOST_SERVER`, so one external MCP call temporarily needs an outer request thread and another free request thread for the internal `/api/v1/*` call.

Consequences of undersizing include:

- `/health`, login, and order endpoints stop responding while streams remain healthy;
- an MCP call waits on its own saturated server;
- Telegram/WhatsApp commands that call the local SDK stall;
- a browser can appear connected while ordinary HTTP is starved.

**Required remediation:**

- Keep `--workers 1`.
- Set an explicit configurable thread count on every deploy surface. A reasonable canary starting point is 32, with 64 evaluated under load; neither number is approved until the acceptance test passes.
- Size from connection demand, not CPU count:

  ```text
  required threads >=
      active Socket.IO transports
    + active Python Strategy SSE streams
    + active MCP SSE streams
    + internal loopback reserve
    + peak ordinary HTTP concurrency
    + failure/reconnect reserve
  ```

- Reserve at least two free request threads when MCP HTTP is enabled because dispatch re-enters the same application.
- Add saturation metrics: configured threads, active requests, active Socket.IO clients, active SSE clients, and rejected/queued work.

Do not apply Gunicorn's generic CPU-based thread formula blindly. Long-lived streams, internal loopbacks, and SQLite writers define OpenAlgo's budget.

### [GT-02] Concurrent server-side Socket.IO emits are not serialized

**Severity:** P0, live-event correctness  
**Locations:** 132 `socketio.emit` calls across 49 files; high-concurrency sources include:

- `utils/event_bus.py:33-58` (10 worker threads)
- `subscribers/socketio_subscriber.py`
- `services/historify_service.py`
- `services/historify_scheduler_service.py`
- `services/scalping_risk_monitor_service.py`
- `services/telegram_bot_service.py`
- `services/whatsapp_bot_service.py`
- request handlers in `blueprints/`

`subscribers/socketio_subscriber.py:5-6` currently says `socketio.emit()` is thread-safe. That assertion conflicts with the [current python-socketio server API](https://python-socketio.readthedocs.io/en/stable/api_server.html), which warns that concurrent emits to the same client are not thread-safe and may interleave multi-packet messages.

Eventlet made many producers cooperatively serialized. gthread allows true simultaneous calls from the EventBus, request pool, APScheduler pools, order-update threads, and bot threads.

**Required remediation:**

- Introduce one central server-originated emit function protected by a process-wide `threading.RLock`, or an equivalent single-consumer emit queue.
- Route background/request/subscriber emits through that boundary.
- Preserve context-bound `flask_socketio.emit()` behavior inside Socket.IO handlers where appropriate, but ensure it cannot race background broadcasts to the same client.
- Add an ordering stress test that emits distinct sequence numbers concurrently and verifies no loss, duplication, corruption, or reordering at the browser client.

The existing `socketio.start_background_task(socketio.emit, ...)` calls do not serialize emits; under threading mode they create more competing native threads.

### [GT-03] Symbol cache reload is not thread-safe; the proposed one-line fix is insufficient

**Severity:** P0, order-symbol correctness  
**Locations:**

- `database/token_db_enhanced.py:139-309`
- `database/token_db_enhanced.py:695-708`
- public read paths at `database/token_db_enhanced.py:737-830` and `:971-1219`
- direct read path at `services/search_service.py:46-75`

`BrokerSymbolCache.load_all_symbols()` calls `clear_cache()` and repopulates multiple dictionaries in place. `clear_cache()` clears nine structures before setting `cache_loaded = False`. Moving the flag assignment to the first line closes one window but not all windows:

1. A reader can observe `cache_loaded == True` immediately before the loader flips it.
2. That reader can then iterate or query dictionaries while another thread clears and repopulates them.
3. Search and expiry functions iterate dict/set views, so they can return partial data or raise a mutation-during-iteration error.
4. Two concurrent reload triggers can interleave entire broker snapshots.

**Required remediation:**

- Build a complete immutable/cache-state object off to the side and atomically replace a single state reference after success; serialize writers with a load lock.
- Alternatively use a read/write locking design, but do not hold a global read lock across the multi-second 150k-symbol build if it blocks live order lookups.
- Ensure failed loads retain the previous valid snapshot rather than leaving an empty cache.
- Make singleton construction safe or instantiate the singleton eagerly before worker threads start.
- Add concurrent reload/read tests for single lookup, bulk lookup, search, F&O search, expiry, and underlying lists.

### [GT-04] Shared `TTLCache` objects are not protected

**Severity:** P0 for auth/order-mode caches; P1 for the remaining modules  
**Primary locations:**

- `database/auth_db.py:145-159`
- `database/settings_db.py:20-22`
- `database/user_db.py:57-58`
- `database/traffic_db.py:55-58`
- `database/flow_db.py:26-28`
- `database/strategy_db.py:13-16`
- `database/market_calendar_db.py:32-34`
- `database/leverage_db.py:17`
- `database/latency_db.py:39-41`
- `database/telegram_db.py:37-42`
- `database/whatsapp_db.py:57-61`
- `utils/trading_calendar.py:30-32`

The [cachetools documentation](https://cachetools.readthedocs.io/en/latest/) explicitly states that its cache classes are not thread-safe and shared access must be synchronized. None of the 12 active modules above defines a lock for its cache mappings.

The `auth_db` caches are especially sensitive. They hold authentication records, feed tokens, broker selection, verified/invalid API-key results, and auto/semi-auto order mode. Concurrent lookup, expiry eviction, clear, delete, and write operations become native-thread races under gthread.

**Required remediation:**

- Protect every operation on each shared cache, including compound `if key in cache` then get/delete/write sequences and global invalidations.
- Prefer one `RLock` per coherent cache group; keep external DB/Argon2/network work outside the cache lock and re-check before publishing a result.
- Add same-key concurrency tests and invalidation-during-read tests, especially for API key regeneration, broker token rollover, logout, and order-mode changes.

`services/indicator_service.py` is the correct local example: its `TTLCache` and single-flight registry already have dedicated locks.

### [GT-05] SQLite needs transaction retry, not only `busy_timeout`

**Severity:** P0, live-order durability  
**Locations:**

- `database/__init__.py:1-67`
- `database/engine_factory.py:35-59`
- all request/background writers using the shared SQLite databases

The current foundation is good: WAL, `synchronous=NORMAL`, a 15-second busy timeout, `NullPool`, and `check_same_thread=False` are process-wide. The code comments correctly state that `busy_timeout` does not recover `SQLITE_BUSY_SNAPSHOT`, which returns immediately and requires restarting the transaction. No repository retry helper currently handles that case.

gthread increases simultaneous writers from request threads, the EventBus, API/analyzer/traffic/latency executors, bot services, schedulers, and the proxy process. A larger thread count must not be allowed to translate directly into uncontrolled SQLite writers.

**Required remediation:**

- Add a bounded, jittered transaction retry for retryable SQLite busy/locked errors, with a fresh session/transaction for each attempt.
- Apply it to idempotent database mutations on critical auth, order-log, settings, strategy, OAuth/MCP, and session paths; do not blindly retry external broker orders.
- Keep high-volume log writers serialized where already designed (`traffic-log`, `latency-log`). Consider serializing additional non-critical log writes instead of increasing parallelism.
- Test concurrent login/token refresh, MCP writes, Socket.IO events, strategy state updates, and order logging against the same SQLite file.

The retry boundary must surround only the local database transaction. A broker order must never be placed twice because a post-order local write was retried at too broad a level.

### [GT-06] Native installs silently change WebSocket-proxy topology

**Severity:** P0 for native Ubuntu/systemd deployments  
**Locations:**

- `websocket_proxy/app_integration.py:25-31`
- `websocket_proxy/app_integration.py:158-253`
- `websocket_proxy/app_integration.py:255-327`
- `app.py:995-1012`
- `start.sh:299-305`
- `websocket_proxy/broker_factory.py:19-20,132-183,299-373`

Docker explicitly starts `python -m websocket_proxy.server` as a separate process, so Docker topology remains stable. Native installs rely on `start_websocket_proxy(app)`. Today `_eventlet_active()` chooses a child process. Under gthread it returns false and chooses an in-process asyncio thread.

The eventlet/greenlet crash that motivated the subprocess disappears, but production topology still changes as an unrelated side effect. In-process mode also means Flask request threads and the proxy thread can touch `_POOLED_ADAPTERS`, whose create/reuse/remove/stats/cleanup operations have no registry lock.

**Required remediation:**

- Replace eventlet detection as the topology switch with an explicit mode, for example `WEBSOCKET_PROXY_MODE=external|subprocess|thread`.
- Use `external` in Docker, `subprocess` in native Gunicorn/systemd production, and `thread` only for the development server.
- Preserve process-group/systemd cleanup and the SUB-binds/PUBs-connect invariant.
- If in-process mode is ever enabled in production, add registry synchronization and lifecycle tests first.

Keeping the subprocess is the lowest-blast-radius migration. It avoids coupling the gthread cutover to proxy registry and asyncio lifecycle changes.

### [GT-07] Python Strategy registries need a lifecycle lock

**Severity:** P0 because hosted strategies can place live orders  
**Locations:**

- `blueprints/python_strategy.py:61-68`
- mutations and iterations of `RUNNING_STRATEGIES` and `STRATEGY_CONFIGS` throughout the module
- request routes and the APScheduler jobs initialized at `blueprints/python_strategy.py:110-153`

`RUNNING_STRATEGIES` and `STRATEGY_CONFIGS` are plain process-wide dictionaries. The SSE subscriber list has a lock, but strategy configuration and process lifecycle do not have an equivalent global/per-strategy synchronization boundary. With gthread, start, stop, delete, restore, cleanup, and scheduled transitions can execute concurrently on native threads.

Possible outcomes include double starts, stopping a replacement process through a stale reference, lost configuration updates, and iteration/mutation errors.

**Required remediation:**

- Add a registry lock plus a per-strategy lifecycle lock or make one owner thread/queue responsible for lifecycle transitions.
- Never hold a global lock while waiting for a child process to exit.
- Test simultaneous manual start/stop/delete against scheduled start/stop and dead-process cleanup.

### [GT-08] MCP has several conditional blockers under gthread

**Severity:** P0 when `MCP_HTTP_ENABLED=TRUE`; otherwise P1  
**Locations:**

- quota: `blueprints/mcp_http.py:112-138`
- initialization: `blueprints/mcp_http.py:198-269`
- audit log: `blueprints/mcp_http.py:344-368`
- synchronous loopback dispatch: `blueprints/mcp_http.py:203-269,615-644`
- SSE: `blueprints/mcp_http.py:671-709`

Findings:

1. `_scope_quota` uses an unlocked read-modify-write sequence. Concurrent write-scope requests can over-admit or miscount live-order calls.
2. Expired bucket entries are removed only when the same `(jti, scope)` is used again. Quiet token keys remain forever, so the registry has unbounded key-space growth.
3. `_audit_log()` appends and then performs read/replace rotation without a lock. Concurrent requests can lose or overwrite audit lines during rotation.
4. `_initialized` is an unlocked check-then-act guard. Normal app startup does not call it; the first MCP requests do.
5. `GET /mcp` is an infinite SSE stream that pins one gthread thread per client even though v1 does not send notifications.
6. Tool dispatch synchronously calls the same OpenAlgo server through the SDK. Pool saturation can self-deadlock the call.

**Required remediation:**

- Lock quota decisions and bound/prune the whole registry.
- Serialize audit append/rotation or move it onto a single log writer.
- Protect first initialization with a lock or complete it before serving requests.
- Track MCP SSE connections and include them in thread admission/capacity checks.
- Prove MCP dispatch still succeeds while Socket.IO and SSE connections occupy their configured maximum.
- Consider disabling the optional GET stream when notifications are not used, if protocol/client compatibility permits; do not assume this without contract testing.

---

## 5. High-priority compatibility and hardening findings

### [GT-09] Four broker data adapters change production execution path

**Severity:** P1 compatibility gate  
**Locations:**

- `broker/flattrade/api/data.py:18-27,521-537`
- `broker/definedge/api/data.py:16-25,533-550`
- `broker/shoonya/api/data.py:16-25,418-434`
- `broker/zebu/api/data.py:16-25,373-388`

These modules define `USE_ASYNC = not _is_eventlet_patched()`. Under gthread, production batch quote requests switch from `ThreadPoolExecutor` to `asyncio.run()` plus per-call `httpx.AsyncClient`. The async clients are context-managed, so no static FD leak was found, but this is a real production behavior change and not merely removal of an eventlet workaround.

**Required validation:** live or broker-sandbox batch quote, option-chain, timeout, rate-limit, exception aggregation, and repeated-call FD/RSS tests for all four brokers.

### [GT-10] Telegram's non-eventlet initialization becomes the production path

**Severity:** P1 compatibility/lifecycle  
**Locations:**

- `app.py:894-942`
- `services/telegram_bot_service.py:541-630,796-845`
- `blueprints/telegram.py:92-156`
- `test/test_telegram_startup.py:15-108`

The long-running Telegram bot already owns a real OS thread and isolated asyncio loop, which fits gthread well. The risk is the newly promoted initialization branch:

- the route starts an untracked thread and joins it for 10 seconds;
- after timeout, the thread continues and may update service/config state after the route reports failure;
- an immediate retry can start a second initializer;
- the only dedicated startup test monkey-patches eventlet and therefore tests the old branch.

**Required remediation/validation:** make initialization single-flight with an owned future/event and test start, timeout, retry, stop, restart, startup auto-restore, and Kaleido rendering without eventlet.

### [GT-11] WhatsApp is structurally compatible but depends on request-thread headroom

**Severity:** P1 validation  
**Locations:** `services/whatsapp_bot_service.py`

The WhatsApp service already owns its state through native locks, queues, events, and dedicated pairing/bot threads. Removing eventlet makes this model more natural. No migration-specific shared-state defect was found in the reviewed ownership boundary.

WhatsApp command handling calls the local OpenAlgo SDK through `HOST_SERVER`, so it requires a free gthread request thread. Validate pairing, reconnect, inbound callbacks, command dispatch, media send, stop, and session restore while HTTP/SSE/Socket.IO load is present.

### [GT-12] Seven `start_background_task(emit)` sites create one native thread per event

**Severity:** P1 resource/performance  
**Locations:**

- `services/order_router_service.py:120`
- `services/openposition_service.py:39,114`
- `services/orderstatus_service.py:40,124,173,267`

Inspection of the installed Flask-SocketIO/python-socketio/python-engineio stack confirms that `start_background_task()` constructs and starts an Engine.IO daemon thread in threading mode. These seven sites use it only to call `socketio.emit()` once.

This is bounded by event rate rather than a persistent leak, but a burst creates avoidable thread churn and worsens the concurrent-emit problem.

**Required remediation:** route these notifications through the serialized emit boundary from GT-02; do not spawn a thread solely to call `emit()`.

### [GT-13] EventBus worker sessions need deterministic cleanup

**Severity:** P1 resource/state hygiene  
**Locations:**

- `utils/event_bus.py:33-66`
- `subscribers/strategy_book_subscriber.py:37-163`
- `subscribers/wsproxy_subscriber.py:17-91`
- convention in `utils/db_sessions.py:1-70`

The EventBus has ten persistent native workers under gthread. Some subscribers query/write scoped SQLAlchemy sessions. `_safe_call()` catches errors but has no `finally` cleanup. The repository's own session registry says background/EventBus threads must call `remove_all_scoped_sessions()`.

NullPool prevents an unlimited idle connection pool, but a persistent scoped session can retain transaction/identity-map state and violate the documented lifecycle boundary.

**Required remediation:** call `remove_all_scoped_sessions()` in `EventBus._safe_call()`'s `finally` block and test success and exception paths.

### [GT-14] Other mutable caches/registries need targeted hardening

**Severity:** P1/P2 depending on path  
**Locations:**

- `database/qty_freeze_db.py:41-44,127-184` — in-place cache reload with no lock; used for order split/freeze sizing.
- `services/option_symbol_service.py:49-75,299-370` — unlocked strike cache/stats; no caller of `clear_strikes_cache()` was found; key-space is unbounded over the process lifetime.
- `websocket_proxy/broker_factory.py:19-20,132-183,299-373` — unlocked global pool registry; avoid production in-process use or add a registry lock.
- `services/websocket_client.py:543-582` — client registry is locked and has a global close path; verify API-key rotation removes obsolete clients.
- `services/flow_executor_service.py:30-40` — workflow lock registry creation is protected, but lock entries have no removal path and grow with workflow IDs.

For the quantity cache, use copy-on-write or locking before gthread because wrong/default freeze quantities can change order splitting. Bound the strike and workflow-lock registries and pair every registry insertion with invalidation/removal.

### [GT-15] Native thread count will be materially higher than the Gunicorn `--threads` value

**Severity:** P1 capacity/resource  

Gunicorn threads are only one part of the process. The application also creates an EventBus pool, API/analyzer log pools, traffic and latency writers, Telegram/WhatsApp alert pools, historify/flow workers, APScheduler executors, bot threads, order-update adapters, broker SDK threads, and occasional request-scoped broker fan-out pools.

The final OS-thread budget can exceed 100 even with `--threads 32`. This is not automatically wrong, but it affects stack virtual memory, scheduler overhead, host thread limits, SQLite writer concurrency, and Docker's prior RLIMIT_NPROC/OpenBLAS mitigations.

**Required validation:** sample process thread count, RSS/VSZ, FDs, CPU context switches, executor queue depth, and SQLite busy retries at idle and under peak workflows. Nested `ThreadPoolExecutor` fan-out should have explicit broker limits and must not be multiplied accidentally by many simultaneous gthread requests.

---

## 6. Deployment and operations gaps

### [GT-16] Every deploy surface must change consistently

**Severity:** P0 rollout integrity

Current eventlet/Gunicorn-25 coupling exists in:

- `Dockerfile:8-13`
- `requirements-nginx.txt:148-149`
- `start.sh:327-341`
- `install/install.sh:766-776,1151-1157`
- `install/install-multi.sh:310-311,605-611`
- `install/update.sh:445-453`
- `CONTRIBUTING.md:183,1059`
- `CLAUDE.md:60-70` and related eventlet runtime/topology statements

Recommended target shape after correctness fixes:

```text
gunicorn>=26.0,<27
gunicorn --worker-class gthread --workers 1 --threads ${GUNICORN_THREADS:-32} ... app:app
```

Additional rollout requirements:

- Remove eventlet from `requirements-nginx.txt` and fresh-install commands.
- Existing updater installs with `uv pip install -r` do not necessarily prune an extraneous eventlet package; uninstall it explicitly or use a sync/prune workflow.
- Keep `simple-websocket` pinned.
- Preserve nginx's dedicated `/socket.io/` upgrade locations; official install scripts already contain them.
- Preserve `--timeout 300` initially. Gunicorn gthread workers continue heartbeating while individual requests run, but the behavior must be verified with both infinite SSE endpoints.
- Keep `--graceful-timeout 30` only if forced disconnect/reconnect of long-lived clients during deploy is accepted and tested.
- Do not add workers above one without Redis/message-queue coordination and sticky sessions.

### [GT-17] Runtime diagnostics and tests still describe eventlet

**Severity:** P2 operations/documentation  
**Locations:**

- `blueprints/admin.py:1205-1232,1698-1704`
- `frontend/src/types/admin.ts:142`
- `test/test_telegram_startup.py`
- `test/test_python_strategy_edge_cases.py`
- `.github/workflows/ci.yml:268-271`
- eventlet-specific comments throughout adapters/services

Under gthread, `_runtime_info()` reports `wsgi_hint="flask-dev"` because it only recognizes active eventlet. Diagnostics should report Gunicorn version, worker class, configured threads, active thread count, active Socket.IO/SSE counts, and proxy mode.

Replace the eventlet-only Telegram startup test with gthread-path tests. Retain only narrowly useful eventlet regression tests if eventlet remains a supported development dependency; otherwise remove that dependency and obsolete tests together.

---

## 7. Frontend transport finding

### [GT-18] WebSocket capability exists but the frontend disables it everywhere

**Severity:** P1 performance/coverage; not a prerequisite for a polling-only canary

All four Socket.IO constructors force:

```ts
transports: ['polling'],
upgrade: false,
```

The comment in `frontend/src/hooks/useSocket.ts:149` says WebSocket upgrade fails in threading mode, but current Flask-SocketIO/python-engineio documentation and the pinned `simple-websocket` package support it on Gunicorn gthread.

Implications:

- Switching to gthread while retaining the frontend pin does not validate WebSocket support.
- Polling still consumes long-lived request capacity and adds repeated HTTP overhead.
- Removing all four pins in the same deployment as the worker migration changes two variables at once.

**Recommended rollout:**

1. Canary gthread with the current polling transport to isolate runtime correctness.
2. Add automated WebSocket-upgrade coverage through each official nginx topology.
3. Remove the pin at one shared/representative client, observe reconnects and event ordering, then migrate the remaining call sites.
4. Prefer a single shared Socket.IO connection per browser tab where page architecture permits; multiple constructors can multiply thread use.

---

## 8. Subsystem viability matrix

| Subsystem | Long-term on gthread? | Current readiness | Required work |
| --- | --- | --- | --- |
| Flask REST/UI | Yes | Conditional | Thread-safe shared caches/state; SQLite retry |
| Flask-SocketIO polling | Yes | Conditional | Explicit thread budget; emit serialization |
| Flask-SocketIO WebSocket | Yes, officially supported | Unproven in this repo because frontend disables it | nginx + `simple-websocket` end-to-end tests, then staged enablement |
| MCP POST/JSON-RPC | Yes at current scale | Conditional blocker when enabled | quota/init/audit locks; loopback headroom |
| MCP SSE | Technically yes, capacity-expensive | Not safe with a small pool | connection accounting/admission and load test |
| `websocket_proxy/` Docker | Yes | Topology already separate | Regression and shutdown tests |
| `websocket_proxy/` native install | Yes | Not ready | explicit subprocess mode; do not silently move in-process |
| Telegram polling bot | Yes | Likely compatible, new production branch untested | single-flight init and lifecycle tests |
| WhatsApp bot | Yes | Structurally compatible | load/lifecycle tests; loopback headroom |
| Broker market-data adapters | Yes | Most have native-thread fallbacks already | reconnect/stop tests; four broker data paths change to asyncio |
| Order-update adapters | Yes | Registry already locked | broker matrix and shutdown tests |
| EventBus | Yes | Needs cleanup and emit serialization | session cleanup in worker `finally` |
| Python Strategy Host | Yes | Shared lifecycle state not ready | registry/per-strategy locking |
| Flow/Historify/schedulers | Yes | Mostly designed for native threads | TTL cache locks, worker/DB stress tests |
| SQLite | Yes for current single-user scale | Conditional | bounded transaction retry and measured writer contention |
| Multiple Gunicorn workers | Not with current in-process Socket.IO state | Out of scope | Redis/message queue, sticky sessions, broader architecture work |

---

## 9. Recommended migration sequence

### Phase A — correctness gates

1. Serialize server-originated Socket.IO emits and remove one-shot emit threads.
2. Make symbol-cache reload atomic and serialize writers.
3. Protect auth/order-mode and all active shared TTL caches.
4. Add bounded SQLite transaction retry at safe local-transaction boundaries.
5. Add Python Strategy lifecycle synchronization.
6. Harden MCP quota, initialization, audit logging, and registry cleanup.
7. Make WebSocket-proxy mode explicit and preserve subprocess isolation in production.
8. Add EventBus scoped-session cleanup.

### Phase B — deployment cutover

1. Pin `gunicorn>=26.0,<27` in server/Docker dependencies.
2. Remove eventlet from production and ensure updaters prune the old package.
3. Change every official command to one gthread worker with configurable threads.
4. Update runtime diagnostics, repository constraints, and contributor commands.
5. Keep frontend polling during the first canary.

### Phase C — validation and realtime upgrade

1. Run contract/unit/concurrency tests with no eventlet imported.
2. Canary with polling at 32 threads; test 64 only if measured headroom requires it.
3. Exercise MCP, both SSE endpoints, bots, strategies, and live Socket.IO events concurrently.
4. Enable WebSocket upgrade in stages after dedicated tests pass.
5. Complete a 24-hour FD/RSS/thread/SQLite-contention soak.

---

## 10. Acceptance test matrix

The migration is ready only when all applicable gates pass.

### Runtime and deployment

- Docker, native single install, multi-instance install, and updater all run Gunicorn 26 gthread with one worker and the configured thread count.
- No production process imports or monkey-patches eventlet.
- Runtime diagnostics identify gthread and show configured/active thread counts.
- SIGTERM and restart cleanly stop Socket.IO clients, SSE streams, bot threads, broker adapters, the proxy subprocess, ZMQ resources, and executors within the configured grace period.

### HTTP, SSE, and internal loopbacks

- With the expected maximum Socket.IO, Python SSE, and MCP SSE clients connected, `/health`, login, and a harmless API request retain defined p95/p99 latency.
- MCP tool dispatch completes while streams are at the configured maximum; no self-deadlock occurs.
- Telegram and WhatsApp local-SDK commands complete under the same load.
- Disconnecting SSE clients returns their thread and removes subscriber/connection state.

### Socket.IO

- Polling works through every official nginx config without `Invalid session`, 400 responses, reconnect loops, or lost room membership.
- WebSocket upgrade works through every official nginx config before frontend pins are removed.
- Concurrent sequence-event stress proves no loss, corruption, duplication, or incorrect ordering.
- Multiple devices/tabs preserve the single shared broker feed invariant.

### Databases and shared state

- Concurrent local writers produce no unhandled `database is locked` or `SQLITE_BUSY_SNAPSHOT` errors.
- Retry tests prove only local DB transactions repeat; broker order calls remain exactly once.
- API-key regeneration/logout/token rollover cannot return stale auth/feed/broker/order-mode cache entries.
- Symbol-cache refresh serves either the complete old snapshot or complete new snapshot, never a partial mix.
- Manual/scheduled strategy lifecycle races cannot double-start or stop the wrong process.
- MCP quota admits exactly its configured count under a thread barrier and the registry remains bounded.

### Resource soak

- Process FD count, RSS, OS-thread count, EventBus/executor queue depths, Socket.IO rooms, SSE subscriber counts, MCP quota keys, and proxy/client registries plateau under repeated connect/disconnect/reconnect cycles.
- Repeat broker reconnect tests for the active broker and the four newly async batch-data brokers.
- Record baseline and final measurements; static review alone is not completion evidence.

---

## 11. Long-term viability and exit conditions

gthread remains a good long-term choice while these product invariants hold:

- one user/broker session per deployment;
- one Gunicorn worker;
- moderate browser, webhook, MCP, and strategy concurrency;
- broker latency dominates request latency;
- market ticks continue through the separate asyncio/ZMQ WebSocket proxy rather than the WSGI request pool;
- SQLite writer contention stays within measured limits.

Reconsider the runtime architecture when one of these becomes true:

1. OpenAlgo becomes multi-user or multi-tenant.
2. Socket.IO must scale across multiple worker processes or hosts.
3. Concurrent SSE/WebSocket clients routinely exceed a practical native-thread budget.
4. Broker/service paths are intentionally converted to async end to end.
5. SQLite remains the write bottleneck after transaction boundaries and writer serialization are corrected; the next step is PostgreSQL or a dedicated write owner, not Uvicorn by itself.

None of these conditions is present merely because eventlet is being removed. For the current product, a hardened gthread deployment is simpler and lower risk than pulling the FastAPI/ASGI migration forward.

---

## 12. Corrections to the original four-fix proposal

| Original proposal | Audit conclusion |
| --- | --- |
| Size threads for SSE | Correct but incomplete: include Socket.IO transports, MCP re-entry, bot loopbacks, ordinary HTTP reserve, and application-owned threads |
| Add a lock to MCP quota | Correct; also prune old keys, lock initialization and audit rotation, and load-test same-server loopback |
| Set `cache_loaded = False` before clearing | Necessary but insufficient; use an atomic snapshot/swap or a proper read/write synchronization design |
| Keep the proxy subprocess under Gunicorn | Correct; use an explicit production topology setting rather than eventlet detection |

The original list also missed Socket.IO emit serialization, unprotected TTL caches, Python Strategy lifecycle state, SQLite snapshot retry, promoted broker async paths, Telegram's promoted non-eventlet branch, EventBus session cleanup, and one-shot background emit threads.

---

## 13. Scope limitations

This was a static migration audit. It did not:

- place live or sandbox broker orders;
- start Gunicorn 26 against the full application;
- open real browser Socket.IO/WebSocket sessions;
- connect an MCP client;
- pair Telegram or WhatsApp;
- run a concurrency benchmark or 24-hour soak;
- mutate application, deployment, dependency, or test code.

Those activities are intentionally acceptance gates, not implied successes. The only repository change produced by this audit is this report.

