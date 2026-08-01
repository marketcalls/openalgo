# PR-10j — Writing down how the sandbox handles concurrency

**Status:** Done · **Tracker item:** GT-A9-11 · **Runs on:** the current eventlet setup

## What was missing

The sandbox design document runs to nearly 1900 lines and, until now, said
**nothing at all** about threads.

That was defensible when the sandbox relied purely on database transactions. It
is not defensible now: over the course of this migration we added **eleven
locks** to it, six of them guarding paths that move money. Someone adding code
to the sandbox next month would have had no way to know which sequences must
stay atomic, or why.

Undocumented locks are worse than no locks. They look like clutter, and the
natural instinct is to remove them.

## What was written

A **Concurrency Model** section in the sandbox design document covering:

- **What the model actually is** — database transactions for most state, plus
  explicit locks on the specific check-then-act sequences where running twice
  is not slow but *wrong*.
- **Every lock**, what it protects, and — most usefully — **what two
  overlapping runs would actually do**. "Release blocked margin twice" is a
  reason someone will respect; "guards the cancel path" is not.
- **Two conventions**: locks live on the class, not the instance, because a
  fresh manager is built per request and a per-instance lock would guard
  nothing; and the catch-up sweep deliberately *skips* rather than queues.
- **Four rules for future changes**, each written from a real failure found in
  this migration — never hold a lock across a `join()`; a retry must re-read
  rather than replay; no broker call inside a retry boundary; serialize the
  decision, not the surrounding read.
- **Where the guarantee is not a lock** — the trade table's order ID is not
  unique, so the in-process lock is the *only* thing preventing a duplicate
  trade. That is the one guarantee that would not survive a second process, and
  it is now stated plainly rather than left in a code comment.

## The test is the point

Architecture documents rarely fail by being wrong when written. They fail by
**drifting silently** afterwards, until they describe a system that no longer
exists — and are then more misleading than no document at all.

So the document is tied to the code in both directions:

- every lock the document names **must exist**;
- every lock in the sandbox **must appear in the document**.

That second check immediately earned its place: it failed on first run and
caught **two locks I had left out of my own table** — the square-off scheduler
guard and the WebSocket engine singleton guard. I had written the section by
hand and simply missed them.

It also verifies the stated conventions are true rather than aspirational: that
each documented lock really is defined on the class, and that the
never-join-under-a-lock rule is actually followed in the shutdown path.

## How we know it works

`test/test_gthread_sandbox_docs.py` — **13 checks, all passing.**

Full suite: **213 checks**, passing twice consecutively.

## Status

34 items remain. **21 are the switch itself or its deployment files.** The other
13 all require something unavailable here: a real Ubuntu, RHEL or Arch server; a
running Docker daemon; a multi-instance host; a 24-hour soak; a browser session
or a paired WhatsApp account; or a rollback rehearsal against a deployed
instance.

This was the last item that could be completed without the switch or real
infrastructure.
