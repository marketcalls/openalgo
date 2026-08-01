# PR-10d — Telegram start-up, scalping engine, rooms

**Status:** Done · **Tracker items:** GT-T-02, GT-A12-07, GT-S-04, GT-H-03, GT-A12-11 · **Runs on:** the current eventlet setup

Five more "investigate" items. One was a real defect; three were already
correct; one is safe today for a reason worth writing down.

## 1. Starting the Telegram bot twice would break it (fixed)

Starting the bot checks "is it already running?" — but that flag is only set
from **inside** the bot thread, once polling is actually live. That happens up
to five seconds after the start call.

So two start requests landing in that gap both saw "not running" and both
spawned a polling thread. Two threads polling the same bot token makes Telegram
reject them with a conflict error, and **the bot stops responding altogether**.

The realistic trigger is mundane: the app auto-starts the bot at boot, and a
user presses Start on the Telegram page at the same time.

**Fixed** by serializing start, and by also rejecting a thread that has been
created but has not yet reported itself running — because that gap is precisely
the problem.

## 2. The scalping stop-loss engine was already right

This module turned out to be the **best-written concurrency code in the
codebase**. It has a properly double-checked singleton, a lock around its state,
and a sync mechanism that coalesces bursts instead of stacking up threads.

Its exit path — the one that fires your stop-loss — does use a check-then-act to
avoid firing twice. That is safe **only** because every caller holds the state
lock. Nothing needed changing, but there is now a test that verifies the call
stays inside that lock, since moving it out would silently allow a stop-loss to
fire twice.

## 3. The historical-data scheduler was already right

It already sets all three job controls: no overlapping runs, combine missed
runs, and a five-minute grace. No change.

## 4. Chat "rooms": safe today, and here is what would change that

The Socket.IO library has its own version of the check-then-act problem when two
connections join the same **new** room simultaneously — one of the two
memberships can be lost.

That race is real, but **unreachable here**, because every single message
OpenAlgo sends is a broadcast. Room membership is recorded but never used to
target anything.

Rather than leave that as a footnote, there is now a test that **fails the build
if anyone adds the first room-targeted message** — at which point this item has
to be reopened. A conditional safety that nobody re-checks is not a safety at
all.

## How we know it works

`test/test_gthread_service_lifecycles.py` — **8 checks, all passing.**

For the bot: eight simultaneous starts result in exactly **one** thread. For
scalping: the singleton is guarded, the exit dispatch is verified to sit inside
the state lock (checked structurally, by walking outward from the call to find
its enclosing lock), and sync is confirmed to coalesce. For rooms: the tripwire
described above.

Full suite: **148 checks**, passing twice consecutively.

## Running total

Investigations are down from 17 to 8. Every one closed so far has ended in one
of three places — fixed, verified safe with evidence, or accepted with the
reasoning recorded and a test pinning it. None have been closed by assertion.
