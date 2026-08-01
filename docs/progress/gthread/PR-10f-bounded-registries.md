# PR-10f — Unbounded caches, a double-locking limiter, and one last money path

**Status:** Done · **Tracker items:** GT-B2-06, GT-A9-06, GT-A12-02, GT-A12-03, GT-A12-13, GT-F-01 · **Runs on:** the current eventlet setup

## 1. Expired contracts could be settled twice (the important one)

When an F&O contract expires, the position is closed automatically: the blocked
margin is released and the profit or loss is credited.

That settlement runs **as a side effect of simply reading your positions** — so
it happens on every positions page load and every positions API call.

It reads the quantity, releases the margin, credits the P&L, then sets the
quantity to zero. With nothing preventing two readers running at once, **two
simultaneous positions requests would both see a non-zero quantity and both
settle** — releasing the margin twice.

Refreshing the page in two browser tabs would do it.

**Fixed** by serializing the settlement — and only the settlement. Ordinary
position reads still run in parallel; making everyone queue for a page load to
fix a rare double-credit would be a bad trade.

## 2. A rate limiter that slept while holding its own lock

The P&L tracker limits how fast it calls the broker. It did this by taking a
lock, then **sleeping while still holding it**.

That makes every caller wait twice: once for the lock, then again for its own
full interval. Five callers took five intervals instead of finishing together
after the last one. Under the new worker, each of those waiters is also
occupying a worker thread the entire time — so a slow limiter turns into
threads unavailable for anything else.

**Fixed** by reserving the slot while holding the lock and sleeping *after*
releasing it. The broker code already does it this way; this was the odd one
out.

## 3. Three registries that grew forever

The production server runs for weeks without restarting, so anything that only
ever grows eventually matters:

- **Option strike cache** — keyed by instrument, expiry and type. Every distinct
  instrument ever queried added an entry, and only one of the 33 brokers ever
  cleared it, so nothing reclaimed the memory. Now size- and time-bounded.
- **Chart symbol cache (HDFC Sky)** — shared by every instance and, notably, the
  only place in the codebase where a class-level value was changed at runtime
  with no protection at all. Now bounded and protected.
- **Workflow locks** — one lock object per workflow, created safely but
  **never removed**. Now removable, with a deliberate refusal to remove one
  that is currently held, since taking a lock away mid-run would strand the
  workflow that needs it.

## How we know it works

`test/test_gthread_bounded_registries.py` — **10 checks, all passing.**

The limiter test is behavioural rather than structural: five callers hit it
simultaneously and the whole thing must finish in well under the time it would
take if they were queuing. The workflow-lock test proves a held lock is
**refused** removal, then released and removed successfully. The caches are
asserted to actually evict.

There is also a check that settlement is serialized while the surrounding read
is *not*, so nobody later "simplifies" it by locking the whole function.

## Note

My first version of the limiter test searched the locked section for the word
"sleep" — and failed, because the variable holding the wait duration is called
`sleep_for`. The check now looks for an actual call. A trivial slip, but it is
the same shape as a real class of bad test: matching on text that resembles the
thing you care about instead of the thing itself.

Full suite: **168 checks**, passing twice consecutively. Tracker: 39 resolved,
68 done, 45 open.
