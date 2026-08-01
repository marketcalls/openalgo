# PR-10g — Telegram start-up, and the last registry questions

**Status:** Done · **Tracker items:** GT-T-01, GT-A12-01, GT-A12-05, GT-A12-06, GT-A12-10, GT-A16-03 · **Runs on:** the current eventlet setup

## The defect: a start-up that reported failure and kept going

Pressing **Start** on the Telegram page ran the set-up on a background thread
and waited ten seconds for it.

If it took longer, the page returned "Initialization failed" — but **the thread
carried on**. It went on to store the bot token and write the database config,
minutes after the user had been told it failed. And because nothing recorded
that a set-up was in progress, pressing Start again immediately launched a
**second** one against the same token.

Four separate problems in one small block:

- the result was read while the thread could still be writing it;
- a timed-out set-up kept writing state after the failure was reported;
- a retry started a second initializer;
- the thread was not a daemon, so a wedged one could hold up shutdown.

**Fixed** by moving it into the service, where it is now single-flight: one
set-up at a time, on an owned single-worker pool, and a timeout that says what
is actually true —

> Initialization did not complete within 10s. It is still running; retry once
> it settles.

That wording matters. Saying "failed" is what invited the immediate retry that
produced two initializers in the first place.

## Four registry questions closed with evidence

- **Banned IPs** — the ban check is a database query every time. There is no
  in-memory ban list to corrupt or to drift out of step with the database. The
  counters themselves were already serialized in an earlier step.
- **Traffic and latency logs** — both write through a **single-worker** pool, so
  they are serialized by construction and need no lock. There is now a test
  pinning that worker count, because the plan specifically warned against
  "increasing parallelism" here.
- **Plugin loader** — broker capabilities are built into a fresh dictionary and
  published in one assignment. The broker auth map does load modules on first
  use rather than only at start-up, but that is **benign**: the import itself is
  serialized by Python, the guard re-checks before assigning, and the value
  assigned is identical either way. Two racing loaders converge on the same
  state, so there is nothing to lose. Verified by running eight threads at it.
- **Pooled broker adapters** — these live in the market-data proxy, which runs
  **out of process** in every production configuration. Only the development-only
  setting would place them inside the web worker.

## Note: I broke one of my own tests, and fixed it the right way

Moving the set-up logic out of the page handler broke a test written two steps
earlier, which checked that the handler contained a specific error fallback.

The behaviour still exists — it moved into the service. The tempting fix is to
delete the test. Instead it now points at the new location **and** additionally
asserts the old inline version has not come back, so the guarantee is stronger
than before rather than quietly weaker.

## How we know it works

`test/test_gthread_telegram_init.py` (7 checks) and
`test/test_gthread_remaining_registries.py` (9 checks) — all passing.

The important one holds a set-up open, confirms a second attempt is **refused**
rather than queued, and then confirms the first one still completes normally.
There is also a check that the timeout message says "still running" rather than
claiming failure, and one that a timed-out attempt does not leave the guard
stuck so that every later attempt fails.

Full suite: **184 checks**, passing twice consecutively.

## What is left

39 items. **21 are the switch itself or its deployment files.** Of the other 18,
almost all need something this machine does not have: a real Ubuntu server, a
RHEL or Arch box, a Docker daemon, a multi-instance host, or a 24-hour soak.

The code work that can be done without the switch is, as far as these sweeps
can tell, done.
