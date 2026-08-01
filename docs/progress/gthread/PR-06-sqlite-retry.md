# PR-6 — Retry database writes that lose a race

**Status:** Done · **Tracker items:** GT-A4-01 … GT-A4-08, GT-A11-01, GT-A11-02 · **Runs on:** the current eventlet setup

## Background: two different "database is locked"

SQLite reports two quite different problems with the **exact same message**:
`database is locked`.

**One is ordinary contention.** Another writer holds the lock; wait and you will
get it. We already handle this — every connection is configured to wait up to
15 seconds, and that works.

**The other is a stale snapshot.** A transaction read some data, someone else
changed it, and now this transaction wants to write. SQLite rejects it
*immediately* and does not wait at all — because waiting cannot help. The data
it read is already out of date. The only fix is to start the transaction over
and read again.

Since the messages are identical, code that reacts to the text alone will treat
them the same. That is the trap.

## Why getting this backwards is worse than doing nothing

If you retry the *first* kind, you wait 15 seconds, retry, wait 15 more, retry,
wait 15 more — **45 seconds with a worker thread held the whole time**. Under
the new worker there is a limited pool of those threads. A brief burst of
contention would turn into the whole application becoming unresponsive. That is
an outage wearing the costume of resilience.

So the rule is deliberately asymmetric:

- **Stale snapshot** → retry immediately, with a fresh read.
- **Ordinary contention** → never retry. The 15-second wait already happened.

## What we changed

Added a small retry helper that tells the two apart **precisely** — not by
reading the message, but by the numeric error code SQLite provides (517 for a
stale snapshot, 5 for ordinary contention). Only 517 is retried.

Two rules are built into how it must be used, and both are documented at the
top of the file:

**It re-reads, it does not replay.** The whole read-decide-write sequence is
retried, not just the save. Replaying a value calculated from the stale read
would write a wrong number — corrupting the very data the retry is protecting.

**It must never wrap a broker call.** A retry re-runs everything inside it. If
that included placing an order, the order would be placed twice. The boundary is
local database work only.

It is also bounded: a fixed number of attempts, a hard ceiling on total time,
and a small random pause between tries so that two threads retrying together do
not simply collide again.

## The historical-data store needed no change

The Historify store uses a different database engine and does not go through the
usual connection machinery, so it was flagged for review.

On inspection it was already correct: **every use opens its own connection and
always closes it**, and nothing is shared between threads.

Rather than take that on faith, we measured it — 16 threads writing
simultaneously, 160 writes: **zero failures**. Marked as resolved with that
evidence rather than changing working code.

## How we know it works

`test/test_gthread_sqlite_retry.py` — **10 checks, all passing.**

The tests do not fake the error. They **cause a real one**: open two
connections, have the first read, have the second commit a change, then have
the first try to write. That produces a genuine stale-snapshot rejection, and
the tests confirm it is identified correctly and that its message really is
indistinguishable from ordinary contention.

The end-to-end check is the important one: it forces a conflict mid-transaction
and then verifies the **other writer's change survived**. If the retry had
replayed its stale value instead of re-reading, that change would have been
silently overwritten. The final number proves it re-read.

## A mistake worth recording

The first version of the Historify concurrency test wrote **400 rows into the
real database** instead of a temporary one.

The reason: that module reads its file location once, when it is first loaded.
The test overrode the setting afterwards, which looked correct and did nothing.

Caught it because the test failed on duplicate keys — data it should never have
been able to collide with. Removed the 400 rows immediately; the table was
empty beforehand, so nothing real was lost, and the database directory is not
tracked by Git so nothing was committed.

The test now patches the value the code actually reads, **and asserts it is
pointing at a temporary path before writing anything**. That guard is the real
fix — the failure mode here was a test that silently escaped its sandbox, which
is far more dangerous than a test that fails.
