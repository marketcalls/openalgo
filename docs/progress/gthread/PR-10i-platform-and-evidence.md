# PR-10i — Windows database checks, and making the emit question answerable

**Status:** Done · **Tracker items:** GT-A4-08, GT-A1-04 · **Runs on:** the current eventlet setup

Both of these were previously blocked. Both became possible because earlier
steps built the thing they needed.

## 1. The database retry budget had only ever been tested on one machine

Our notes record that database locking behaves more strictly on Windows. The
retry rule added earlier — **three attempts within two seconds** — had only ever
been exercised on a single developer's Mac.

That number matters. If a platform needs longer than two seconds to clear
contention, the limit is simply wrong there: the attempt is abandoned *and* a
worker thread was held for the whole time. The worst of both.

There was no way to check, because nothing ran on Windows.

**There is now** — an earlier step added a start-up job covering Linux, macOS
and Windows. This hangs a database suite off it, checking on each platform:

- that WAL mode is genuinely available and did not silently fall back (if it
  did, readers would block writers and the whole contention model would be
  wrong there);
- that the fifteen-second wait is actually applied to every connection;
- that a stale-snapshot rejection can really be reproduced — if a platform
  quietly blocks instead, the retry never even runs;
- that a conflicting write recovers **inside** the budget;
- that eight threads writing at once lose no updates.

It passes locally. **The Windows result arrives with the next pull request** —
that is the whole point, and it would be dishonest to imply otherwise.

## 2. The lock we were not sure we needed is now measurable

An earlier step put a lock around every live update sent to the browser, because
the library documents that concurrent sends can interleave.

But that risk is specific to messages **split across multiple packets**, and
messages split when they carry **binary** data — not when they are merely long.
Almost all our updates are small JSON. So the lock may well be broader than
necessary.

We deliberately did not guess. The counters were already being kept; they simply
were not visible anywhere. They now appear in the admin runtime information
alongside the thread and stream counts.

So the question becomes answerable by looking: **if binary messages stay at zero
in production, the lock can be narrowed on evidence.** Until someone looks, it
stays as-is, which is the safe default.

## How we know it works

`test/test_gthread_sqlite_platform.py` — **5 checks**, and
`test/test_gthread_ci_gates.py` — **20 checks**, all passing.

The gate tests assert the platform suite really is wired into the Windows job,
and that the emit evidence really is reachable from a running server — not just
that the code exists somewhere.

Full suite: **200 checks**, passing twice consecutively.

## What is actually left

35 items. **21 are the switch itself or the deployment files it touches.**

Of the remaining 14, every one needs something this machine does not have:

| Needs | Items |
| --- | --- |
| A real Ubuntu / RHEL / Arch server | 4 |
| A running Docker daemon | 2 |
| A multi-instance host | 2 |
| A 24-hour soak run | 2 |
| A browser session, or a paired WhatsApp account | 2 |
| A rollback rehearsal against a deployed instance | 2 |

There is one documentation item that could still be written up, but no further
code that can be honestly justified without either the switch or real
infrastructure. Continuing to loop past this point would mean inventing work,
which the instructions rule out — and rightly.
