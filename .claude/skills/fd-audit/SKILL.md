---
name: fd-audit
description: Audit a change for resource leaks in OpenAlgo — file descriptors AND unbounded memory growth. Run after building a feature or fixing anything that touches databases, WebSockets or streaming, threads or executors, subprocesses, files, sockets, caches, or module-level registries. Also use when the user reports "too many open files", refused DB connections, dropped sockets, rising RSS, or a Gunicorn worker that degrades over hours or days.
---

# Resource leak audit — descriptors and memory

OpenAlgo runs production as a **single long-lived Gunicorn worker**
(`--worker-class eventlet -w 1`). It never restarts between deploys, so anything
leaked once per request accumulates until the process dies. There is no second
worker to absorb the failure and no natural recycling point.

Two failure modes, same root cause — unbounded growth in a process that never
restarts:

| | Symptom | Ceiling |
| --- | --- | --- |
| **Descriptors** | `OSError: [Errno 24] Too many open files`, refused DB connections, dropped WebSocket clients | OS `ulimit -n` (often 1024–65535) |
| **Memory** | Rising RSS, swap thrash, OOM-killer, gradual latency creep | Host RAM |

Audit **the change you just made**, not the whole repo.

## Step 1 — scope

If the change touches none of these, the audit is done. Say so and move on.

**Descriptor-holding:** SQLAlchemy engines/sessions · DuckDB connections · HTTP
clients · WebSockets · ZeroMQ sockets · subprocesses · files · raw sockets ·
threads and executors · `inotify`/selectors

**Memory-holding:** module-level dicts, lists and sets · caches · event-bus
subscriptions · SocketIO rooms · registries keyed by symbol/user/strategy ·
retained DataFrames · closures capturing large objects

## Step 2 — descriptor conventions

**SQLite engines.** Only via `database.engine_factory.create_db_engine()`, which
applies `NullPool`. Never `create_engine()` directly, never `StaticPool` — a
shared connection has its cursor state corrupted under concurrency, producing
`"bad parameter or other API misuse"` and `"cannot commit - SQL statements in
progress"`.

**DuckDB is separate.** `database/historify_db.py` calls `duckdb.connect()`
directly — it does **not** go through `engine_factory` and `NullPool` does not
apply. Each connection is an FD plus a memory arena. Use a context manager or
guarantee `.close()`; a DuckDB connection left open also holds its buffer pool.

**Sessions.** Every `scoped_session` is either registered in the `app.py`
`teardown_appcontext` handler or used as `with db_session() as session:`. A
`scoped_session` created in a module and never `.remove()`d holds a connection
per green thread forever. Existing cleanup layers to match: `app.py` teardown,
`traffic_logger.py` `logs_session.remove()` in a `finally`,
`security_middleware.py` for the banned-IP WSGI path, and teardown handlers in
`blueprints/traffic.py` and `blueprints/security.py`.

**HTTP.** Use the shared `utils/httpx_client.get_httpx_client()`. A per-call
`httpx.Client()` opens a fresh connection pool and leaks it unless closed; the
shared client is what keeps HTTP/2 keep-alive to broker APIs working. Always
pass an explicit `timeout=` — a hung request holds its socket indefinitely,
which is a slow leak that looks like a hang.

**WebSocket adapters.** Close before reconnect. A reconnect path that opens a
new socket without closing the old one leaks one descriptor per retry — and
retries run unbounded during a broker outage, which is exactly when you cannot
afford it.

**ZeroMQ.** Sockets closed on shutdown and adapter teardown; `cleanup_zmq()` in
`disconnect()`. Never create a context per call. Read the SUB-binds/PUBs-connect
invariant in `CLAUDE.md` before changing any bind/connect.

**Subprocesses.** Write to a log file, not `PIPE`, and `.wait()`-reap. An
unreaped child leaves a zombie plus its pipe FDs; undrained `PIPE` output
deadlocks the child once the buffer fills. Note `telegram_bot_service`'s kaleido
renderer spawns a real OS thread *and* an image-export subprocess — both must be
joined/reaped on every path.

