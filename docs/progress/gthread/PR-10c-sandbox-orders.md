# PR-10c — Order cancellation and the catch-up sweep

**Status:** Done · **Tracker items:** GT-A9-08, GT-A9-09 · **Runs on:** the current eventlet setup

Two more items carried as **"investigate"**. Both turned out to be real.

## 1. Cancelling an order twice refunded the margin twice

When you place an order, some of your balance is set aside as margin. When you
cancel it, that margin is given back.

Cancelling checked the order was still open, then marked it cancelled, then
released the margin — with **nothing preventing two cancels running at once**.

Two cancels of the same order arriving together would both see it as open, both
mark it cancelled, and **both release the margin**. Your available balance would
go up by twice what was actually set aside.

The fund code does protect its own balance updates — but that does not help
here. Each release is individually valid. There are simply two of them.

**Fixed** by making the whole sequence — check, mark, release — a single
protected step, for both cancelling and modifying an order. The lock is shared
across the whole process on purpose: a new manager object is created for each
request, so anything narrower would protect nothing.

## 2. Two logins could run the recovery sweep at the same time

After signing in, OpenAlgo runs a catch-up sweep for anything missed while it
was shut down: squaring off stale overnight positions, settling holdings,
resetting the daily profit figures.

That sweep is reachable from **two different login paths**, each on its own
background thread — and OpenAlgo permits up to five signed-in devices. Two
logins landing together started two sweeps at once. Stale positions could be
squared off twice; the daily profit reset could fire twice.

**Fixed** so a second trigger **skips** rather than waits. Waiting would be
worse than useless — it would simply run the entire sweep again the moment the
first one finished, which is exactly what the guard exists to prevent.

## How we know it works

`test/test_gthread_sandbox_orders.py` — **8 checks, all passing.**

The cancellation pair is matched: the unguarded shape is shown to release more
than once, and the guarded shape releases **exactly once** across 8 competing
threads. There is also a check that the order of operations — verify, then
mark, then refund — has not been rearranged, since the protection depends on
all three staying together.

For the sweep: six simultaneous triggers result in **one** run, and a sweep that
fails still releases the guard, so one bad run cannot wedge every later one.

## Note: a flaky test is worse than no test

The MCP quota control written in an earlier step failed during this run. It had
been documented as "intermittent" — it relied on the operating system happening
to interleave threads, and under a full-suite load it sometimes did not.

That is not an acceptable test. A control that fails at random teaches people to
re-run the suite rather than read it, and the next real failure gets dismissed as
"just the flaky one".

Rewritten to hold the window open deliberately rather than hoping for a
scheduling accident. The full suite now passes three times in a row: **140
checks**.

## Where this leaves the sandbox

The sandbox was described early on as relying on database transactions rather
than locks. That is accurate, and mostly fine — but three of its money paths
needed real protection: settlement, order cancellation, and the catch-up sweep.
All three are now serialized, and each was verified by reproducing the failure
first.
