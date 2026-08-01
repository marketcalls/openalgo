# PR-3 — Stop live updates from getting jumbled

**Status:** Done · **Tracker items:** GT-A1-01, GT-A1-02, GT-A1-03, GT-A1-04 · **Runs on:** the current eventlet setup

## What was broken

The dashboard updates live — order fills, position changes, analyzer results.
Those pushes come from all over the app: background job runners, the scheduler,
order-update threads, the Telegram and WhatsApp bots, and ordinary web
requests. About **123 places in 46 files** send them.

The library we use to push them says plainly, in its own source code:

> this method is not thread safe. If multiple threads are emitting at the same
> time to the same client, then messages composed of multiple packets may end
> up being sent in an incorrect sequence. Use standard concurrency solutions
> (such as a Lock object) to prevent this situation.

Meanwhile our own code carried a comment claiming the opposite — that pushing
updates *was* thread-safe. That comment was simply wrong.

Today it does not bite, because the old eventlet worker only ever ran one piece
of code at a time, so two pushes could not genuinely overlap. **The new worker
runs things in parallel for real.** Two updates sent at the same moment could
arrive at the browser interleaved and scrambled.

## What we changed

Rather than edit 123 call sites — easy to get wrong, and easy for a new one to
slip through later — we put the fix in **one place**: the shared object that
every one of those call sites already uses.

It now takes a lock before sending and releases it after. Every existing push
is covered without touching any of them, and any push added in future is
covered automatically. The lock is reentrant, so code that pushes an update
while already sending one on the same thread will not freeze.

We also **removed 7 places** that span a brand-new background thread purely to
send one message. That was a workaround for the old worker. With sending now
serialized, it bought nothing and just created thread churn.

And we corrected the misleading comment, so the next person reading it is told
the truth: the library is not thread-safe, and safety comes from our lock.

## An open question we are now measuring, not guessing

The library's warning is specifically about messages **split across multiple
packets** — and messages get split when they carry *binary* data, not when they
are simply long. Most of our updates are small JSON, which is a single packet
and was never at risk.

So the lock might be broader than strictly necessary. Rather than guess, the
boundary now counts how many pushes happen and how many carry binary data.
Once there is real production data, that number tells us whether the lock can
safely be narrowed. Until then it stays as-is, which is the safe default.

## How we know it works

`test/test_gthread_emit_boundary.py` — **12 checks, all passing.**

The important pair:

- **With the lock:** 12 threads each sending 8 updates at once → **zero
  overlaps**, all 96 delivered.
- **Without the lock** (the old behaviour, kept in the test as a control):
  overlaps **do** happen.

That second test matters. Without it, the first one could pass for the wrong
reason and prove nothing. We assert the problem is real before asserting the
fix works.

The rest check that the lock does not deadlock when reentered, that the live
app object really is the locked one, that binary data is detected correctly at
any nesting depth, that the counters tally, that **no** background-thread emit
workaround remains anywhere, and that the misleading comment is gone.

## Note

Two of these tests failed on the first run. Both were faults in the tests, not
the code: one assumed a setting is readable before the app is fully started,
the other accidentally reached for a real network connection. Fixed both and
re-ran. Worth recording, because "the test failed" and "the code is wrong" are
not the same thing, and treating them as the same is how a correct change gets
reverted.
