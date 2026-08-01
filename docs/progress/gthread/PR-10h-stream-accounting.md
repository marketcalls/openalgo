# PR-10h — Counting the streams that consume threads

**Status:** Done · **Tracker items:** GT-A6-04, GT-R-05 · **Runs on:** the current eventlet setup

## Why this matters more than it sounds

Under the new worker, **every open live-update stream occupies one worker thread
for as long as the client stays connected.** Two of these exist and both are
infinite: the Python Strategy status stream, and the MCP stream used by AI
assistants.

That makes them the single biggest factor in deciding how many threads the
server needs. And until now, **nobody could count them.** The strategy streams
could only be counted by reading a private internal list; the MCP streams were
not counted at all.

Which means the thread numbers in the plan were estimates with no way to check
them against reality. That is the wrong footing for a decision about production
capacity.

## What we changed

A small shared counter now tracks every long-lived stream for exactly as long as
it holds a thread, reporting both the **current** count and the **peak**.

Peak matters more than current: the budget has to cover the worst moment, not
whatever happens to be open when someone looks.

Both streams are wired in, and the counts appear in the admin runtime
information added in an earlier step. An operator can now compare *streams
currently open* against *threads configured* and see the real headroom instead
of inferring it.

Two details worth stating:

- The counter wraps the **stream itself**, not the web route. The thread is held
  for as long as the stream lives, so counting at the route would report streams
  that had already ended.
- The release happens in a `finally`. A client disconnecting raises out of the
  stream — that is the *normal* ending, not an unusual one. Miss it and the
  count only ever climbs, which is worse than not counting at all.

## We also tested a claim we had only been asserting

The plan says each step can be undone on its own. That had been stated
repeatedly and never actually verified.

So we tried it — reverting each of the last nine steps in turn:

| Result | Count |
| --- | --- |
| Reverts with **no code conflict** | **7 of 9** |
| Conflicts in code | 2 |

The two exceptions are the diagnostics step and the bot-start step, and the
reason is ordinary: a later step edited the same Telegram files. That is not a
hidden dependency, but the blanket phrasing "each step is independently
revertible" was too strong, and the tracker now records what is actually true.

Every other conflict was in the two shared bookkeeping files — the tracker and
this progress folder — which every step appends to by construction.

## A mistake, and what it cost

Running that revert experiment with **uncommitted work in the tree** destroyed
it. The experiment repeatedly resets the working tree; stashing first was not
enough, and three files of finished work had to be written again.

Nothing was lost permanently and the tests confirm the re-applied version is
correct — but the sequencing was avoidable. **Commit first, then experiment with
history.** Recorded here because the failure looked like a successful stash right
up until the moment the files turned out to be empty.

## How we know it works

`test/test_gthread_stream_accounting.py` — **9 checks, all passing.**

Twelve concurrent streams are counted as exactly twelve, then zero once closed.
A client disconnect is simulated directly and asserted not to leak a count. An
exception inside a stream still releases. Peak survives after streams close. And
the diagnostics are asserted to keep working even if the counter itself fails,
since a diagnostics endpoint that breaks during an incident is worse than one
that reports a little less.

Full suite: **193 checks**, passing twice consecutively.
