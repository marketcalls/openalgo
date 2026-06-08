# OpenAlgo File-Descriptor / Resource-Leak Audit

> **Generated**: June 2026
> **Scope**: SQLAlchemy engines/sessions, raw file handles, network sockets (HTTP/WebSocket/ZeroMQ), subprocesses, threads, executors, and schedulers across the full runtime codebase
> **Methodology**: Manual lifecycle tracing of every resource-acquiring call site. Severity is judged by whether the leak is unbounded in a long-running process (per-request / per-loop / per-reconnect) vs. bounded (import-time / startup singleton).
> **Status (updated)**: FD-1 and FD-3 are **RESOLVED** — all 32 broker engines now route through the shared `database/engine_factory.create_db_engine()` (NullPool on SQLite), merged in commit `7d59a62c`. This also defuses FD-2 (connections now close on session GC). Findings below are cross-reviewed (independent second pass by Codex); corrections from that review are folded in and marked.

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
| High | 2 | **RESOLVED** (commit `7d59a62c`) — broker DB engines held persistent pooled connections to `openalgo.db` with no release path; now all NullPool |
| Medium | 4 | FD-3 NullPool-invariant violation (resolved with FD-1); `oauth_db` session missing from teardown; one un-managed request-path query; one per-call executor |
| Low | 5 | Bounded / standalone-script / defensive-nit items (FD-8 covers three module-level `httpx.Client` singletons) |
| Informational | 3 | Doc inaccuracy (6 schedulers, not 3), dead code, per-request open that is correctly closed |

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

### [FD-3] 30 broker engines used bare `create_engine(DATABASE_URL)` (default QueuePool) — RESOLVED
- **Location**: `broker/{zerodha,dhan,angel,aliceblue,fyers,kotak,upstox,groww,paytm,pocketful,shoonya,flattrade,definedge,samco,motilal,mstock,nubra,rmoney,tradejini,wisdom,zebu,ibulls,iifl,iiflcapital,compositedge,jainamxts,fivepaisa,fivepaisaxts,firstock,dhan_sandbox}/database/master_contract_db.py` — e.g. `broker/zerodha/database/master_contract_db.py:27`:
  ```python
  engine = create_engine(DATABASE_URL)   # default QueuePool: 5 + 10 overflow = up to 15 FDs
  ```
