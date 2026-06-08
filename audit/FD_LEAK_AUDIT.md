# OpenAlgo File-Descriptor / Resource-Leak Audit

> **Generated**: June 2026
> **Scope**: SQLAlchemy engines/sessions, raw file handles, network sockets (HTTP/WebSocket/ZeroMQ), subprocesses, threads, executors, and schedulers across the full runtime codebase
> **Methodology**: Manual lifecycle tracing of every resource-acquiring call site. Severity is judged by whether the leak is unbounded in a long-running process (per-request / per-loop / per-reconnect) vs. bounded (import-time / startup singleton).

---

## Why this audit

OpenAlgo runs as a single long-lived process (Gunicorn `-w 1` + eventlet in production). In that model, any resource opened per-request, per-loop, or per-reconnect and not released accumulates until the process hits the OS file-descriptor limit and starts failing. CLAUDE.md makes two specific FD-hygiene claims that this audit verifies:

1. *"All SQLite databases use NullPool"* — each operation gets a fresh connection closed immediately.
2. *"FD leak prevention is handled by 5 layers of session cleanup."*

**Claim 2 is TRUE and confirmed. Claim 1 is FALSE for the broker layer** — this is where the real findings are.

---

## Executive Summary

| Severity | Count | Nature |
| --- | --- | --- |
| High | 2 | Broker DB engines hold persistent pooled connections to `openalgo.db` with no release path; can grow to the pool cap and exhaust connections |
| Medium | 4 | NullPool-invariant violations, two scoped sessions missing from teardown, one un-managed request-path query, one per-call executor |
| Low | 5 | Bounded / standalone-script / defensive-nit items |
| Informational | 3 | Doc inaccuracy, dead code, per-request open that is correctly closed |

**Most of the codebase is clean.** Raw file-handle hygiene is excellent (no `json.load(open())`, no `read_csv(open())`, no `with`-less leaks in runtime paths). Streaming WebSocket reconnect loops, the ZeroMQ bus, and — importantly — the Python Strategy Host start/stop/restart lifecycle are all leak-free. The problems are concentrated in the per-broker `master_contract_db.py` modules, which diverge from the hardened core-database pattern.

---

## Verification of CLAUDE.md claims

### "5 layers of session cleanup" — CONFIRMED
All five exist and actually call `.remove()`:
1. `app.py:836-875` `@app.teardown_appcontext shutdown_database_sessions` — iterates 19 sessions, calls `session.remove()`.
2. `utils/traffic_logger.py:53` `logs_session.remove()` in `finally`.
3. `utils/security_middleware.py:64` `logs_session.remove()` (banned-IP WSGI path).
4. `blueprints/traffic.py:219` teardown handler.
5. `blueprints/security.py:534` teardown handler.

### "All SQLite databases use NullPool" — FALSE for brokers
The 22 core `database/*.py` modules correctly use the guarded pattern (NullPool on SQLite, QueuePool only on the Postgres branch) — see `database/auth_db.py:158-168` as the reference. But **none of the 32 `broker/*/database/master_contract_db.py` modules use NullPool**, and **none appear in the teardown list**.

---

## High Findings

### [FD-1] Broker master-contract engines use a real connection pool on SQLite (indmoney, deltaexchange)
- **Location**: `broker/indmoney/database/master_contract_db.py:27`; `broker/deltaexchange/database/master_contract_db.py:20`
- **Evidence**:
  ```python
  engine = create_engine(
      DATABASE_URL,
      pool_size=20, max_overflow=50,      # up to 70 persistent connections to openalgo.db
      pool_timeout=30, pool_recycle=3600,
      connect_args={"timeout": 30, "check_same_thread": False},
  )
  ```
- **Mechanism**: This holds a QueuePool of up to `pool_size + max_overflow = 70` open connections (each an FD) to the single `db/openalgo.db` file, contradicting the "NullPool everywhere, zero idle connections" invariant. Symbol→token lookups run on this engine on every order/quote request. Because the scoped session is **never removed** (see FD-2), each eventlet green thread retains a session holding a checked-out connection; under load these climb toward the 70-connection cap.
- **Impact**: Persistent FD growth to the pool cap, and — once the cap is reached — `pool_timeout` (30s) blocking followed by `TimeoutError` on new checkouts, i.e. order/quote failures under concurrency. This is the worst case of the NullPool-invariant violation.
- **Fix**: Replace with the guarded pattern from `database/auth_db.py:158-168` (NullPool on SQLite). WAL/pragmas can still be applied once at import via a short-lived `with engine.connect()`.

