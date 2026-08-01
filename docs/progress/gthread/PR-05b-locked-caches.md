# PR-5b — Make the shared memory caches safe for multiple threads

**Status:** Done · **Tracker items:** GT-A3-01 … GT-A3-12 · **Runs on:** the current eventlet setup

## What was broken

OpenAlgo keeps 26 in-memory caches across 12 modules — login tokens, broker
selection, API-key checks, order mode, settings, strategies, calendars, and the
Telegram/WhatsApp user tables.

They all use a library cache type that **expires entries after a time limit**.
That library states plainly in its documentation that its cache types are *not*
safe for use by multiple threads at once, and that the caller must protect them.

**None of them were protected.**

This is not a plain dictionary. To know what to expire, the cache keeps an
internal ordered list that gets rewritten on every insert, every eviction, and
every expiry. If two threads rewrite that list at the same time, it can end up
inconsistent — and then a perfectly valid key raises "not found".

The most exposed module is the one holding login tokens, broker choice and
order mode. Those are read **on every single order**.

The old worker only ran one thing at a time, so two cache operations could never
overlap. The new worker runs them in parallel.

## What we changed

Rather than adding locks in 26 separate places, we made **one** thread-safe
cache type and swapped every cache over to it. Behaviour is identical —
expiry, size limits and eviction all work exactly as before — but every
operation now takes a lock.

There was a second, subtler problem. Code frequently did:

> is this key in the cache? … yes … fetch it

That is **two** separate operations. Even with each one individually protected,
the entry can expire in the gap between them, and the fetch then fails on a key
that existed a moment earlier. On the order path that is a login token
vanishing mid-request.

We converted the six such sequences in the token/order module into single
atomic lookups. The remaining two there are membership checks with no follow-up
fetch, which are already safe.

## How we know it works — and the part worth reading

`test/test_gthread_locked_cache.py` — **15 checks, all passing.**

The two that matter run the *same* punishing workload against the unprotected
cache and the protected one:

| | Result |
| --- | --- |
| Unprotected cache | **12 failures**, repeatable across 3 runs |
| Protected cache | **0 failures**, across 3 runs |

The failures are `KeyError` on keys that were just written — exactly the
corruption described above.

**Getting that control to fail took three attempts.** A straightforward
hammering of the cache produced **zero** errors. It only broke once the test
combined three things: entries expiring constantly, the cache being full so
evictions fire too, and Python's thread-switching interval turned right down so
threads actually get interrupted mid-operation.

That is worth writing down. It is the second time in this migration that a real
defect refused to appear under casual testing. Both times the reason was the
same: **the fault needs genuine parallelism plus the right timing**, and the old
worker supplied neither. If we had accepted the first "no errors" result, we
would have marked all 12 modules as fine and shipped the bug.

It also means the reason for this change is the library's own written contract,
not merely a failure we happened to catch. The reproduction confirms the
contract is real; it is not the sole justification.
