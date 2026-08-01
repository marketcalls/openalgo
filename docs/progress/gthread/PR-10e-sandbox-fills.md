# PR-10e — Fills, square-off, and the last open questions

**Status:** Done · **Tracker items:** GT-A9-02, GT-A9-03, GT-A9-04, GT-A9-07, GT-A9-10, GT-F-04 · **Runs on:** the current eventlet setup

The last six "investigate" items. Two were real; four closed with evidence.

## 1. An order could be filled twice (fixed)

Filling a simulated order checks "does this order already have a trade?" and, if
not, creates one.

Those are two separate steps, and — importantly — **the database does not
enforce uniqueness here**. The trade table indexes the order ID but does not
require it to be unique. So nothing stops two trades being created for one
order, which would double the resulting position.

Two engines can be running: a polling one and a live-feed one. They are meant to
be mutually exclusive, but the handover between them leaves a window.

**Fixed** by making the check and the creation a single protected step.

Worth being straight about the scope: **this is not a problem gthread creates.**
Both engines already ran on real threads. The switch makes the window easier to
hit, and this is a reasonable moment to close it.

The genuinely stronger fix is to make the order ID unique in the database, which
would hold even across separate processes. That needs a migration and a check
for any duplicates already present, so it is deliberately **not** bundled here —
it is recorded in the code so it does not get forgotten.

## 2. Square-off could run twice at the same minute (fixed)

Positions that must close at day's end are handled by a scheduled job. There is
also a **backup job running every minute**, as a safety net in case the primary
one was missed.

The scheduler prevents a job overlapping *itself* — but these are two different
jobs. At the square-off minute, both fire, and each would fetch the same open
positions and close them. Positions closed twice.

**Fixed** by serializing the sweep. There is also a test asserting that **two**
such jobs still exist — if the backup is ever removed, the reasoning behind this
lock should be revisited rather than left as unexplained machinery.

## 3. Four closed with evidence

- **Holdings** — the money path (settlement) was already protected in an earlier
  step. Everything else recalculates display values: repeatable, last-write-wins,
  no money movement. There is a test asserting no money operation ever appears
  in that display path.
- **Engine fallback and teardown** — covered by the handover fix from PR-8.
- **Flow database writers** — the detector reports **zero** check-then-act
  patterns across the whole database layer. Closed on the tool's evidence rather
  than by reading it and forming an impression.

## Milestone: every item is now classified

| | |
| --- | --- |
| Items still carrying an open question | **0** (was 17) |
| Items with a real decision recorded | **152 of 152 — 100%** |

This is worth stating carefully, because it is easy to over-read.

**It means:** every surface found has a decision — fixed, verified safe with
evidence, or accepted with reasoning and a test pinning it. None were closed by
assertion.

**It does not mean the migration is finished.** 51 items are still open work:
the switch itself, the deployment files it touches, the platform tests that need
real infrastructure, and the soak measurements that can only happen afterwards.
Those are known work with owners, not unanswered questions.

It also does not mean nothing else exists. Every previous claim of completeness
in this project was falsified by the next sweep. What is true is narrower:
**no unanswered question survives the sweeps run so far.**

## How we know it works

`test/test_gthread_sandbox_fills.py` — **10 checks, all passing.**

Six competing square-off sweeps run strictly one at a time; the duplicate-trade
check is verified to still precede the creation, since the protection depends on
them staying together; and the flow-database result is taken from the gate script
directly rather than restated.

Full suite: **158 checks**, passing twice consecutively.
