# Admin, diagnostics, events, and WebSocket proxy gthread audit

**Date:** 2026-08-02  
**Branch / HEAD:** `gthread` / `fb6726777` (PR-13)  
**Scope:** `admin`, logs, health, latency, traffic, analyzer, `events/`,
`websocket_proxy/`, and `services/order_update_service.py`.  
**Mode:** audit only. No runtime code was changed by this audit.

## Verdict

The route-level conclusion is mostly correct: the admin, log, health, latency,
traffic, and analyzer blueprint modules have no SSE endpoints and do not create
threads or executors. `events/` is a passive event-schema package with no
runtime mutable registry. No new gthread blocker was found in those files.

The WebSocket conclusion is incomplete. `_POOLED_ADAPTERS` is one affected
surface, but the required change is not merely snapshotting two iterations.
The committed PR-13 `_POOL_LOCK` implementation fixes concurrent pool
creation and live iteration, but leaves pool ownership and invalidation races.
It is not ready to be described as complete or marked `done`.

## Validated claims

### Route modules

An AST census of these files found no thread/executor/scheduler construction
and no SSE response:

- `blueprints/admin.py`
- `blueprints/log.py`
- `blueprints/health.py`
- `blueprints/latency.py`
- `blueprints/traffic.py`
- `blueprints/analyzer.py`

`blueprints/admin.py::_BROKER_PROBE_HOSTS` is a static lookup table. The only
application use is `.get()`; no mutation was found.

The request-scoped database sessions are released either by the local teardown
handlers in health, latency, and traffic or by the global
`app.py::shutdown_database_sessions`, which calls
`utils.db_sessions.remove_all_scoped_sessions()` for every request.

The statement "threads/executors: none" must remain scoped to the blueprint
files. The backing product surfaces do use native concurrency:

- `utils/health_monitor.py` starts the `HealthCollector` thread.
- `utils/traffic_logger.py` owns a one-worker `traffic-log` executor.
- `utils/latency_monitor.py` owns a one-worker `latency-log` executor.
- `database/apilog_db.py` and `database/analyzer_db.py` each configure a
  ten-worker executor.

These are already represented by `GT-A12-06` and the `GT-B1-02` capacity
census; they are not new blockers, but they make the unqualified "none" claim
false.

### `events/`

The seven modules contain event types, constructors, and `__all__`. No locks,
threads, executors, schedulers, or mutable runtime registry were found. No
gthread change is required.

### `services/order_update_service.py`

`_ADAPTERS` is consistently guarded. The apparent unguarded
`_ADAPTERS.pop()` is inside `_stop_locked()`, and all three callers hold
`_LOCK`. It is safe because of that call contract, not merely because a single
CPython dictionary operation happens to be atomic.

## WebSocket proxy findings

### F1 — High: stale wrapper can remove a replacement pool

Current PR-13 code in `_PooledAdapterWrapper.disconnect()` disconnects its
own `self._pool`, then unconditionally removes the registry entry by key:

```python
self._pool.disconnect()
with _POOL_LOCK:
    _POOLED_ADAPTERS.pop(pool_key, None)
```

If invalidation removed pool A and a reconnect installed pool B under the same
key before stale wrapper A disconnects, A removes B. B remains referenced by
its new wrapper but is no longer visible to health reporting or cleanup.

Deterministic reproduction against the current worktree:

```text
replacement_survives_stale_disconnect=False
old_disconnects=1
new_disconnects=0
```

The removal must be identity-safe: remove only when
`_POOLED_ADAPTERS.get(pool_key) is self._pool`. The wrapper also needs a clear
ownership rule because multiple wrappers can intentionally share one pool.

### F2 — High: invalidation selection and removal are not atomic

`cleanup_pools_for_user()` snapshots matching keys under `_POOL_LOCK`, releases
the lock, then reacquires it separately for each `pop()`. A replacement can be
installed between those phases. The cleanup then removes and disconnects the
new pool even though the old pool was the one selected for invalidation.

Deterministic reproduction against the current worktree:

```text
selected_old_but_removed_new=True
old_disconnects=0
new_disconnects=1
```

Selection and detachment must happen in one critical section. Socket shutdown
can then happen outside the lock. The return value must count pools actually
detached, not the number of keys seen during the earlier snapshot.

### F3 — Medium: health snapshot count can disagree with its contents

`get_resource_health()` snapshots the items under `_POOL_LOCK`, computes
`pool_stats` from that snapshot, but later evaluates
`len(_POOLED_ADAPTERS)` outside the lock. Concurrent churn can therefore report
`active_pools.count != len(active_pools.pools)`. The count should derive from
the same snapshot.

### F4 — Medium: existing tests do not cover lifecycle ownership

`test/test_gthread_pool_registry.py` covers duplicate creation, iterator
survival, whole-registry cleanup, and structural lock placement. It has no test
for:

- stale-wrapper disconnect versus replacement creation;
- user invalidation versus reconnect;
- identity-safe removal;
- actual removed count;
- consistency of health count and pool contents.

Its churn helper also mutates `_POOLED_ADAPTERS` directly without `_POOL_LOCK`,
so it does not verify that every production writer follows the lock protocol.
Under eventlet monkey patching that tight no-yield churn test stalls; five
non-churn registry tests pass with eventlet 0.41.1.

### F5 — Low: tracker contains contradictory classifications

The tracker currently contains both:

- `GT-A12-01`: `_POOLED_ADAPTERS` is safe and needs no lock (`resolved`).
- `GT-A15-08`: `_POOLED_ADAPTERS` needed `_POOL_LOCK` and is complete (`done`).

The second row is marked done even though F1-F4 remain. Reconcile the two rows and reopen
`GT-A15-08` until lifecycle tests pass.

## Topology and eventlet compatibility

The production-topology observation is accurate with one qualification:

- Gunicorn uses `subprocess` mode and Docker uses `external` mode, so the
  Flask worker's registry is normally empty.
- The standalone proxy process performs its core registry lifecycle on one
  asyncio event-loop thread.
- Flask development mode runs the proxy in a real OS thread in the Flask
  process. The health collector and credential-update request paths can then
  access the same registry concurrently. This is a live pre-gthread surface.

The `_POOL_LOCK` itself is backward-compatible with eventlet: five applicable
registry tests passed under eventlet 0.41.1 monkey patching. The full six-test
file cannot currently serve as an eventlet regression gate because its churn
test contains a tight loop with no cooperative yield.

This does **not** establish that the whole branch cannot break an existing
eventlet deployment. It establishes only that the new registry lock primitive
does not inherently conflict with eventlet. The default deploy selector still
chooses eventlet, but feature-level eventlet regression coverage remains a
separate merge gate.

## Verification performed

```text
uv run pytest -q test/test_gthread_pool_registry.py
6 passed

eventlet 0.41.1, monkey patched, five non-churn registry tests
5 passed

deterministic stale-wrapper replacement check
FAILED: replacement pool was removed

deterministic invalidation/replacement check
FAILED: replacement pool was removed and old pool was not disconnected
```

## Required disposition

Do not merge PR-13 to main in its current form.
Treat the registry as one lifecycle unit:

1. Atomically select and detach pools during invalidation.
2. Make wrapper removal conditional on object identity.
3. Define whether wrappers share ownership (reference count / lease) or whether
   one wrapper is the sole owner; test that contract.
4. Derive health count and contents from one snapshot.
5. Add deterministic race tests for replacement and invalidation.
6. Reconcile `GT-A12-01` and reopen `GT-A15-08` until those tests pass.
