# PR-5a — Shared HTTP client, event bus cleanup, and abuse counters

**Status:** Done · **Tracker items:** GT-A10-01/02/03, GT-A8-01, GT-A16-01/02 · **Runs on:** the current eventlet setup

PR-5 is the largest step, so it is being done in slices. This is the first:
shared resources. The memory caches follow in PR-5b.

## 1. Two threads could each build their own HTTP client

Every broker API call goes through one shared HTTP client that holds a pool of
up to 100 reusable connections. It was created the first time anyone asked for
it:

> if there is no client yet, build one

With the old worker, only one thing ran at a time, so the first caller always
won. With real threads, **two callers starting at the same moment can both see
"no client yet" and both build one.** Only one gets stored; the other is
abandoned — along with its 100 connections, which are never closed.

The production server runs for weeks without restarting, so leaked connections
never get cleaned up. Eventually the process runs out of file handles and stops
accepting work.

**Fixed** by taking a lock around creation and re-checking inside it, so
whoever gets there second uses the client the first one built. Shutdown takes
the same lock, so a client cannot be closed while another thread is mid-build.

## 2. A busy connection pool looked like a hang

The client had one timeout of 120 seconds. That number applies to *everything* —
including waiting for a free connection from the pool.

So when all 100 connections were busy, the next caller waited **two minutes**
before giving up, holding a worker thread the whole time. It looked like the app
had frozen rather than a pool that needed more headroom.

**Fixed** by separating the two: large historical downloads still get their
120-second read budget, but waiting for a free connection now gives up after
10 seconds (configurable) with a clear error. We also added a way to read the
pool's current usage, because that pool is shared by web requests *and* the
bots, schedulers and streaming threads — you cannot work out its load from the
web thread count alone. It has to be measured.

## 3. Background workers never released their database sessions

Ten long-lived worker threads handle internal events (order fills, alerts).
Some read and write the database.

Normally a database session is cleaned up when a web request finishes. **These
threads are not web requests**, so that cleanup never ran for them, and a
session left open keeps a database connection and its cached objects alive
indefinitely.

**Fixed** by releasing sessions in a `finally` block, so cleanup happens whether
the work succeeded or raised — and a failure is exactly when a session is most
likely to be left half-finished.

## 4. Abuse counters could lose their count

Two counters decide when to block an abusive IP: repeated 404s, and repeated
invalid API keys.

Each one loads its row, adds one in Python, and saves. **Two requests can each
load the value 5, each work out 6, and each save 6.** One increment vanishes.
Under a burst — exactly when these counters matter — the ban threshold is
reached later than it should be, or not at all.

Nothing errors. The protection just quietly under-counts.

**Fixed** by serializing the whole decision. These paths only run during abuse,
so the cost is irrelevant.

## An important correction to our own records

The earlier plan described this fourth item as a "check-then-act" problem,
based on output from the detector script we wrote in an earlier step.

**That description was wrong, and the tool was at fault.** The detector had a
bug where it could report a guard that appeared *after* the change it was
supposedly guarding — a meaningless pairing. We fixed that bug in a later
revision, and re-running the corrected detector against the original code finds
**nothing** here at all.

The defect is still real, but it is a different shape: a lost update, not a
check-then-act. The plan has been corrected to say so.

This is the second time a tool we built produced a false finding that we then
had to withdraw. Both times it was caught by re-checking rather than by trusting
the output. The stronger long-term fix here would be to let the database do the
addition itself, which cannot lose a count regardless of threads — that is noted
in the plan.

## How we know it works

`test/test_gthread_shared_resources.py` — **8 checks, all passing.**

- Eight threads racing to get the HTTP client from cold → **exactly one** client
  built, and all eight get the same one.
- Pool wait is separate from, and shorter than, the read timeout.
- Pool usage figures are readable.
- Shutdown uses the same lock as creation.
- Event bus releases sessions on **both** the success and the failure path.
- Both abuse counters are serialized.
- A control showing a serialized counter never loses an increment across 8
  threads × 500 increments.