### [FD-2] All 32 broker `db_session` scoped sessions have no `.remove()` teardown
- **Location**: every `broker/*/database/master_contract_db.py` (`db_session = scoped_session(...)`); none are in `app.py:842-865`, and there are **zero `.remove()` calls in the entire `broker/` tree**.
- **Mechanism**: A `scoped_session` keeps one `Session` per (green) thread. With no per-request `.remove()`, each session — and the DB connection it holds — lives until the thread dies or the process exits. On the default-QueuePool brokers (FD-3) and especially the pooled brokers (FD-1), that connection is a persistent FD; on a hypothetical NullPool broker it would at least close the connection on GC but still leak the session object.
- **Impact**: Connections/FDs accumulate per worker thread with no release path. This is the structural root cause that makes FD-1 and FD-3 actually leak rather than stay bounded.
- **Fix**: (a) Switch all broker engines to NullPool (so a missing `.remove()` only leaks a cheap session object, not an FD), **and** (b) add the active broker's `db_session` to the `app.py` teardown loop. The teardown already imports modules dynamically, so adding the configured broker's module is straightforward. Minimum viable fix: do (a) for all brokers.

---

## Medium Findings

### [FD-3] 30 broker engines use bare `create_engine(DATABASE_URL)` (default QueuePool, `check_same_thread` not disabled)
- **Location**: `broker/{zerodha,dhan,angel,aliceblue,fyers,kotak,upstox,groww,paytm,pocketful,shoonya,flattrade,definedge,samco,motilal,mstock,nubra,rmoney,tradejini,wisdom,zebu,ibulls,iifl,iiflcapital,compositedge,jainamxts,fivepaisa,fivepaisaxts,firstock,dhan_sandbox}/database/master_contract_db.py` — e.g. `broker/zerodha/database/master_contract_db.py:27`:
  ```python
  engine = create_engine(DATABASE_URL)   # default QueuePool: 5 + 10 overflow = up to 15 FDs
  ```
