# PR-14 — The production greenlet crashes, and whether gthread ends them

**Status:** Validated · **Tracker item:** GT-A15-09 · **Issues:** #1569, #1441, #1467, #1473, #1402, #1474

Six open production issues were checked against the branch. **Five are the same
bug** wearing different clothes, and the sixth is a close cousin.

## They are one root cause

Every one of these traces to the same three lines:

```
File ".../eventlet/hubs/hub.py", line 471, in fire_timers
File ".../eventlet/semaphore.py", line 147, in _do_acquire
    waiter.switch()
greenlet.error: Cannot switch to a different thread
```

Under `--worker-class eventlet`, `threading.Thread` is monkey-patched into green
threads, so most application "threads" are safe. But some threads are **real OS
threads** and always were:

* broker SDK WebSocket clients running their own asyncio loop
* the ZeroMQ cache-invalidation subscriber
* APScheduler's executor
* psutil's process-wait machinery

When one of those real threads touches an **eventlet** primitive — a semaphore,
the Socket.IO emit queue, a patched logging lock — eventlet tries to resume a
greenlet belonging to a different OS thread, and the worker is corrupted. The
master survives, the worker does not, and every later request fails until a
manual restart.

| Issue | Trigger | Symptom |
| --- | --- | --- |
| **#1402** | Cache-invalidation subscriber after a plain `/auth/login` | Login spins forever; invalidation pipeline dead until restart |
| **#1441** | APScheduler session-expiry job at 3:30 AM | Login broken every morning; needs `systemctl restart` |
| **#1569** | ZMQ subscriber thread touching eventlet semaphores | Crash hours after startup, preceded by `'StreamHandler' object has no attribute 'lock'` |
| **#1473** | Webhook order flow | Worker stale and unresponsive under two strategies |
| **#1474** | Tick callback emitting Socket.IO from the broker's asyncio thread | Same crash, reached through `socketio.emit` |
| **#1467** | Stopping a strategy | `module 'select' has no attribute 'poll'` — zombie process, `is_running` stuck true |

## Why gthread ends this class of bug

**There is no eventlet.** No hub, no greenlets, no monkey-patching, so there is
no "wrong OS thread" to switch to. Every thread is a real OS thread and every
lock is a real lock — the mismatch that produces `greenlet.error` cannot exist.

Verified on the branch: **no application code calls `eventlet.monkey_patch()`.**
Eventlet is only ever activated by Gunicorn's own worker class. Selecting
gthread means nothing patches the standard library at all.

That is what makes this structural rather than a fix. Five of these six issues
are not *repaired* by the migration; the conditions that produce them stop
existing.

#### #1467 specifically

Eventlet's `monkey_patch(select=True)` **removes `select.poll`**, which psutil's
pidfd wait path needs on Linux. The exception escaped the handler, so the
strategy was killed but never reaped, `is_running` stayed `true`, and the reaper
retried forever.

The branch already carries a workaround (`terminate_psutil_process_safely`,
which avoids `psutil.Process.wait(timeout=...)`). Under gthread `select.poll`
is simply present, so the underlying cause is gone and the workaround becomes
belt-and-braces.

## What would have replaced them, and is already handled

Removing eventlet removes the *green thread* hazard, but real threads bring
their own. The one that maps directly onto #1474 is that **`socketio.emit()` is
documented as not thread-safe** — concurrent emits can interleave multi-packet
messages.

That was addressed in **PR-3**. There is exactly **one** Socket.IO object in the
application (`extensions.socketio`, a `SerializedSocketIO`), every server
emit takes a process-wide lock, and all **130 emit call sites across 60 modules**
route through that single object. No module constructs its own.

So #1474's crash chain — tick callback on the broker's own thread calling
`socketio.emit` — is serialized rather than merely un-crashing.

The broader class (real threads racing on shared state) is what the rest of this
migration has been about: 71 completed items covering caches, registries, the
sandbox, MCP, Telegram and the strategy host.

## What this does not claim

* **Not verified in production.** This is code and architecture analysis. None
  of these six has been reproduced on the branch under a real broker and then
  shown fixed, because reproducing them needs a live session and, for #1441,
  a 3:30 AM rollover.
* **The migration is not finished** — see the tracker. In particular
  `GT-A15-07` (APScheduler jobs lack per-job database session cleanup) is open
  and touches the same scheduler as #1441. It is a resource-leak risk, not the
  crash, but it should be closed before claiming that issue.
* **Eventlet must remain installed for now.** Several broker modules still
  `import eventlet` to *detect* patching. Those imports must be made optional
  in PR-11b, when eventlet is removed from the dependency set.

## Recommended verification before closing any of them

1. Run the branch with `OPENALGO_WORKER_CLASS = 'gthread'` against a live broker
   through a full trading day, including the ~3:00 AM token rollover (#1441).
2. Exercise webhook order flow with two or more strategies (#1473).
3. Start a strategy, restart OpenAlgo, then stop that strategy from the UI —
   this is the exact #1467 reproduction, since it only triggers for a strategy
   re-adopted as a `psutil.Process`.
4. Confirm `log/errors.jsonl` contains no `greenlet.error` for the whole run.

Step 4 is the real acceptance test: on eventlet these appear within hours, and
under gthread the string should be structurally impossible.
