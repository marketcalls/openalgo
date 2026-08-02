# PR-13 — Guarding the pooled broker adapter registry

**Status:** Done · **Tracker item:** GT-A15-08 · **Runs on:** both

## How this was found

An audit of the pages nobody had reviewed — admin, logs, health, latency,
diagnostics — plus `events/` and `websocket_proxy/`.

**The pages themselves were clean.** No module-level state, no SSE endpoints (so
they cost nothing from the thread budget), no background threads, and database
sessions properly torn down. `events/` was clean too.

The problem was one module: `websocket_proxy/broker_factory.py`, whose registry
of live broker connection pools had **no lock at all**.

## What could go wrong

**A leaked broker connection.** Creating a pool was a check-then-create:

```python
if pool_key in _POOLED_ADAPTERS:
    self._pool = _POOLED_ADAPTERS[pool_key]
else:
    _POOLED_ADAPTERS[pool_key] = ConnectionPool(...)
```

Two threads could both miss the check and each build a pool. The second
registration overwrites the first, and **the orphaned pool keeps its broker
WebSocket connections open with no reference left to disconnect it**. That is a
descriptor leak in a process that never restarts, not a wasted object.

Reproduced: eight threads racing on one key produced **eight pools**.

**A crashing diagnostics page.** `get_pool_stats()` and `get_resource_health()`
iterated the live dictionary. Both are reachable from `utils/health_monitor.py`,
which runs on a background daemon thread, so a pool appearing or disappearing
mid-loop raises `RuntimeError: dictionary changed size during iteration`.

## Why this is not only a gthread issue

Under Gunicorn the WebSocket proxy runs **out of process**, so the worker's copy
of the registry stays empty and iterating it is incidentally safe. That safety
is a side effect of the deployment shape, not of the code.

In `thread` mode — `uv run app.py` on Windows and macOS — the proxy shares the
process. The registry is populated, the health collector iterates it on its own
thread, and **this is a live race today**, with or without the migration.

## What changed

A reentrant `_POOL_LOCK`:

- **Lookup and registration are atomic**, so exactly one pool exists per key.
- **Readers snapshot under the lock and call `get_stats()` outside it.**
  Holding the lock across `get_stats()` would let a diagnostics page stall a
  broker connect — trading a crash for a stall.
- **Cleanup paths mutate under the lock** but `disconnect()` outside it, since
  closing sockets can block.

## How we know it works

`test/test_gthread_pool_registry.py` — **6 checks**, all passing.

Mutation-verified. Restoring the original check-then-create produces the
message that makes the cost concrete:

```
8 pools created for one key; the extras hold broker sockets
that nothing will ever disconnect
```

Restoring the live iteration fails the churn test. A structural check also
covers functions that do not exist yet, and a further check asserts
`get_stats()` is never called while the lock is held.

## Scope note

The pages that prompted this audit need **no changes**. Their database layers
were already covered by earlier rows, they hold no shared state, and they open
no streams.