- **Mechanism**: Default `QueuePool` (≈15 connections) to `openalgo.db`, created at import. Bounded per process (normally only the configured broker's module is imported), but it still violates the NullPool invariant and, combined with FD-2, retains connections per thread. It also omits `check_same_thread=False`, which risks SQLite "objects created in a thread can only be used in that same thread" errors.
- **Fix**: Apply the guarded NullPool pattern to all `broker/*/database/master_contract_db.py`. A single shared helper (e.g. `database/engine_factory.py`) would prevent future drift across 32 copies.

### [FD-4] `oauth_db` and `whatsapp_db` scoped sessions missing from teardown
- **Location**: `database/oauth_db.py` and `database/whatsapp_db.py` define `db_session = scoped_session(...)` but are absent from `app.py:842-865`.
- **Mechanism**: Same as FD-2 but on core DBs. Damage is limited because both use NullPool (the connection closes on session GC), so the leak is the session object rather than an FD — but it is an inconsistency in the otherwise-complete "19 sessions" list.
- **Fix**: Add `("database.oauth_db", "db_session")` and `("database.whatsapp_db", "db_session")` to the teardown `_sessions` list.

### [FD-5] Un-managed scoped-session query in a request path
- **Location**: `broker/groww/mapping/order_data.py:115`
- **Evidence**: `db_session.query(SymToken).filter_by(...).first()` — no `with` context, no `.remove()`. Runs during order-list mapping (per request).
- **Mechanism**: Holds the identity-mapped session/connection on the green thread; only released at process exit because no teardown removes the groww `db_session`.
- **Fix**: Wrap in `with db_session() as session:` like the other groww call sites, and fix FD-2.

### [FD-6] Per-call `ThreadPoolExecutor` never shut down (Flow Telegram alerts)
- **Location**: `services/flow_openalgo_client.py:567`
- **Evidence**:
  ```python
  alert_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="flow_telegram")
  alert_executor.submit(telegram_alert_service.send_alert_sync, telegram_id, formatted_message)
  ```
- **Mechanism**: A new executor (and its non-daemon worker thread) is created on every Flow alert-node firing and dropped without `.shutdown()`. Each worker exits after its single task, so it is bounded by alert concurrency rather than truly unbounded, but it is needless thread churn that contradicts the shared-pool pattern used everywhere else.
- **Fix**: Reuse the existing module-level shared pool `services/telegram_alert_service.py:30` (`alert_executor`) — call `telegram_alert_service.alert_executor.submit(...)` and delete the local executor.

---

## Low Findings

| ID | Location | Issue | Why Low |
| --- | --- | --- | --- |
| FD-7 | `download/sqlite_downloader.py:31` | Non-NullPool SQLite engine | Standalone historical-data script, not a request path |
| FD-8 | `broker/tradejini/database/master_contract_db.py:20` | Module-level `httpx.Client` never closed | App-lifetime singleton (one per process), bounded; should route through `get_httpx_client()` |
| FD-9 | `sandbox/execution_thread.py:78` | Probe `socket.socket` closed but not in `try/finally` | `connect_ex` returns a code rather than raising; practical leak risk near zero — wrap in `with` for robustness |
| FD-10 | `blueprints/python_strategy.py:483` | Raw `open()` for subprocess stdout | Deliberate and closed on all paths (lines 535/542/553/564); defensive nit only |
| FD-11 | `blueprints/historify.py:278,488` + `database/historify_db.py` exports | Temp export files orphaned if the user never downloads | Disk residue, not an FD leak; bounded by user action; cleaned in the download endpoint's `finally` |

---

## Informational

- **[I-1] Scheduler count vs. docs**: CLAUDE.md says Flow and Historify "share the same scheduler instance," but there are three independent `BackgroundScheduler` singletons (`blueprints/python_strategy.py:110`, `services/flow_scheduler_service.py:57`, `services/historify_scheduler_service.py:60`). Each is a properly-guarded singleton (bounded at 3 total) — not a leak, but the doc is inaccurate.
- **[I-2] Dead code**: `services/telegram_bot_service_v2.py:42` and `services/telegram_bot_service_fixed.py:42` each create an `httpx.AsyncClient` but are not imported anywhere — candidates for deletion (no runtime impact).
- **[I-3] Per-request audit log open** `blueprints/mcp_http.py:348` uses `with _AUDIT_PATH.open("a")` per MCP request — opened and closed each call, FD-safe (minor perf only).

---

## Confirmed Clean (no action)

- **File handles**: ~250+ `open(...)` sites are virtually all `with open(...)`. Zero `json.load(open())`, zero `pd.read_csv(open())`, zero chained `open().read()/.write()`, no `os.open`/`os.fdopen`/`os.popen`. Every `gzip.open`/`ZipFile`/`urlopen` is context-managed.
- **Temp files**: `mkstemp` (`whatsapp_bot_service.py:344`) closes the fd on the next line; `NamedTemporaryFile(delete=False)` (`historify.py:778`) is `.close()`d and `os.remove`d in `finally`.
- **Streaming reconnect loops**: leak-free. `run_forever`-style adapters (zerodha, fyers, dhan, upstox) only reassign `self.ws` after the prior `run_forever()` returns (socket already torn down). Explicit-cleanup adapters (angel `_cleanup_websocket`, iiflcapital MQTT, rmoney socketio) close the old connection before reconnecting.
- **ZeroMQ bus**: shared `zmq.Context` is reference-counted; sockets closed with `linger=0` and context `.term()`'d on last-adapter cleanup (`websocket_proxy/base_adapter.py:298-348`), including the bind-failure path. SUB socket + context closed on server shutdown (`server.py:281-314`).
- **Shared HTTP client**: `utils/httpx_client.py:184` is the canonical pooled singleton with `cleanup_httpx_client()` on shutdown; per-request `httpx.Client` uses elsewhere are all `with`/`async with` managed.
- **Strategy Host lifecycle**: child stdout/stderr go to a **log file**, not a `PIPE` (`python_strategy.py:500-501`), so there are no orphaned pipe FDs or reader threads. Parent closes the inherited handle immediately after `Popen` (lines 563-566). Stop/restart `.terminate()`+`.wait()` reaps children; a 60s `cleanup_dead_processes` job and `atexit` handler prevent zombie/entry accumulation.
- **Sockets**: raw socket probes (latency/health/admin) are closed; reconnect paths close before reopening.

---

## Remediation Priority

| Priority | Items | Effort | Fix |
| --- | --- | --- | --- |
| 1 | FD-1, FD-3 (all 32 broker engines) | Medium | Standardize on the guarded NullPool pattern (`auth_db.py:158-168`); ideally extract a shared `create_db_engine()` helper |
| 2 | FD-2 | Low/Medium | After NullPool, optionally add the active broker `db_session` to `app.py` teardown |
| 3 | FD-4 | Trivial | Add `oauth_db`, `whatsapp_db` to the teardown `_sessions` list |
| 4 | FD-5 | Trivial | Wrap groww `order_data.py:115` query in `with db_session()` |
| 5 | FD-6 | Trivial | Reuse `telegram_alert_service.alert_executor` |
| 6 | FD-7..FD-11, I-2 | Low | Opportunistic cleanups |

The single highest-leverage change is **standardizing the broker engine creation** (priority 1): it resolves FD-1 and FD-3 across all 32 brokers and renders FD-2 mostly harmless in one stroke, restoring the documented "NullPool everywhere" invariant.

---

## Scope and Limitations

This audit traced resource lifecycles statically across the runtime tree (`blueprints/`, `services/`, `broker/`, `utils/`, `database/`, `websocket_proxy/`, `mcp/`, `sandbox/`). It did not include runtime FD measurement (e.g. `lsof`/`/proc/<pid>/fd` under load) or load testing to observe pool-exhaustion empirically — both are recommended as a follow-up to quantify FD-1 in production. `test/`, `examples/`, and one-time `upgrade/` scripts were deprioritized. No files were modified during this audit.
