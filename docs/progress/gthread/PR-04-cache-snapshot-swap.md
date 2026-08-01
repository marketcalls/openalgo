# PR-4 — Stop the symbol lookup going blank during its daily refresh

**Status:** Done · **Tracker items:** GT-A2-01, GT-A2-02, GT-A2-03 · **Runs on:** the current eventlet setup

## What was broken

Two in-memory lookup tables sit directly on the order path:

- **The symbol cache** — around 150,000 instruments. Every order looks up its
  symbol here. It is rebuilt once a day when the broker's contract file is
  downloaded.
- **The freeze-quantity cache** — the maximum size a single order is allowed to
  be before it must be split. Rebuilt when the admin uploads a new list.

Both rebuilt themselves the same way: **empty the table, then fill it back up
row by row.**

While that refill is running, the table is partly — or completely — empty. And
the "cache is loaded" flag stays switched on the whole time. So an order
arriving mid-refresh does not wait, and does not error. It gets a confident,
wrong answer:

- **Symbol cache empty** → the symbol looks like it does not exist.
- **Freeze quantity missing** → falls back to the default of 1, so a large
  order gets split into single-lot pieces.

Neither logs an error. Both look like normal behaviour.

This has been safe until now only because the old worker ran one thing at a
time — the rebuild could never be interrupted. **The new worker runs things in
parallel for real.**

## What we changed

Both caches now use the same approach: **build the new table completely off to
the side, then switch over in one instant.**

Nothing is ever emptied in place. Readers hold either the complete old table or
the complete new one — never a half-built one. Swapping a single reference is a
single, indivisible operation, so there is no in-between state to catch.

Three supporting changes:

- **Writers take a lock**, so two rebuilds cannot interleave and produce a
  mixture of two contract files.
- **Readers do not take that lock.** A rebuild takes seconds; making order
  lookups queue behind it would trade a rare wrong answer for a routine slow
  one. That is a bad trade.
- **A failed rebuild keeps the old table.** Previously a failure left the cache
  empty. Now the previous day's data keeps serving, which is far better than
  nothing.

For the symbol cache this meant grouping its ten lookup tables into one
snapshot object. The ten names are still readable exactly as before — around 56
places in the code use them and none needed changing — but behind the scenes
they all come from one object that gets replaced in a single step. Clearing now
also lowers the "loaded" flag *before* emptying, closing the same window from
the other side.

## How we know it works

`test/test_gthread_cache_snapshot.py` — **10 checks, all passing.**

The main one runs a reader thread continuously while a writer publishes three
different versions of the table, and asserts the reader **only ever saw sizes
that were actually published**. A partial rebuild would show a size nobody ever
published.

We also ran the *old* approach the same way as a control. It leaked
**40 distinct partial states** to the reader, including a table down to a
single entry. That is the bug, reproduced.

## Worth recording: the control failed twice first

My first two attempts to reproduce the old bug found **nothing** — zero partial
states. Not because the bug is not real, but because in a tiny benchmark the
rebuild finishes inside a single scheduling slice, so the reader never gets a
chance to look mid-way.

It only appeared once the test modelled a rebuild that takes a realistic amount
of time, which the real 150,000-row rebuild certainly does.

That is worth writing down, because it is exactly why this class of bug never
showed up in ordinary testing: **it needs a slow rebuild and genuine parallelism
at the same time.** Under the old worker the second ingredient never existed.
Had I stopped after the first attempt, I would have concluded the fix was
unnecessary.
