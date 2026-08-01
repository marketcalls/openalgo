# Eventlet to gthread — Migration Plan

**Status:** Design — not yet built
**Date:** 2026-08-01
**Branch:** `gthread`
**Scope:** Replace Gunicorn's `eventlet` worker with its `gthread` worker. Keep Flask, keep Flask-SocketIO, keep `-w 1`.
**Evidence base:** [`audit/EVENTLET_TO_GTHREAD_MIGRATION_AUDIT.md`](../../audit/EVENTLET_TO_GTHREAD_MIGRATION_AUDIT.md), with the corrections in §8 of this plan applied.

---

## 1. Why

This is a **foundation migration, not a performance one**. Nobody should expect it to be faster; broker API latency dominates request latency and the WSGI server is not the ceiling.

What it buys:

1. **eventlet is deprecated and unmaintained.** It prints its own warning recommending migration.
2. **We are pinned out of the current Gunicorn major.** `gunicorn>=25.0,<26` in `Dockerfile:13` and three install scripts, because Gunicorn 26 removed the eventlet worker entirely (`SUPPORTED_WORKERS` = `asgi, gevent, gevent_pywsgi, gevent_wsgi, gthread, sync, tornado`). No security or bugfix updates until this lands.
3. **The "no asyncio in production" invariant disappears.** Today async work must be shunted onto real OS threads or subprocesses. That entire workaround category goes away.
4. **The dev/prod gap closes.** CLAUDE.md calls asyncio-works-locally-breaks-on-deploy "the single most common way a change passes locally and fails on deploy." Dev already uses threading; gthread makes production match.
5. **A class of bugs is eliminated, not mitigated** — `greenlet.error` cross-thread crashes (#1421), the heartbeat starvation behind #1419, psutil's patched-`select` breakage.
6. **CPU-bound work stops freezing everything.** The 150k-row symbol cache build and Plotly rendering have no yield points, so under eventlet they stall the whole hub. Under gthread they block one thread.
7. **WebSocket transport becomes available** for Socket.IO, currently disabled at all four frontend call sites.

What it does **not** buy: no throughput gain, no multi-worker scaling (still `-w 1`), and SQLite contention gets *worse* before the hardening makes it better.

**Independent justification for Phase A:** the hardening items below (unlocked TTL caches, non-atomic symbol-cache reload, missing SQLite retry) are latent correctness bugs that exist *today* and are merely masked by eventlet's cooperative serialization. That work has value even if the flag is never flipped.

### 1.1 Rejected alternatives

| Option | Verdict | Reason |
| --- | --- | --- |
| Granian (WSGI) | Rejected — issue #1722 closed | No WebSocket support on WSGI; logs `Websockets are not supported on WSGI, ignoring`. `simple-websocket` can only obtain a socket from `werkzeug.socket`, `gunicorn.socket`, `eventlet.input`, or gevent. gthread works because Gunicorn sets `gunicorn.socket`. |
| uvicorn `--interface wsgi` | Rejected | Same dead end — verified polling-only, no WebSocket. |
| uvicorn ASGI | Deferred | Verified working (`WsgiToAsgi` + `socketio.AsyncServer`, with a sync `.emit()` shim so the 123 emit sites need not change), but requires dropping Flask-SocketIO. That is the FastAPI-shaped re-architecture in [`docs/migration/flask-to-fastapi-migration-plan.md`](../migration/flask-to-fastapi-migration-plan.md). |
| gevent | Not evaluated | Still a monkey-patching runtime; trades one green-thread foundation for another. |

---

## 2. Non-goals

- No move to ASGI, FastAPI, or uvicorn.
- No `-w > 1`. In-process Socket.IO state makes that a separate project requiring a Redis backplane and sticky sessions.
- No conversion of broker or service paths to `async def`.
- No SQLite-to-Postgres migration. In scope only if Phase C measurement proves write contention is the ceiling *after* correct transaction boundaries.
- No frontend transport change during the initial cutover (see §6, Phase C).

---

## 3. The governing constraint

**Under eventlet, non-yielding code is implicitly atomic. Under gthread it is not.**

Every finding in this plan descends from that one sentence. Green threads switch only at yield points, so a read-modify-write with no I/O in the middle can never be interleaved. Real OS threads preempt anywhere. Code that was correct by accident becomes racy.

The second-order constraint: **every long-lived request holds a real thread.** Gunicorn's gthread worker defaults to `--threads 1`. SSE streams, Socket.IO transports, internal loopbacks, and sleeping broker rate limiters each occupy one for their full lifetime.

---

## 4. Phase A — correctness gates (blocking)

None of these may be deferred past cutover.

### A1. Serialize server-originated Socket.IO emits

`socketio/server.py:157` in the installed library states: *"this method is not thread safe. If multiple threads are emitting at the same time to the same client, then messages composed of multiple packets may end up being sent in an incorrect sequence. Use standard concurrency solutions (such as a Lock object)."*

`subscribers/socketio_subscriber.py:5-6` currently asserts the opposite. That comment is wrong and must be corrected.

- Introduce one central emit boundary guarded by a process-wide `RLock`, route background/subscriber/request emits through it.
- Remove the 7 `socketio.start_background_task(socketio.emit, ...)` sites (`services/orderstatus_service.py:40,124,173,267`, `services/openposition_service.py:39,114`, `services/order_router_service.py:120`) — they spawn a native thread solely to call `emit()`.
- **Measure first.** The library warning is specific to *multi-packet* messages. Most OpenAlgo payloads are single-packet JSON. Instrument payload sizes before refactoring all 123 call sites; scope the change to what is actually exposed.

### A2. Make symbol-cache reload atomic

`database/token_db_enhanced.py:181-309` and `:695-708`. `clear_cache()` empties nine structures then sets `cache_loaded = False`.

Merely reordering the flag is **insufficient** — a reader can pass the `cache_loaded` check and then iterate while another thread clears. Required: build the new state off to the side and atomically swap a single reference; serialize writers with a load lock; retain the previous snapshot on failure. Readers must see the complete old snapshot or the complete new one, never a mix.

This is on the live-order symbol lookup path.

### A3. Protect shared `TTLCache` objects

cachetools does not make its mappings thread-safe. Verified: 12 active modules hold `TTLCache` instances with zero locks — `auth_db` (6 caches), `settings_db`, `user_db`, `traffic_db`, `flow_db`, `strategy_db`, `market_calendar_db`, `leverage_db`, `latency_db`, `telegram_db` (4), `whatsapp_db` (4), `utils/trading_calendar.py`.

`auth_db` is the priority: it holds auth records, feed tokens, broker selection, API-key verification results, and order mode — all on the live-order path.

`services/indicator_service.py` is the correct in-repo exemplar (TTLCache + single-flight registry, each with its own lock).

Protect compound `if key in cache` / get / delete / write sequences, not just individual operations. Keep DB, Argon2, and network work outside the lock.

### A4. Add bounded SQLite transaction retry

WAL, `synchronous=NORMAL`, `busy_timeout=15000` (landed in `658d44830`), and `NullPool` are in place. What is missing is retry for `SQLITE_BUSY_SNAPSHOT`, which returns immediately and cannot be waited out — only a restarted transaction fixes it.

- Bounded, jittered retry with a **fresh session per attempt**.
- Apply to idempotent local mutations on auth, order-log, settings, strategy, OAuth/MCP, and session paths.
- **The retry boundary must surround only the local transaction.** A broker order must never be placed twice because a post-order local write was retried at too broad a level.

### A5. Extend Python Strategy lock coverage to readers

`blueprints/python_strategy.py:64` already defines `PROCESS_LOCK = threading.RLock()`, and it guards the lifecycle entry points — `start_strategy_process` (line 423), stop (606), and three more sites. **The registries are not unsynchronized**, contrary to the audit's GT-07.

The real gap is coverage: 106 references to `RUNNING_STRATEGIES` / `STRATEGY_CONFIGS` against 6 lock sites, so read and iteration paths (line 215, status/list endpoints) run unguarded while writers mutate — risking dict-changed-size-during-iteration. Extend coverage to readers; do not hold the lock while waiting for a child process to exit.

### A6. Harden MCP (`MCP_HTTP_ENABLED=TRUE` only)

`blueprints/mcp_http.py`:

- `_scope_quota` (line 115) — unlocked read-modify-write, with the comment *"Single eventlet worker, so no shared-state concerns"* stating the premise that this migration invalidates. Add a lock and bound the key space; entries are pruned only when the same `(jti, scope)` recurs.
- `_audit_log` (line 344) — appends then size-triggered trims with no lock; concurrent requests can lose audit lines during rotation.
- `_initialized` — unlocked check-then-act, first exercised by the first MCP request rather than at startup.

### A7. Make WebSocket-proxy topology explicit

`websocket_proxy/app_integration.py:25` `_eventlet_active()` returns False under gthread, silently moving the proxy from a subprocess into the Gunicorn worker on native installs. The `greenlet.error` motivation (#1421) genuinely disappears, but production topology must not change as a side effect of a worker-class flag.

Replace eventlet detection with an explicit `WEBSOCKET_PROXY_MODE=external|subprocess|thread`: `external` in Docker (`start.sh:303` already runs it separately), `subprocess` in native Gunicorn production, `thread` for the dev server only. Preserve the SUB-binds/PUBs-connect invariant.

### A8. EventBus scoped-session cleanup

`utils/event_bus.py:60` `_safe_call()` has `try`/`except` but no `finally`. Ten persistent native workers query and write scoped SQLAlchemy sessions; `utils/db_sessions.py` states background threads must call `remove_all_scoped_sessions()`. Add it in a `finally`.

### A9. Sandbox / Analyzer engine review

**Not covered by the audit** — it must not ship unreviewed. The engine executes simulated orders and one known production instance runs Analyzer mode full-time.

Surfaces: `sandbox/execution_thread.py:33` (`ExecutionEngineThread`), the auto-upgrade thread at `:284`, `sandbox/websocket_execution_engine.py:434,468`, the squareoff thread, the startup `ThreadPoolExecutor` at `app.py:846-865`, and `sandbox.db`. Apply the same shared-state and thread-budget review as the Python Strategy host.

### A10. Assess shared HTTP client and rate-limiter state

Also uncovered by the audit:

- `utils/httpx_client.py` — shared client pool limits under N concurrent real threads.
- `limiter.py:7` — `Limiter(storage_uri="memory://", strategy="moving-window")`, in-process mutable rate-limit state on the API surface fronting order placement.

---

## 5. Phase B — thread budget and deployment

### B1. Size the thread pool from connection demand

`--worker-class gthread` without `--threads` is a one-request worker. Size from demand, not CPU count:

```text
required threads >=
    active Socket.IO transports
  + active Python Strategy SSE streams        (blueprints/python_strategy.py:2335, infinite)
  + active MCP SSE streams                    (blueprints/mcp_http.py:695, infinite)
  + internal loopback reserve (>=2 when MCP HTTP is enabled — dispatch re-enters this server)
  + requests parked in broker rate limiters   (see B2)
  + peak ordinary HTTP concurrency
  + failure/reconnect reserve
```

Canary at 32; evaluate 64 only if measurement demands it. Neither value is approved until the §7 gates pass.

### B2. Account for broker rate limiters and per-call executors

**Missing from the audit's formula.** Under eventlet a sleeping caller yields the hub for free. Under gthread it **holds a worker thread for the full sleep**.

Eight modules sleep-throttle: `angel/api/data.py`, `definedge/api/data.py`, `definedge/api/rate_limiter.py`, `dhan/api/data.py`, `flattrade/api/data.py`, `fyers/api/rate_limiter.py`, `iiflcapital/api/rate_limiter.py`, `tradesmart/api/data.py`. Angel's history limiter is 0.5s at ~2 req/s, so N concurrent history requests serialize into N × 0.5s of occupied threads. On a history-heavy workload this may be the largest term in B1.

Separately, per-call `ThreadPoolExecutor` in broker request paths multiplies with concurrent requests. Live under gthread: **nubra, iiflcapital, tradesmart**. For shoonya, definedge, flattrade and zebu the `USE_ASYNC` flip (§B4) makes the executor a dead branch.

### B3. Deployment surfaces

```text
gunicorn>=26.0,<27
gunicorn --worker-class gthread --workers 1 --threads ${GUNICORN_THREADS:-32} ... app:app
```

Files to change — the audit's GT-16 list **plus nine it omits**:

| In GT-16 | Omitted by GT-16 |
| --- | --- |
| `Dockerfile:8-13` | `install/enable-remote-mcp-docker.sh` |
| `requirements-nginx.txt:148-149` | `install/Remote-MCP-readme.md` |
| `start.sh:327-341` | `docs/design/11-docker/README.md` (9 refs) |
| `install/install.sh:766-776,1151-1157` | `docs/design/12-ubuntu-server/README.md` (4 refs) |
| `install/install-multi.sh:310-311,605-611` | `docs/design/06-websockets/README.md` |
| `install/update.sh:445-453` | `docs/design/34-app-startup/README.md` |
| `CONTRIBUTING.md:183,1059` | `docs/design/02-backend/README.md` |
| `CLAUDE.md:60-70` | `docs/design/20-design-principles/README.md` |
| | `docs/design/30-upgrade-procedure/README.md` |

`docs/` is the single source of truth per CLAUDE.md, so the design docs are a rollout requirement, not cosmetic.

Also: remove eventlet from `requirements-nginx.txt` and fresh-install commands; `uv pip install -r` does not prune an extraneous eventlet, so uninstall it explicitly. Keep `simple-websocket` pinned. Preserve nginx's `/socket.io/` upgrade locations. Keep `--timeout 300` initially and verify against both infinite SSE endpoints.

### B4. Broker validation matrix

`broker/` needs **one** genuine change. 19 files across 13 of 36 brokers reference eventlet:

- **No change (6 files):** zerodha (adapter + websocket), hdfcsky (websocket + api/data), arrow, dhan_sandbox — all guarded `else: _real_threading = threading` fallbacks that become no-ops.
- **Behaviour change (4 brokers):** `USE_ASYNC = not _is_eventlet_patched()` in shoonya, definedge, flattrade, zebu flips batch quotes from `ThreadPoolExecutor` to `asyncio.run()` + per-call `httpx.AsyncClient`. Requires live batch-quote, option-chain, timeout, rate-limit, exception-aggregation, and repeated-call FD/RSS tests per broker.
- **Comment-only (9 files):** upstox, mstock, dhan, shoonya, iiflcapital, angel — design rationale becomes void, code unaffected.

The `broker/*/streaming/` adapters were written for real OS threads from the start and are the best-prepared part of the codebase.

### B5. Diagnostics

`blueprints/admin.py:1206-1232` `_runtime_info()` defaults `wsgi_hint="flask-dev"` and only flips on active eventlet, so gthread would be misreported in production. Report Gunicorn version, worker class, configured and active threads, active Socket.IO and SSE counts, and proxy mode. Update `frontend/src/types/admin.ts:142`.

Replace the eventlet-monkeypatching `test/test_telegram_startup.py` with gthread-path tests.

---

## 6. Phase C — cutover, validation, rollback

1. Run the full suite with **no eventlet imported**.
2. Canary at 32 threads **with the frontend still pinned to polling** — isolate runtime correctness from transport change.
3. Exercise MCP, both SSE endpoints, both bots, strategies, and live Socket.IO events concurrently.
4. 24-hour soak: FD count, RSS, OS-thread count, executor queue depths, SQLite busy retries. Record baseline and final; static review is not completion evidence.
5. Only then stage the WebSocket transport change (§6.1).

### 6.1 Frontend transport (separate change)

All four Socket.IO constructors force `transports: ['polling'], upgrade: false` — `useSocket.ts:149`, `useOrderEventRefresh.ts`, `ActionCenter.tsx`, `WhatsAppIndex.tsx`. The comment claims WebSocket upgrade fails in threading mode; that is false on Gunicorn gthread with `simple-websocket`, which we verified directly.

Do not remove the pins in the same deployment as the worker change. Add nginx WebSocket-upgrade coverage first, unpin one representative client, observe, then migrate the rest.

### 6.2 Rollback

**Absent from the audit and mandatory here** — this is a runtime cutover on a platform placing live orders.

- Phase A is behaviour-preserving under eventlet and ships independently. It is not rolled back.
- The cutover itself is a one-line worker-class revert plus the `gunicorn<26` pin. Keep the previous pin reachable for the duration of the canary.
- **Abort criteria:** any unhandled `database is locked` in live-order paths; Socket.IO reconnect loops; thread-pool saturation causing `/health` timeouts; FD or RSS failing to plateau in soak; any broker batch-quote regression in the four `USE_ASYNC` brokers.
- Rehearse the revert on a non-production instance before the canary, not after an incident.

---

## 7. Acceptance gates

Ready only when all applicable gates pass. Full matrix in the audit §10; the load-bearing ones:

- Docker, native single, multi-instance, and updater all run Gunicorn 26 gthread, one worker, configured threads. No production process imports eventlet.
- With maximum expected Socket.IO + both SSE stream types connected, `/health`, login, and an ordinary API request hold defined p95/p99. MCP dispatch completes without self-deadlock.
- Concurrent sequence-event stress shows no loss, duplication, corruption, or reordering.
- No unhandled `database is locked` or `SQLITE_BUSY_SNAPSHOT`. Retry tests prove only local transactions repeat and broker orders remain exactly-once.
- Symbol-cache refresh serves a complete old or complete new snapshot, never a mix.
- API-key regeneration, logout, and token rollover cannot return stale auth/feed/broker/order-mode cache entries.
- FDs, RSS, thread count, queue depths, and registries plateau across repeated connect/disconnect cycles.

---

## 8. Corrections applied to the source audit

The audit was independently validated. 15 of 18 findings confirmed as stated. Corrections folded into this plan:

| Audit finding | Correction |
| --- | --- |
| GT-07 — "registries have no lifecycle synchronization boundary" | **Overstated.** `PROCESS_LOCK = threading.RLock()` exists at `python_strategy.py:64` and guards start (423), stop (606) and three more sites. Rescoped to reader coverage; severity P0 → P1 (§A5). |
| GT-14 — "no caller of `clear_strikes_cache()` was found" | **Factually wrong.** `broker/paytm/database/master_contract_db.py:395` calls it. The unbounded-key-space concern survives. |
| Inventory — "132 `socketio.emit` across 49 files" | Actual is **123 across 46** excluding tests. |
| GT-02 severity | Valid, but the library warning is specific to *multi-packet* messages. Measure payload sizes before refactoring 123 sites (§A1). |
| GT-16 — "every deploy surface" | Misses nine files (§B3). |
| Coverage | Sandbox engine (§A9), httpx/limiter (§A10), rollback (§6.2), broker rate limiters and per-call executors (§B2) were absent. |

---

## 9. Exit conditions

gthread remains correct while: one user and broker session per deployment; one worker; moderate browser/webhook/MCP/strategy concurrency; broker latency dominating; market ticks flowing through the separate asyncio/ZMQ proxy rather than the WSGI pool.

Revisit when OpenAlgo becomes multi-user, Socket.IO must span processes or hosts, concurrent stream clients routinely exceed a practical thread budget, service paths are intentionally converted to async end to end, or SQLite remains the write bottleneck *after* correct transaction boundaries — in which case the answer is PostgreSQL or a dedicated write owner, not a different HTTP server.

None of these is triggered merely by removing eventlet.
