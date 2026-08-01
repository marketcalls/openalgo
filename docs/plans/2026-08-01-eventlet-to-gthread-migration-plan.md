# Eventlet to gthread — Migration Plan

**Status:** Design — not yet built
**Date:** 2026-08-01 (rev 5)
**Branch:** `gthread`
**Scope:** Replace Gunicorn's `eventlet` worker with its `gthread` worker. Keep Flask, keep Flask-SocketIO, keep `-w 1`.
**Evidence base:** [`audit/EVENTLET_TO_GTHREAD_MIGRATION_AUDIT.md`](../../audit/EVENTLET_TO_GTHREAD_MIGRATION_AUDIT.md), with the corrections in §10 applied.
**Row-level tracking:** [`2026-08-01-gthread-migration-tracker.csv`](2026-08-01-gthread-migration-tracker.csv) — 113 rows, each with decision, gate, test, rollback boundary and acceptance criterion.

---

## 1. Why

This is a **foundation migration, not a performance one**. Nobody should expect it to be faster; broker API latency dominates request latency and the WSGI server is not the ceiling.

What it buys:

1. **eventlet is deprecated and unmaintained.** It prints its own warning recommending migration.
2. **We are pinned out of the current Gunicorn major.** `gunicorn>=25.0,<26` in `Dockerfile:13` and three install scripts, because Gunicorn 26 removed the eventlet worker entirely (`SUPPORTED_WORKERS` = `asgi, gevent, gevent_pywsgi, gevent_wsgi, gthread, sync, tornado`). No security or bugfix updates until this lands.
3. **The "no asyncio in production" invariant disappears.** Today async work must be shunted onto real OS threads or subprocesses. That entire workaround category goes away.
4. **The dev/prod gap closes.** CLAUDE.md calls asyncio-works-locally-breaks-on-deploy "the single most common way a change passes locally and fails on deploy." Dev already uses threading; gthread makes production match.
5. **A class of bugs is eliminated, not mitigated** — `greenlet.error` cross-thread crashes (#1421), the heartbeat starvation behind #1419, psutil's patched-`select` breakage.
6. **CPU-bound work stops monopolising the process.** Under eventlet the 150k-row symbol cache build and Plotly rendering have no yield points and stall the whole hub. Under gthread they occupy one thread — though the GIL means heavy pure-Python CPU work still degrades every concurrent request. This is an improvement, not an escape from the GIL.
7. **WebSocket transport becomes available** for Socket.IO, currently disabled at all four frontend call sites.

What it does **not** buy: no throughput gain, no multi-worker scaling (still `-w 1`), and SQLite contention gets *worse* before the hardening makes it better.

**Independent justification for Phase A:** the hardening items below are latent defects that exist *today*, merely masked by eventlet's cooperative scheduling. That work has value even if the flag is never flipped. Note however that Phase A is **not behaviour-preserving** — emit serialization, quota locking, cache replacement and SQLite retry all change observable behaviour. Each must ship and revert independently.

### 1.1 Rejected alternatives

| Option | Verdict | Reason |
| --- | --- | --- |
| Granian (WSGI) | Rejected — issue #1722 closed | No WebSocket support on WSGI; logs `Websockets are not supported on WSGI, ignoring`. `simple-websocket` can only obtain a socket from `werkzeug.socket`, `gunicorn.socket`, `eventlet.input`, or gevent. gthread works because Gunicorn sets `gunicorn.socket`. |
| uvicorn `--interface wsgi` | Rejected | Same dead end — verified polling-only, no WebSocket. |
| uvicorn ASGI | Deferred | Verified working (`WsgiToAsgi` + `socketio.AsyncServer` with a sync `.emit()` shim), but requires dropping Flask-SocketIO. That is the re-architecture in [`docs/migration/flask-to-fastapi-migration-plan.md`](../migration/flask-to-fastapi-migration-plan.md). |
| gevent | Not evaluated | Still a monkey-patching runtime; trades one green-thread foundation for another. |

---

## 2. Non-goals

- No move to ASGI, FastAPI, or uvicorn.
- No `-w > 1`. In-process Socket.IO state makes that a separate project requiring a Redis backplane and sticky sessions.
- No conversion of broker or service paths to `async def`.
- No SQLite-to-Postgres migration. In scope only if Phase C measurement proves write contention is the ceiling *after* correct transaction boundaries.
- No frontend transport change during the initial cutover (§8.1).

---

## 3. The governing constraint

**Under eventlet, non-yielding code is atomic *relative to other greenlets*. Under gthread it is not.**

The qualifier matters: OpenAlgo already runs real OS threads under eventlet (the `eventlet.patcher.original("threading")` escape hatches, the Telegram bot, broker streaming adapters), so code touched by those paths is already exposed. What changes is that *request handlers and every green-thread-scheduled background task* join that exposed set.

The second-order constraint: **every long-lived request holds a real thread.** Gunicorn's gthread worker defaults to `--threads 1`. SSE streams, Socket.IO transports, internal loopbacks, and sleeping broker rate limiters each occupy one for their full lifetime.

---

## 4. Phase A — correctness gates (blocking)

### A1. Serialize server-originated Socket.IO emits

`socketio/server.py:157` states: *"this method is not thread safe. If multiple threads are emitting at the same time to the same client, then messages composed of multiple packets may end up being sent in an incorrect sequence."* `subscribers/socketio_subscriber.py:5-6` asserts the opposite; that comment is wrong.

- Introduce one central emit boundary guarded by a process-wide `RLock`; route background, subscriber and request emits through it. **The lock is the default and stays until evidence says otherwise.**
- Remove the 7 `socketio.start_background_task(socketio.emit, ...)` sites (`services/orderstatus_service.py:40,124,173,267`, `services/openposition_service.py:39,114`, `services/order_router_service.py:120`) — they spawn a native thread solely to call `emit()`.
- **Scoping evidence — measure the right thing.** Packet count is *not* a function of JSON byte size. `socketio/manager.py:44-46` shows multiplicity comes from `pkt.encode()` returning a list, which happens for **binary attachments**. Instrument encoded packet count, presence of binary attachments, callback use, destination (broadcast vs `to=`/room), and concurrent-sender identity. Byte size is not a proxy for any of these.

### A2. Make symbol-cache reload atomic

`database/token_db_enhanced.py:181-309` and `:695-708`. `clear_cache()` empties nine structures then sets `cache_loaded = False`.

Merely reordering the flag is **insufficient** — a reader can pass the `cache_loaded` check and then iterate while another thread clears. Required: build the new state off to the side and atomically swap a single reference; serialize writers with a load lock; retain the previous snapshot on failure. Readers must see the complete old snapshot or the complete new one, never a mix. This is on the live-order symbol lookup path.

**Same defect, second location.** `database/qty_freeze_db.py:41-44,127-184` holds `_freeze_qty_cache` plus a `_cache_loaded` flag and does the identical `clear()`-then-refill (`:138`). It feeds order split and freeze-quantity sizing, so a partial read changes how an order is split. It takes the same snapshot-swap fix (`GT-A2-03`).

### A3. Protect shared `TTLCache` objects

cachetools does not make its mappings thread-safe. Verified: 12 active modules hold `TTLCache` instances with zero locks — `auth_db` (6), `settings_db`, `user_db`, `traffic_db`, `flow_db`, `strategy_db`, `market_calendar_db`, `leverage_db`, `latency_db`, `telegram_db` (4), `whatsapp_db` (4), `utils/trading_calendar.py`.

`auth_db` is the priority: auth records, feed tokens, broker selection, API-key verification, order mode — all on the live-order path. `services/indicator_service.py` is the in-repo exemplar. Protect compound `if key in cache` / get / delete / write sequences, not just individual operations; keep DB, Argon2 and network work outside the lock.

### A4. Bounded SQLite transaction retry — with a per-transaction work list

WAL, `synchronous=NORMAL`, `busy_timeout=15000` (`658d44830`) and `NullPool` are in place. Missing is retry for `SQLITE_BUSY_SNAPSHOT`, which returns immediately and cannot be waited out.

**Inventory (complete).** 179 commit sites across 34 modules, resolved to five databases. Enumerating 179 rows is not useful; the tractable unit is the risk class, and every module is assigned to one in the tracker (`GT-A4-*`):

| Class | Scope | Policy |
| --- | --- | --- |
| **Never retry** | Any commit at a boundary enclosing a broker network call — order placement post-ack writes | Retry here can place a broker order twice. Restructure the boundary instead. |
| **Retry — idempotent local state** | `openalgo.db` (24 modules, ~140 sites): auth, settings, strategy, oauth/MCP, session, action-center, market-calendar | Bounded, jittered, fresh session per attempt |
| **Retry — sandbox** | `sandbox.db` (29 sites across `sandbox/*` + `database/sandbox_db.py`) | Retry safe **except** the fill-commit path, which must stay exactly-once |
| **Retry — health** | `health.db` (7 sites) | Samples are idempotent |
| **Do not retry — serialized by design** | `logs.db` (`traffic_db`, 10 sites), `latency.db` | Already single-writer. Adding retry converts a fast path into a thread-parking one. |

Per-row columns in the tracker:

| Column | Requirement |
| --- | --- |
| Function + database | Exact target |
| Idempotent? | If no, it does not get retried |
| Broker/network side effect before commit? | If yes, the retry boundary is wrong — restructure |
| Retryable error codes | `SQLITE_BUSY_SNAPSHOT` restarts immediately with a fresh session |
| Max attempts + total latency budget | Must be bounded and stated |

**Do not layer retries on top of the 15s `busy_timeout` for generic `SQLITE_BUSY`.** Three attempts × 15s parks a request thread for ~45 seconds — a thread-pool outage dressed as resilience. Generic `SQLITE_BUSY` is what `busy_timeout` is for; retry is for the snapshot conflict it cannot fix.

The retry boundary must surround only the local transaction. A broker order must never be placed twice because a post-order local write was retried too broadly.

### A5. Extend Python Strategy lock coverage to readers

`blueprints/python_strategy.py:64` already defines `PROCESS_LOCK = threading.RLock()`, guarding the lifecycle entry points — start (`:423`), stop (`:606`), plus three more. **The registries are not unsynchronized**, contrary to the audit's GT-07.

The gap is coverage: 106 references to `RUNNING_STRATEGIES` / `STRATEGY_CONFIGS` against 6 lock sites, so readers (line 215, status/list endpoints) run unguarded while writers mutate. Extend coverage to readers; never hold the lock while waiting for a child process to exit (see A9 for why that rule matters).

### A6. Harden MCP (`MCP_HTTP_ENABLED=TRUE` only)

`blueprints/mcp_http.py`:

- `_scope_quota` (`:115`) — unlocked read-modify-write, with the comment *"Single eventlet worker, so no shared-state concerns"* stating the premise this migration invalidates. Add a lock and bound the key space; entries prune only when the same `(jti, scope)` recurs.
- `_audit_log` (`:344`) — appends then size-trims with no lock; concurrent requests can lose audit lines during rotation.
- `_initialized` — unlocked check-then-act, first exercised by the first MCP request rather than at startup.

### A7. Give the WebSocket proxy a real owner and an explicit topology

Two distinct defects.

**A7a — Docker has no supervisor.** `start.sh:303` backgrounds the proxy and `start.sh:319` installs `trap cleanup SIGTERM SIGINT`, but `start.sh:332` then `exec`s Gunicorn. **`exec` replaces the shell, so the trap ceases to exist.** Consequences: the proxy is never gracefully stopped; an unexpected proxy exit is never noticed or restarted; and the container health check probes only Flask, so Docker reports healthy with market data dead.

Required: a real owner — a separate Compose service, a minimal PID-1 supervisor, or a supervising shell that forwards signals, monitors both processes and reaps children. Health check must cover port 8765.

**A7b — native topology must not flip silently.** `websocket_proxy/app_integration.py:25` `_eventlet_active()` returns False under gthread, moving the proxy from subprocess into the Gunicorn worker on native installs. The `greenlet.error` motivation (#1421) genuinely disappears, but topology must not change as a side effect of a worker-class flag.

Replace eventlet detection with explicit `WEBSOCKET_PROXY_MODE=external|subprocess|thread`: `external` in Docker, `subprocess` in native Gunicorn production, `thread` for the dev server only. Preserve the SUB-binds/PUBs-connect invariant.

### A8. EventBus scoped-session cleanup

`utils/event_bus.py:60` `_safe_call()` has `try`/`except` but no `finally`. Ten persistent native workers query and write scoped SQLAlchemy sessions; `utils/db_sessions.py` states background threads must call `remove_all_scoped_sessions()`. Add it in a `finally`.

### A9. Sandbox / Analyzer engine — named lifecycle defect

Not covered by the audit. The engine executes simulated orders and at least one production instance runs Analyzer mode full-time.

**Concrete defect:** `sandbox/execution_thread.py:186` `stop_execution_engine()` acquires `_thread_lock`, then calls `_stop_websocket_upgrade_watcher()`, which `join(timeout=5)`s the watcher at `:296`. The watcher loop at `:250` acquires the *same* `_thread_lock`. If the watcher is blocked there, the stopper waits the full 5s, the join times out, and `_auto_upgrade_thread = None` is set **while the thread is still alive** — it then acquires the lock and mutates engine state after being declared stopped. Bounded by the timeout, so a stall plus an orphaned mutator rather than a permanent deadlock — but it is exactly the "hold a lock while joining" pattern A5 forbids, and gthread widens the window.

Other surfaces: the auto-upgrade thread (`:284`), `sandbox/websocket_execution_engine.py:434,468`, the squareoff thread, the startup `ThreadPoolExecutor` (`app.py:846-865`), and `sandbox.db`.

**Pass/fail tests:** stop during auto-upgrade; stale-feed fallback and recovery; repeated start/stop cycles; exactly-once simulated fills while polling and WebSocket engines overlap; clean session and thread teardown with no orphaned threads.

### A10. Shared HTTP client singleton

`utils/httpx_client.py:19-30` — `_httpx_client = None` with an unlocked `if _httpx_client is None:` check-then-create. Concurrent first calls construct **competing connection pools**; the losers are never closed, which is both a correctness issue and an FD leak under CLAUDE.md's own hygiene rule. Cleanup is likewise unsynchronized with active users.

Required: guard construction and teardown; add a bounded pool-acquisition timeout separate from the 120s request timeout (a saturated 100-connection pool currently manifests as a hang, not an error); expose saturation metrics.

**Correction — Flask-Limiter needs no locking work.** `limiter.py:7` uses `storage_uri="memory://"`, and the installed backend already holds `defaultdict[str, threading.RLock]` per key (`limits/storage/memory.py:37`). A concurrency test is appropriate; a new locking design is not justified.

### A11. Historify / DuckDB under real thread concurrency

Not covered by the audit or by rev 1–2. `historify.duckdb` is one of the six databases and **does not go through `engine_factory`** — `database/historify_db.py:75` calls `duckdb.connect()` directly, so `NullPool` and the WAL/`busy_timeout` pragmas in `database/__init__.py` do not apply to it. Its `get_connection()` (`:49`) already carries a `max_retries`/`retry_delay` loop, which is itself evidence that write contention is a known problem there.

DuckDB's single-writer model and connection semantics differ from SQLite's; more concurrent real-thread writers from the Historify scheduler and request paths is a materially different load. Required: determine the concurrency contract for the connection helper, whether connections may cross threads, and whether the retry loop is adequate or needs the same treatment as A4. Each connection is also an FD plus a buffer-pool arena — include it in the soak.

### A12. Remaining unsynchronized registries

Lower severity than A1–A3 but on the same footing as A6, and none currently has a lock:

| Registry | Location | Exposure |
| --- | --- | --- |
| `_POOLED_ADAPTERS` | `websocket_proxy/broker_factory.py` | Mostly the proxy process; becomes request-thread reachable if A7b ever selects `thread` mode |
| `_STRIKES_CACHE` | `services/option_symbol_service.py` | Unbounded key space; only `broker/paytm/database/master_contract_db.py:395` invalidates |
| Workflow lock registry | `services/flow_executor_service.py:30-40` | Creation is guarded, entries never removed, grows with workflow IDs |
| `_ADAPTERS` | `services/order_update_service.py` | Already locked — verify coverage extends to removal on disconnect |
| `Error404Tracker` / banned-IP state | `utils/security_middleware.py` | Per-request mutation on the WSGI path outside Flask |
| Traffic / latency log writers | `traffic_logger.py`, `database/latency_db.py` | Already serialized by design; confirm the design holds with real threads |
| Scalping risk monitor | `services/scalping_risk_monitor_service.py` | Server-side SL/target engine; owns state across request and monitor threads |

Decisions are recorded per row in the tracker (`GT-A12-*`). `_POOLED_ADAPTERS` resolves to **safe under `external`/`subprocess` mode** and only needs a lock if A7b ever selects `thread`.

### A13. APScheduler job defaults

`services/flow_scheduler_service.py:57-59` and `services/historify_scheduler_service.py:60-65` both set `coalesce: True, max_instances: 1, misfire_grace_time`. Correct and bounded — **resolved, no work**.

`blueprints/python_strategy.py:110` creates `BackgroundScheduler(daemon=True, timezone=IST)` with **no `job_defaults`**. It therefore has no `max_instances`, no `coalesce` and no misfire grace. Under eventlet the executor was cooperatively scheduled; under gthread, overlapping triggers can genuinely run in parallel — a duplicate strategy start places duplicate live orders. **Add job defaults matching the other two schedulers.**

### A14. Flask session and CSRF — resolved

Flask's default session is a signed client-side cookie deserialized per request, so there is no shared server-side session store to race. `app.py:173` `CSRFProtect` binds tokens to that session. `utils/auth_utils.py:374` sets `PERMANENT_SESSION_LIFETIME` per login. **Both resolved as safe**; a concurrent multi-device login test is retained as regression only.

The one open item is `MAX_SESSIONS_PER_USER` enforcement in `database/auth_db.py` — a check-then-insert cap that must hold under concurrent device logins (`GT-A14-03`).

### A15. Windows SQLite locking

CLAUDE.md records that SQLite locking is stricter on Windows. The A4 retry bounds must be validated there, not only on Linux — the same attempt count can produce a different worst-case latency (`GT-A4-08`).

---

## 5. Phase B — thread budget

### B1. Size from connection demand

`--worker-class gthread` without `--threads` is a one-request worker. Size from demand, not CPU count:

```text
required threads >=
    active Socket.IO clients x 2          (polling can hold an outstanding GET and POST simultaneously)
  + active Python Strategy SSE streams    (blueprints/python_strategy.py:2335, infinite)
  + active MCP SSE streams                (blueprints/mcp_http.py:695, infinite)
  + internal loopback reserve             (MCP, Telegram AND WhatsApp all re-enter this server via the SDK; >=2)
  + requests parked in broker rate limiters   (B2)
  + basket-order fan-out                  (services/basket_order_service.py:351, up to BATCH_SIZE threads per request)
  + peak ordinary HTTP concurrency
  + failure/reconnect reserve
```

Budget **native application threads separately from request threads** — EventBus (10), API/analyzer/traffic/latency writers, bot threads, APScheduler executors, order-update adapters, broker SDK threads. The shared HTTP pool (A10) is consumed by all of them, not only Gunicorn threads.

Canary at 32; evaluate 64 only if measurement demands it. Neither value is approved until §9 passes.

### B2. Blocking-sleep inventory

Under eventlet a sleeping caller yields the hub for free. Under gthread it **holds a worker thread for the full sleep**.

Eight modules are known steady-state throttles: `angel/api/data.py`, `definedge/api/data.py`, `definedge/api/rate_limiter.py`, `dhan/api/data.py`, `flattrade/api/data.py`, `fyers/api/rate_limiter.py`, `iiflcapital/api/rate_limiter.py`, `tradesmart/api/data.py`. Angel's history limiter is 0.5s at ~2 req/s, so N concurrent history requests serialize into N × 0.5s of occupied threads.

**Classification (complete).** All 203 `time.sleep()` sites under `broker/` are categorized:

| Category | Sites | Files | Consumes a request thread? |
| --- | ---: | ---: | --- |
| **Request path** — `api/data.py`, `api/order_api.py`, `api/funds.py` | **103** | **43** | **Yes — this is the budget term** |
| Streaming threads — `streaming/`, `api/*websocket*.py` | 75 | — | No, own threads |
| Background master-contract download | 5 | — | No, background thread |

The eight modules named in rev 2 were the *steady-state throttles*; the real request-path exposure is **103 sites across 43 broker files**. Worst case is bounded by the slowest configured interval on the active broker, not by the sum — only one broker is active per deployment. Size B1 against the active broker's request-path sleeps, and re-derive when switching brokers.

**Per-call executors.** 13 non-streaming sites. Live under gthread: brokers **nubra, iiflcapital, tradesmart**; services **`basket_order_service.py:351`** (up to `BATCH_SIZE` live-order threads per request), `historify_service`, `flow_price_monitor_service`, `flow_order_update_monitor_service`, `telegram_alert_service`, `whatsapp_alert_service`. For shoonya, definedge, flattrade and zebu the `USE_ASYNC` flip (§6.4) makes the executor a dead branch. All bounded via `GT-B2-04`.

### B3. `GUNICORN_THREADS` must be plumbed end to end

The target command is configurable, but the variable must reach every surface that launches Gunicorn:

`Dockerfile` · `start.sh` · `docker-compose.yaml` (all generated variants) · `.sample.env` · `install/install.sh` · `install/install-multi.sh` · `install/update.sh` · `install/install-docker.sh` · `install/install-docker-multi-custom-ssl.sh` · `install/docker-run.sh` · `install/docker-run.bat`

**Do not reuse `THREAD_LIMIT`.** It sets `OPENBLAS_NUM_THREADS` / `OMP` / `MKL` / `NUMEXPR` / `NUMBA` and is deliberately capped at 1–4 (`install/install-docker-multi-custom-ssl.sh:450-456`). Gunicorn needs its own variable.

**Multi-instance needs an aggregate host budget.** 32 threads × instance count, plus application executors and numerical-library threads, is not safe to assume on a small VPS. Derive a per-host ceiling and divide.

---

## 6. Phase C — deployment surfaces

### C1. Target shape

```text
gunicorn>=26.0,<27
gunicorn --worker-class gthread --workers 1 --threads ${GUNICORN_THREADS:-32} ... app:app
```

### C2. Existing native installs must have their systemd unit migrated

**Release blocker.** `install/update.sh` updates dependencies and restarts the service, and runs `systemctl daemon-reload` at `:517` "in case service file changed" — but **it never rewrites `ExecStart`**. An upgraded install would receive Gunicorn 26 with eventlet removed while its unit still says `--worker-class eventlet`, and fail to start.

`update.sh` must: inspect and back up the current unit; rewrite `--worker-class eventlet` to `gthread` and add the thread count; `daemon-reload`; validate the new `ExecStart` **before** removing eventlet; and automatically restore the previous unit and dependency set if startup fails.

### C3. Complete `install/` and Docker inventory

Every file in `install/` is classified. **No file may be left unclassified** — an unreviewed installer is how a migration ships a broken upgrade path.

**Launches Gunicorn — must change worker class AND accept `GUNICORN_THREADS`:**

| File | Site | Change |
| --- | --- | --- |
| `Dockerfile` | `:8-13` | Pin `gunicorn>=26,<27`, drop eventlet, add `GUNICORN_THREADS` default |
| `start.sh` | `:332-341` | Worker class, threads, **and the A7a supervisor rewrite** |
| `install/install.sh` | `:766-776`, `:1151-1157` | Dependency install + systemd `ExecStart` |
| `install/install-multi.sh` | `:310-311`, `:605-611` | Dependency install + per-instance systemd `ExecStart` |
| `install/update.sh` | `:445-453` | Dependencies **and the C2 unit migration** |
| `requirements-nginx.txt` | `:148-149` | Repin, remove eventlet |

**Generates or rewrites `docker-compose` — must inject and preserve `GUNICORN_THREADS`:**

| File | Note |
| --- | --- |
| `install/install-docker.sh` | Generates compose with an `environment:` block |
| `install/install-docker-multi-custom-ssl.sh` | Generates compose; also owns `THREAD_LIMIT` (`:450-456`) — keep strictly separate from `GUNICORN_THREADS`, and apply the B3 aggregate host budget here |
| `install/enable-remote-mcp-docker.sh` | **Reclassified.** Sets no worker class (rev 2 excluded it correctly on that basis), but `:67` discovers and rewrites existing `docker-compose.{yaml,yml}` files, so it must preserve the env var rather than drop it on rewrite |
| `install/docker-run.sh` | 28 `-e` injections — largest env surface |
| `install/docker-run.bat` | Windows equivalent; must stay in parity |

**Touches the systemd unit or nginx — regression coverage, not configuration:**

| File | Note |
| --- | --- |
| `install/change-domain.sh` | Reads the unit at `:200-201`, stops/starts the service (`:353-354`, `:470`), reloads nginx (`:439`, `:469`). Must be re-validated **after** the C2 unit migration, and regenerates `/socket.io/` config so it belongs in WebSocket regression coverage |
| `install/update.bat` | Windows updater — no Gunicorn today; confirm it needs no unit handling |

**Documentation surfaces** (CLAUDE.md makes `docs/` the source of truth):

`INSTALL.md:84` · `DISCOVERY_MAP.md:29` · `CONTRIBUTING.md:183,1059` · `CLAUDE.md:60-70` · `docs/docker/docker.md:28` · `docs/docker/DOCKER_BUILD_GUIDE.md:74` · `docs/websocket-architecture.md:477` · `docs/prd/websocket-proxy.md:51` · `docs/design/11-docker/README.md` (9 refs) · `docs/design/12-ubuntu-server/README.md` (4) · `docs/design/06-websockets/README.md` · `docs/design/34-app-startup/README.md` · `docs/design/02-backend/README.md` · `docs/design/20-design-principles/README.md` · `docs/design/30-upgrade-procedure/README.md` · `install/Docker-install-readme.md` · `install/Docker-Multi-SSL-README.md` · `install/README.md` · `install/Remote-MCP-readme.md:89`

Also: remove eventlet from `requirements-nginx.txt` and fresh-install commands; `uv pip install -r` does not prune an extraneous eventlet, so uninstall explicitly. Keep `simple-websocket` pinned. Keep `--timeout 300` initially and verify against both infinite SSE endpoints.

### C4. Broker validation

19 files across 13 of 36 brokers reference eventlet. **One genuine change:**

- **No change (6 files):** zerodha (adapter + websocket), hdfcsky (websocket + api/data), arrow, dhan_sandbox — guarded `else: _real_threading = threading` fallbacks that become no-ops.
- **Behaviour change (4 brokers):** `USE_ASYNC = not _is_eventlet_patched()` in shoonya, definedge, flattrade, zebu flips batch quotes from `ThreadPoolExecutor` to `asyncio.run()` + per-call `httpx.AsyncClient`. Requires live batch-quote, option-chain, timeout, rate-limit, exception-aggregation and repeated-call FD/RSS tests per broker.
- **Comment-only (9 files):** upstox, mstock, dhan, shoonya, iiflcapital, angel — rationale void, code unaffected.

### C5. Diagnostics

`blueprints/admin.py:1206-1232` `_runtime_info()` defaults `wsgi_hint="flask-dev"` and only flips on active eventlet, so gthread is misreported in production. Report Gunicorn version, worker class, configured and active threads, active Socket.IO and SSE counts, and proxy mode. Update `frontend/src/types/admin.ts:142`. Replace the eventlet-monkeypatching `test/test_telegram_startup.py` with gthread-path tests.

---

## 7. Cross-platform validation

CI today is Linux-only, and the Docker smoke test at `.github/workflows/ci.yml:272` **overrides the entrypoint** — it never starts `start.sh`, Gunicorn, Flask, Socket.IO or the proxy. It cannot detect any defect in this plan.

Required before declaring readiness:

- Full-container boot on linux/amd64 **and** linux/arm64 using the real entrypoint.
- Assert Gunicorn 26, worker class `gthread`, one worker, configured thread count; assert eventlet absent.
- Probe Flask health, Socket.IO polling, Socket.IO WebSocket upgrade, and port 8765.
- Stop the container; prove Gunicorn **and** the proxy exit cleanly (the A7a gate).
- Native Ubuntu fresh install **and** `update.sh` upgrade-path test (the C2 gate).
- RHEL-family and Arch-family installer and unit rendering.
- Windows and macOS dev startup via `uv run app.py`.
- Windows/macOS Docker runner tests, or at minimum platform-native script validation.
- Multi-instance native and Docker with separate Flask, WebSocket and ZMQ ports.

---

## 8. Cutover and rollback

1. Full suite with **no eventlet imported**.
2. Canary at 32 threads **with the frontend still pinned to polling** — isolate runtime correctness from transport change.
3. Exercise MCP, both SSE endpoints, both bots, strategies and live Socket.IO concurrently.
4. 24-hour soak against the §9 numbers.
5. Only then stage the transport change.

### 8.1 Frontend transport (separate change)

All four Socket.IO constructors force `transports: ['polling'], upgrade: false` — `useSocket.ts:149`, `useOrderEventRefresh.ts`, `ActionCenter.tsx`, `WhatsAppIndex.tsx`. The comment claiming WebSocket upgrade fails in threading mode is false on Gunicorn gthread with `simple-websocket`; verified directly.

Do not unpin in the same deployment as the worker change. Add nginx upgrade coverage across every official topology first (including post-`change-domain.sh`), unpin one representative client, observe, then migrate the rest.

### 8.2 Rollback

**Rollback is not a one-line revert.** It spans five artefacts:

| Artefact | Rollback requirement |
| --- | --- |
| Docker image | Redeploy an **immutable previous SHA tag**, never `latest` |
| systemd unit | Restore the backup taken in C2 |
| Dependencies | Restore the previous Gunicorn + eventlet set explicitly |
| Proxy mode | Explicit `WEBSOCKET_PROXY_MODE` revert |
| Phase A changes | Each independently revertible — they are **not** behaviour-preserving |

**Abort criteria:** any unhandled `database is locked` on live-order paths; Socket.IO reconnect loops; thread saturation causing `/health` timeouts; FD or RSS failing to plateau in soak; any batch-quote regression in the four `USE_ASYNC` brokers; proxy exit undetected by the supervisor.

Define and measure a **rollback RTO** with post-rollback health verification. Rehearse the revert on a non-production instance before the canary, not after an incident.

---

## 9. Acceptance gates — numbers required

Two kinds of number. **Engineering-derived** values are filled below with their derivation and need no sign-off. **Product-owned** values are provisional defaults derived from the single-user invariant and are marked — they are the only rows requiring a decision, and disagreeing with a number is faster than originating one.

**Engineering-derived (final unless measurement contradicts):**

| Parameter | Value | Derivation |
| --- | --- | --- |
| Max thread-pool utilization | **70% sustained, 90% peak** | Above 90% there is no headroom for the reconnect burst that follows any restart |
| SQLite retry budget | **3 attempts, 2s total ceiling** | `SQLITE_BUSY_SNAPSHOT` restarts immediately; generic `BUSY` is already covered by `busy_timeout=15000` and must not be re-waited (A4) |
| Graceful shutdown deadline | **30s** | Existing `--graceful-timeout 30` at `start.sh:337`, kept |
| Client reconnect deadline | **<60s** | `extensions.py` `ping_timeout=60` — clients must not declare the connection dead before a 30s drain completes |
| Proxy restart/recovery | **detect <10s, recover <30s** | Must be under the `ping_timeout=60` window so a proxy bounce never surfaces as a client disconnect |
| FD slope over 24h | **0 net** — plateau within 30min of steady state | Single worker that never restarts; any positive slope is a leak by definition |
| RSS slope over 24h | **<2% growth after plateau** | Caches are TTL-bounded; sustained growth indicates an unbounded registry (A12) |

**Product-owned (provisional — confirm or amend):**

| Parameter | Provisional | Basis |
| --- | --- | --- |
| Concurrent browser tabs | **5** | `MAX_SESSIONS_PER_USER = 5` already caps devices |
| Concurrent Socket.IO clients | **10** (budget **20** threads) | 2 tabs per device at the cap; polling can hold a GET and POST simultaneously |
| Concurrent Python Strategy SSE | **5** | One per open `/python` tab |
| Concurrent MCP SSE clients | **5** | The least predictable term and the most likely to grow — the row to revisit first |
| Sustained request rate | **10 req/s**, burst 50 | Webhook-driven; single user |
| p95 / p99 — order placement | **broker latency + 50ms / +150ms** | Only the overhead is ours; absolute latency is the broker's |
| p95 / p99 — `/health`, login, ordinary API | **200ms / 500ms** | Must hold while all streams above are connected |

Applying B1 to the provisional values: 20 (Socket.IO) + 5 + 5 (SSE) + 2 (loopback) + active-broker request-path sleeps + basket fan-out + HTTP headroom + reconnect reserve. **A `--threads 32` canary fits with roughly 30% headroom**, which is the basis for that starting value.

Qualitative gates that remain: no production process imports eventlet; MCP dispatch completes without self-deadlock at maximum stream occupancy; concurrent sequence-event stress shows no loss, duplication, corruption or reordering; retry tests prove only local transactions repeat and broker orders remain exactly-once; symbol-cache refresh serves a complete old or complete new snapshot; API-key regeneration, logout and token rollover cannot return stale cache entries.

---

## 9a. PR sequencing and rollback boundaries

Each PR is independently revertible. **No PR depends on a later one.** PR-1 and PR-2 fix defects that exist on eventlet today and should merge regardless of whether the cutover proceeds.

| PR | Scope | Ships on | Revert impact |
| --- | --- | --- | --- |
| **PR-1** | `update.sh` unit backup/rewrite/validate/restore (C2) | eventlet | Upgrade path reverts to current behaviour |
| **PR-2** | Proxy supervisor + `WEBSOCKET_PROXY_MODE` (A7a/A7b) | eventlet | Returns to trap-based (broken) cleanup |
| **PR-3** | Emit boundary + remove one-shot emit threads (A1) | eventlet | Direct emits restored |
| **PR-4** | Symbol-cache snapshot swap (A2) | eventlet | Prior in-place reload |
| **PR-5** | TTLCache locks, httpx singleton, EventBus cleanup, registries (A3/A10/A8/A12) | eventlet | Per-cache revert possible |
| **PR-6** | SQLite retry helper + DuckDB contract (A4/A11) | eventlet | No retry; `busy_timeout` only |
| **PR-7** | MCP quota, audit, init (A6) | eventlet | Prior unlocked behaviour |
| **PR-8** | Sandbox lifecycle + APScheduler defaults (A9/A13) | eventlet | Prior lock-while-joining |
| **PR-9** | **The cutover** — worker class, `GUNICORN_THREADS`, all deploy surfaces (B3/C1/C3/C4) | gthread | Worker class + pin revert (§8.2) |
| **PR-10** | Diagnostics, docs, test replacement (C5/C3-docs) | gthread | Cosmetic |
| **PR-11** | Cross-platform CI (§7) | either | CI only |

PR-1 through PR-8 are the correctness work and carry no runtime risk. **PR-9 is the only one that changes the runtime**, and it is the only one whose revert requires the five-artefact procedure in §8.2.

Qualitative gates that remain: no production process imports eventlet; MCP dispatch completes without self-deadlock at maximum stream occupancy; concurrent sequence-event stress shows no loss, duplication, corruption or reordering; retry tests prove only local transactions repeat and broker orders remain exactly-once; symbol-cache refresh serves a complete old or complete new snapshot; API-key regeneration, logout and token rollover cannot return stale cache entries.

---

## 10. Review corrections

### 10.1 Applied to the source audit (rev 1)

| Audit finding | Correction |
| --- | --- |
| GT-07 — "no lifecycle synchronization boundary" | **Overstated.** `PROCESS_LOCK` exists at `python_strategy.py:64` and guards start/stop. Rescoped to reader coverage, P0 → P1 (A5). |
| GT-14 — "no caller of `clear_strikes_cache()`" | **Wrong.** `broker/paytm/database/master_contract_db.py:395` calls it. |
| "132 emits across 49 files" | Actual **123 across 46** excluding tests. |
| GT-16 "every deploy surface" | Incomplete (C3). |
| Coverage | Sandbox engine, httpx client, rollback, broker sleep costs absent. |

### 10.2 Applied to this plan (rev 1 → rev 2)

| Rev 1 error | Correction |
| --- | --- |
| A1 proposed measuring **payload byte size** to find multi-packet emits | Wrong mechanism. `socketio/manager.py:44-46` shows multiplicity comes from binary attachments via `pkt.encode()` returning a list. Instrument packet count, attachments, callbacks, destination, concurrent senders. Lock stays default. |
| A10 proposed a Flask-Limiter locking design | Unjustified. `limits/storage/memory.py:37` already holds per-key `RLock`s. Replaced with the real defect: `utils/httpx_client.py:19` unlocked singleton. |
| §6.2 called rollback "a one-line worker-class revert" | Wrong. Five artefacts (8.2). Phase A is not behaviour-preserving. |
| A7 covered only native topology | Missed that `start.sh:332` `exec` destroys the `:319` trap — Docker has no proxy supervisor (A7a). |
| No `update.sh` systemd migration | Release blocker; existing installs would fail to start (C2). |
| No `GUNICORN_THREADS` plumbing | 11 surfaces, and `THREAD_LIMIT` must not be reused (B3). |
| B3 listed `enable-remote-mcp-docker.sh`, `Remote-MCP-readme.md` | Misclassified — prose only, configure nothing. Six real surfaces were missing (C3). |
| A9/A10 were reviews, not gates | Now carry a named defect and pass/fail tests. |
| Governing sentence said "implicitly atomic" | Narrowed: atomic *relative to other greenlets*. Real OS threads already exist under eventlet. |
| "CPU work blocks one thread" | Softened — GIL contention still degrades concurrent requests. |
| Acceptance criteria unmeasurable | §9 now requires numbers before implementation. |

### 10.3 Applied in rev 3

| Gap | Correction |
| --- | --- |
| Historify/DuckDB absent | `database/historify_db.py:75` calls `duckdb.connect()` directly, bypassing `engine_factory`, so `NullPool` and the WAL/`busy_timeout` pragmas never apply. New gate A11. |
| Unsynchronized registries absent | `_POOLED_ADAPTERS`, `_STRIKES_CACHE`, flow-executor lock registry, `Error404Tracker`, scalping monitor. New gate A12. |
| `install/` inventory partial | All 14 files in `install/` now classified by role (C3). Five compose-generating scripts identified as `GUNICORN_THREADS` carriers. |
| `enable-remote-mcp-docker.sh` excluded outright | Reclassified: correct that it sets no worker class, but `:67` rewrites existing compose files and must preserve the env var. |
| `change-domain.sh` scoped to nginx only | It also reads the unit (`:200-201`) and stops/starts the service; must be re-validated after the C2 unit migration. |
| Completeness implied | §11 now states explicitly what is still open. |

---

## 11. Coverage status

"100% coverage" here means **every discovered runtime and deployment surface is classified, mapped to a gate, a test, a rollback boundary and a measurable acceptance criterion.** It does not mean static analysis guarantees production behaviour — that is what the §7 platform matrix and the 24-hour soak are for.

By that definition, **discovery and classification are complete.** Every surface has a row in [`2026-08-01-gthread-migration-tracker.csv`](2026-08-01-gthread-migration-tracker.csv): 113 rows, each carrying `decision`, `gate`, `test`, `rollback_boundary`, `acceptance_criterion` and `status`.

| Area | Rows | Resolved (no work) | Open |
| --- | ---: | ---: | ---: |
| Socket.IO emit (A1) | 4 | 0 | 4 |
| Caches (A2, A3) | 15 | 0 | 15 |
| SQLite + DuckDB (A4, A11, A15) | 10 | 0 | 10 |
| MCP (A6) | 4 | 0 | 4 |
| Proxy (A7) | 3 | 0 | 3 |
| EventBus (A8) | 1 | 0 | 1 |
| Sandbox (A9) | 4 | 0 | 4 |
| HTTP client + limiter (A10) | 4 | 1 | 3 |
| Registries (A12) | 12 | 1 | 11 |
| Schedulers (A13) | 3 | 2 | 1 |
| Session/CSRF (A14) | 3 | 2 | 1 |
| Capacity (B1, B2) | 6 | 3 | 3 |
| Deployment (B3, C2, C3) | 15 | 0 | 15 |
| Documentation (C3) | 1 | 0 | 1 |
| Broker (C4) | 3 | 2 | 1 |
| Diagnostics (C5) | 3 | 0 | 3 |
| Platform (§7) | 16 | 0 | 16 |
| Rollback (§8.2) | 6 | 0 | 6 |
| **Total** | **113** | **11** | **102** |

Eleven rows are **resolved with no work required** — each carries the evidence for why, so the exclusion is auditable rather than an omission: Flask-Limiter already holds per-key `RLock`s; flow and historify schedulers already set `max_instances: 1`; Flask session is a per-request signed cookie; 75 streaming and 5 download sleep sites are not request threads; four brokers' executors become dead branches; six broker files have guarded fallbacks.

**What remains is execution, not discovery.** The gates are prose and the tracker rows are `open` because no code or test has been written yet. §9 now carries derived values for every engineering row and provisional values for every product row, so implementation is unblocked — the seven product rows can be amended without re-planning.

**How this was verified (rev 5).** A residual sweep for module-level mutable globals across `services/`, `blueprints/`, `utils/`, `subscribers/`, `websocket_proxy/`, `sandbox/` and `database/` found **six surfaces that rev 4 had not mapped** — including `database/qty_freeze_db.py`, which carries the identical clear-then-refill defect as the symbol cache and sits on the order-splitting path. It was named in the source audit's GT-14 and lost when A12 was drafted. All six now have rows.

That is the honest state of "complete": it means no unmapped surface survives the sweeps run so far, not that none exists. Each future sweep either finds nothing or, as here, finds something — and the tracker is the record of which sweeps have been run.

**Residual risk that no amount of static analysis closes:** real broker behaviour under the four `USE_ASYNC` paths, actual thread saturation under production traffic, FD and RSS behaviour over 24 hours, and platform-specific SQLite timing. Those are §7 and §8 gates by design.

---

## 12. Exit conditions

gthread remains correct while: one user and broker session per deployment; one worker; moderate browser/webhook/MCP/strategy concurrency; broker latency dominating; market ticks flowing through the separate asyncio/ZMQ proxy rather than the WSGI pool.

Revisit when OpenAlgo becomes multi-user, Socket.IO must span processes or hosts, concurrent stream clients routinely exceed a practical thread budget, service paths are intentionally converted to async end to end, or SQLite remains the write bottleneck *after* correct transaction boundaries — in which case the answer is PostgreSQL or a dedicated write owner, not a different HTTP server.

None of these is triggered merely by removing eventlet.