**Threads and executors.** Shared module-level singletons. Never a
`ThreadPoolExecutor` per call or per request — each holds threads plus an
internal control pipe until shut down. Under eventlet, `threading.local()` maps
to green threads, so per-green-thread state accumulates with connection count,
not with CPU count.

**Files.** `with` blocks. Temp files cleaned up via `tempfile` context managers.

## Step 3 — memory conventions

Descriptors have a hard OS ceiling that surfaces loudly. Memory degrades quietly,
so it needs deliberate checking.

**Every cache needs a bound.** A plain `dict` used as a cache never evicts. Use
`cachetools.TTLCache(maxsize=..., ttl=...)` — the codebase already standardises
on it (`database/telegram_db.py`, `latency_db.py`, `token_db_backup.py`,
`flow_db.py`). Both parameters matter: `maxsize` bounds memory, `ttl` bounds
staleness.

Known unbounded collections to model your review on — check whether yours looks
like these:

- `services/option_symbol_service.py:_STRIKES_CACHE` — plain dict keyed by `(symbol, exchange, expiry, type)`, no eviction. Grows with every distinct instrument queried.
- `blueprints/python_strategy.py:RUNNING_STRATEGIES` / `STRATEGY_CONFIGS` — keyed by strategy id; correct only if entries are deleted on stop, not just on graceful stop.
- `websocket_proxy/broker_factory.py:_POOLED_ADAPTERS` and `services/order_update_service.py:_ADAPTERS` — keyed by `{broker}_{user_id}`; bounded in practice because OpenAlgo is single-user, but verify entries are removed on disconnect.

**Registries need a matching removal.** For every `dict[key] = value`,
`join_room`, `subscribe`, `append`, or `add` on module-level state, find the
line that removes it — and confirm it runs on the error path too. Subscription
without unsubscription is the most common memory leak in an event-driven app.

**Ask "what is the key space?"** A dict keyed by user id is bounded (one user).
Keyed by symbol, strategy id, request id, or session id, it is not. Unbounded
key space plus no eviction equals a leak, however small each entry is.

**Retained DataFrames.** History and option-chain paths build large pandas
objects. Don't stash them on module-level state or in a closure that outlives
the request.

## Step 4 — check every exit path

For each resource, confirm release on all three, not just the happy one:

1. Success
2. Exception — `finally` or a context manager, not a trailing close statement
3. Reconnect / retry loops

Retry loops are the most common real leak: the code closes on success and on
error, but the `continue` in the retry branch skips the close.

## Step 5 — measure, don't just read

Static review misses leaks that only appear under repetition. When a leak is
suspected rather than hypothetical:

```bash
# Descriptor count for the running worker, sampled over time
PID=$(pgrep -f "gunicorn.*app:app" | head -1)
lsof -p "$PID" | wc -l          # macOS and Linux
ls /proc/$PID/fd | wc -l        # Linux, cheaper

# What kind of descriptor is growing
lsof -p "$PID" | awk '{print $5}' | sort | uniq -c | sort -rn | head

# RSS over time
ps -o rss=,vsz= -p "$PID"
```

Take a baseline, drive the suspect path in a loop (100+ iterations), sample
again. **A flat count after N iterations is the only real proof.** A count that
rises and plateaus is a cache filling; one that rises linearly is a leak.

For memory specifically, `tracemalloc` around the suspect path gives allocation
sites directly:

```python
import tracemalloc
tracemalloc.start()
snap1 = tracemalloc.take_snapshot()
# ...drive the path N times...
snap2 = tracemalloc.take_snapshot()
for s in snap2.compare_to(snap1, "lineno")[:10]:
    print(s)
```

## Step 6 — report

If everything holds, state which resources you checked and that each is released
on all paths — and say whether you verified statically or by measurement.

If you find a leak, **do not silently fix it and do not proceed with other
work.** Report:

- Exact file and line where the resource is acquired
- Which exit path fails to release it
- Whether it is descriptor or memory, and what bounds the growth (nothing, a cache size, the key space)
- Production cost: a single-worker Gunicorn/eventlet process that never restarts accumulates until it hits the OS descriptor limit or host RAM — "too many open files", refused DB connections, dropped sockets, OOM, forced restart

Then ask the user to approve the fix before applying it.
