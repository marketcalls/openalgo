# PR-8 — Fix sandbox shutdown and scheduler timing

**Status:** Done · **Tracker items:** GT-A9-01, GT-A9-12, GT-A13-01, GT-A13-04, GT-A13-06 · **Runs on:** the current eventlet setup

This is the last correctness step before the switch itself.

## 1. Shutting down the sandbox engine was guaranteed to stall

The sandbox engine has a background "watcher" that periodically checks whether
it can upgrade from polling to a live feed.

Shutting the engine down did this:

1. Take the engine lock.
2. Ask the watcher to stop, and wait up to 5 seconds for it to finish.

But the watcher needs **that same lock** to do its work. So it was sitting there
waiting for the lock that the shutdown was holding, while the shutdown sat
waiting for the watcher to finish. Neither could move.

After 5 seconds the wait gave up — and then the code **cleared its reference to
the watcher anyway**, recording it as stopped. The watcher was still alive. Once
the shutdown released the lock, that supposedly-stopped thread woke up and
carried on changing engine state.

So every sandbox shutdown paid a guaranteed 5-second stall *and* left a thread
running that everything else believed was gone.

**Fixed** three ways: stop the watcher **before** taking the lock, so the wait
can actually succeed; if the wait does time out, **do not** pretend it stopped —
log an error and keep the reference so it is not treated as gone; and have the
watcher re-check the stop signal after it gets the lock, so it exits instead of
doing one more round of work on the way out.

## 2. Overnight settlement could run twice and lose money

Once a day, positions held overnight are moved into holdings. For each one it
reads the current holding, works out a new quantity and a new average price, and
transfers the margin.

Nothing stopped two settlement runs happening at once — the scheduled run and a
catch-up triggered by a login, for example. Both would read the **same** starting
quantity, both would calculate from it, and both would write. One settlement is
silently lost, and **the margin transfer happens twice**.

**Fixed** by serializing settlement across the whole process. The lock is shared
by all instances deliberately: callers create a fresh manager object each time,
so a per-object lock would protect nothing at all.

## 3. Three schedulers could silently skip jobs

The scheduling library gives every job a **1-second grace period** by default. If
a job's moment passes and the scheduler is busy for more than a second, the job
is **skipped entirely** — not run late.

One second is nothing on a busy worker. Three schedulers were relying on that
default:

- hosted Python strategies
- ChartInk scan triggers
- **sandbox auto square-off**

The third is the one that matters: square-off is aligned to exchange close.
Silently skipping it means positions that should have been closed stay open.

**Fixed** by setting an explicit 5-minute grace on all three, matching what the
other schedulers already used.

An earlier version of the plan claimed these schedulers also lacked protection
against a job running twice concurrently. **That was wrong** — the library
already prevents that by default, and there is now a test asserting it, so if
the library ever changes that default we find out immediately.

## How we know it works

`test/test_gthread_sandbox_lifecycle.py` — **12 checks, all passing.**

The lock-and-wait problem is demonstrated, not just asserted about. Two small
models run side by side:

| Shape | Result |
| --- | --- |
| Wait while holding the lock (the old code) | times out, thread still alive |
| Signal, release, then wait (the new code) | exits in well under a second |

The settlement test runs 8 threads into settlement at once and asserts **zero
overlap**. There is also an inventory check that all six schedulers in the
codebase are accounted for, so a seventh added later cannot quietly skip review.

## Note: a test that could not see the code it was testing

The sandbox tests initially failed with "no such module" — while the exact same
import worked fine from the command line.

The cause: there is a `test/sandbox/` folder, and the test runner puts the test
directory on the import path. So inside tests, `sandbox` means the *test* folder,
not the real one. The real modules were invisible.

The tests now load those files by their explicit path. Worth recording because
the symptom looked like a broken import in new code, when it was actually a
name collision that has been sitting in the repo all along — no previous test
had tried to import a real sandbox module.
