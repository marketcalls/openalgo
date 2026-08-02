# PR-12 — Making the /python strategy host thread-safe

**Status:** Done · **Tracker items:** GT-A14-01 (done), GT-A14-02 (open) · **Runs on:** both

## Why this was nearly missed

The Python Strategy Host is 2,999 lines and keeps two module-level registries:
`STRATEGY_CONFIGS` (saved strategies) and `RUNNING_STRATEGIES` (live
subprocesses). They are reached from request handlers, from the APScheduler jobs
that start and stop strategies at IST times, and from a dead-process sweep — all
of which are separate real threads under gthread.

**103 references. Only 38 inside `PROCESS_LOCK`.**

The whole migration had covered exactly *one* row here: the scheduler's
misfire grace time. Everything else looked clean, because the check-then-act
gate said so.

It was wrong. The gate collects guards only from attribute nodes — it sees
`self.foo` and is **blind to a bare module-level name** like
`STRATEGY_CONFIGS`. A file whose entire state is module-level dicts is
invisible to it. That is the third blind spot of this shape found in this
migration, after the symbol-snapshot properties and the tracker-count drift.

## What actually breaks

Two shapes, neither reachable under eventlet because nothing yields between the
two statements, both reachable on real threads:

**Listing while another thread creates a strategy.**

```python
for sid, config in STRATEGY_CONFIGS.items():   # another thread adds one
    ...                                        # RuntimeError: dictionary changed size
```

This is the worst one, because the loop body calls `check_process_status()` and
can call `save_configs()` — a file write — per entry. It holds its iterator open
for a long time, so the window is wide rather than theoretical.

**Membership test, then index.**

```python
if strategy_id in STRATEGY_CONFIGS:            # passes
    STRATEGY_CONFIGS[strategy_id][...] = ...   # deleted meanwhile -> KeyError
```

The widest instance had the guard in `validate_strategy_access()` and the
indexing back in the *calling* route, with an ownership check in between.

## What changed

Three accessors, and a rule: **do not touch the dicts directly.**

| Accessor | Replaces | Behaviour |
| --- | --- | --- |
| `get_strategy_config(id)` | `if id in D: D[id]` | returns `None`, never raises |
| `get_running_strategy(id)` | same, for the process table | returns `None`, never raises |
| `snapshot_strategy_configs()` | `D.items()` | a point-in-time copy, safe to iterate slowly |

They hold `PROCESS_LOCK` **only for the dict operation itself**, never across a
file write or a process poll. Holding it across `save_configs()` would make a
slow listing block a strategy from starting — trading one bug for a worse one.

`load_configs()` now builds the new map off to the side and publishes it with a
single rebind, the same publish-by-swap shape used for the symbol cache, so a
concurrent reader never sees a half-backfilled config map.

Where a config is mutated after being fetched, a concurrent delete now makes the
write a harmless no-op on an orphaned dict rather than a `KeyError`.

## What was deliberately left alone

The SSE endpoint was already correct and needed nothing: `SSE_LOCK` guards the
subscriber list, cleanup runs in a `finally`, the queue is `queue.Queue`, and
PR-10h already wrapped it in `track_stream`. It costs **one worker thread per
open /python tab** for the life of the connection — that is the documented
budget cost, not a defect.

Sites where the guard and the index are both inside the same held
`PROCESS_LOCK` were left untouched. They are correct, and the structural checks
below are lock-aware specifically so they do not push churn into the most
delicate code in the file — the start, stop and delete paths.

## How we know it works

`test/test_gthread_python_strategy.py` — **7 checks**, all passing.

Five are behavioural: four reader threads looking up while another thread
creates and deletes the same strategy in a loop, and three listing threads
iterating while the registry churns. Both reproduced the real exception before
the fix.

Two are structural and lock-aware, so a future edit that reintroduces either
shape fails the build rather than waiting for a user to hit it.

## What remains open

`GT-A14-02`. The gate still has the blind spots that hid this file:

- guards only from attributes, not bare names
- mutations only from attributes, and only self-referential ones
- subscript assignment (`D[k] = v`) not treated as a mutation at all
- **check-then-read is never detected**, though that is what raises `KeyError`

A codebase-wide sweep for the specific pattern found **5 unguarded sites left**,
in `services/indicator_service.py` (2), `blueprints/chart_test.py`,
`blueprints/scalping.py` and `database/market_calendar_db.py`. Small, but the
gate should be the thing that finds them, not a one-off script. Both are
recorded rather than quietly fixed.