- **Mechanism**: Default `QueuePool` (≈15 connections) to `openalgo.db`, created at import. Bounded per process (normally only the configured broker's module is imported), but it violates the NullPool invariant and, combined with FD-2, retains connections per thread.
- **Correction (cross-review)**: An earlier draft also claimed these omit `check_same_thread=False` and therefore risk SQLite "objects created in a thread can only be used in that same thread" errors. **That claim is withdrawn.** A direct probe on the pinned SQLAlchemy 2.x runtime confirmed that bare `create_engine('sqlite:///file.db')` yields a `QueuePool` and that cross-thread connection checkout does **not** raise — so the only real issue here is pooled-connection/FD retention, not a threading error.
- **Fix (applied)**: All `broker/*/database/master_contract_db.py` now use the shared `database/engine_factory.create_db_engine()` (NullPool on SQLite), preventing future drift across the 32 copies.

### [FD-4] `oauth_db` scoped session missing from teardown
- **Location**: `database/oauth_db.py` defines `db_session = scoped_session(...)` but is absent from `app.py:842-865`. Its callers in `utils/oauth_tokens.py` and `utils/oauth_keys.py` do not call `.remove()` either (confirmed: zero `db_session.remove()` across `oauth_db.py`/`oauth_tokens.py`/`oauth_keys.py`).
- **Mechanism**: Same as FD-2 but on a core DB. Damage is limited because `oauth_db` uses NullPool (the connection closes on session GC), so the leak is the session object rather than an FD — but it is an inconsistency in the otherwise-complete "19 sessions" list.
- **Fix**: Add `("database.oauth_db", "db_session")` to the teardown `_sessions` list.
- **Correction (cross-review)**: An earlier draft also flagged `database/whatsapp_db.py`. That is **withdrawn** — `whatsapp_db.py` calls `db_session.remove()` in the `finally` block of each of its helpers (lines 279, 324, 338, 361, 387, 428, 460, 521), so it cleans up locally and is not at risk.

### [FD-5] Un-managed scoped-session query in a request path — RESOLVED
- **Location**: `broker/groww/mapping/order_data.py:115`
- **Evidence**: `db_session.query(SymToken).filter_by(...).first()` — no `with` context, no `.remove()`. Runs during order-list mapping (per request).
- **Mechanism**: Holds the identity-mapped session/connection on the green thread; only released at process exit because no teardown removes the groww `db_session`.
- **Fix**: Wrap in `with db_session() as session:` like the other groww call sites, and fix FD-2.

### [FD-6] Per-call `ThreadPoolExecutor` never shut down (Flow Telegram alerts) — RESOLVED
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
| FD-8 | `broker/tradejini/database/master_contract_db.py:20`; `services/telegram_alert_service.py:33`; `broker/dhan/api/gtt_api.py:30` | Module-level `httpx.Client` never explicitly closed | App-lifetime singletons (one per process), bounded; should route through `get_httpx_client()` or close on shutdown. (Added telegram_alert/dhan-gtt per cross-review.) |
| FD-9 | `sandbox/execution_thread.py:78` | Probe `socket.socket` closed but not in `try/finally` | `connect_ex` returns a code rather than raising; practical leak risk near zero — wrap in `with` for robustness |
| FD-10 | `blueprints/python_strategy.py:483` | Raw `open()` for subprocess stdout | Deliberate and closed on all paths (lines 535/542/553/564); defensive nit only |
| FD-11 | `blueprints/historify.py:278,488` + `database/historify_db.py` exports | Temp export files orphaned if the user never downloads | Disk residue, not an FD leak; bounded by user action; cleaned in the download endpoint's `finally` |

---

## Informational

- **[I-1] Scheduler count vs. docs**: CLAUDE.md says Flow and Historify "share the same scheduler instance," but there are at least **six** independent `BackgroundScheduler` instances: `blueprints/python_strategy.py:110`, `services/flow_scheduler_service.py:57`, `services/historify_scheduler_service.py:60`, and — added per cross-review — `blueprints/chartink.py:58`, `blueprints/strategy.py:59`, and `sandbox/squareoff_thread.py:330`. Each is a properly-guarded singleton (bounded total) — not a leak, but the doc is inaccurate and the count is higher than stated.
- **[I-2] Dead code**: `services/telegram_bot_service_v2.py:42` and `services/telegram_bot_service_fixed.py:42` each create an `httpx.AsyncClient` but are not imported anywhere — candidates for deletion (no runtime impact).
- **[I-3] Per-request audit log open** `blueprints/mcp_http.py:348` uses `with _AUDIT_PATH.open("a")` per MCP request — opened and closed each call, FD-safe (minor perf only).

---

## Confirmed Clean (no action)

- **File handles**: ~250+ `open(...)` sites are virtually all `with open(...)`. Zero `json.load(open())`, zero `pd.read_csv(open())`, zero chained `open().read()/.write()`, no `os.open`/`os.fdopen`/`os.popen`. Every `gzip.open`/`ZipFile`/`urlopen` is context-managed.
- **Temp files**: `mkstemp` (`whatsapp_bot_service.py:344`) closes the fd on the next line; `NamedTemporaryFile(delete=False)` (`historify.py:778`) is `.close()`d and `os.remove`d in `finally`.
- **Streaming reconnect loops**: leak-free. `run_forever`-style adapters (zerodha, fyers, dhan, upstox) only reassign `self.ws` after the prior `run_forever()` returns (socket already torn down). Explicit-cleanup adapters (angel `_cleanup_websocket`, iiflcapital MQTT, rmoney socketio) close the old connection before reconnecting.
- **ZeroMQ bus**: shared `zmq.Context` is reference-counted; sockets closed with `linger=0` and context `.term()`'d on last-adapter cleanup (`websocket_proxy/base_adapter.py:298-348`), including the bind-failure path. SUB socket + context closed on server shutdown (`server.py:281-314`).
- **Shared HTTP client**: `utils/httpx_client.py:184` is the canonical pooled singleton with `cleanup_httpx_client()` on shutdown; per-request `httpx.Client` uses elsewhere are all `with`/`async with` managed. **Caveat (cross-review)**: a few bounded module-level `httpx.Client` singletons are created outside this helper and never explicitly closed — `services/telegram_alert_service.py:33`, `broker/dhan/api/gtt_api.py:30`, `broker/tradejini/database/master_contract_db.py:20` (see FD-8). One per process, so not an accumulating leak, but they are not "clean" in the strict sense.
- **Broker engines/connections (full `broker/` sweep)**: after the NullPool fix, a sweep of the entire `broker/` tree found **no** raw `create_engine()` calls, **no** `scoped_session`/`sessionmaker` outside the 32 master-contract modules, **no** raw `sqlite3.connect`/`duckdb.connect`, and every `engine.connect()` inside a `with` block. No QueuePool engine remains at the broker level.
- **Strategy Host lifecycle**: child stdout/stderr go to a **log file**, not a `PIPE` (`python_strategy.py:500-501`), so there are no orphaned pipe FDs or reader threads. Parent closes the inherited handle immediately after `Popen` (lines 563-566). Stop/restart `.terminate()`+`.wait()` reaps children; a 60s `cleanup_dead_processes` job and `atexit` handler prevent zombie/entry accumulation.
- **Sockets**: raw socket probes (latency/health/admin) are closed; reconnect paths close before reopening.

---

## Remediation Priority

| Priority | Items | Status | Fix |
| --- | --- | --- | --- |
| 1 | FD-1, FD-3 (all 32 broker engines) | **DONE** (commit `7d59a62c`) | Standardized on the shared `database/engine_factory.create_db_engine()` (NullPool on SQLite) |
| 2 | FD-2 | Mostly defused by #1 | Under NullPool a missing `.remove()` leaks only a session object, not an FD; optionally still add the active broker `db_session` to `app.py` teardown |
| 3 | FD-4 | Open | Add `oauth_db` (only) to the teardown `_sessions` list |
| 4 | FD-5 | **DONE** | Wrapped groww `order_data.py:115` query in `with db_session() as session:` |
| 5 | FD-6 | **DONE** | Reuses the shared `telegram_alert_service.alert_executor` instead of a per-call pool |
| 6 | FD-7..FD-11, I-2 | Open (Low) | Opportunistic cleanups |

The highest-leverage change — **standardizing the broker engine creation** (priority 1) — is now complete: it resolved FD-1 and FD-3 across all 32 brokers and rendered FD-2 mostly harmless in one stroke, restoring the documented "NullPool everywhere" invariant. A full `broker/` sweep confirms no QueuePool engine or raw DB connection remains at the broker level.

---

## Scope and Limitations

This audit traced resource lifecycles statically across the runtime tree (`blueprints/`, `services/`, `broker/`, `utils/`, `database/`, `websocket_proxy/`, `mcp/`, `sandbox/`). It did not include runtime FD measurement (e.g. `lsof`/`/proc/<pid>/fd` under load) or load testing to observe pool-exhaustion empirically — both are recommended as a follow-up to quantify FD-1 in production. `test/`, `examples/`, and one-time `upgrade/` scripts were deprioritized. No files were modified during this audit.
