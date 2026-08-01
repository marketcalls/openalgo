# PR-7 — Make the MCP server's counters and logs accurate

**Status:** Done · **Tracker items:** GT-A6-01, GT-A6-02, GT-A6-03 · **Runs on:** the current eventlet setup

MCP is the interface that lets AI assistants place orders and read account data
through OpenAlgo. Only active when `MCP_HTTP_ENABLED=TRUE`.

## 1. The write quota could let extra orders through

Every access token has a limit on how many **write** operations — order
placement — it may perform in a time window.

The check worked like this: look at how many requests this token has already
made, and if it is under the limit, record one more and allow it.

That is three steps, and they were not protected. **Several requests arriving
together can all read the same count before any of them records anything**, so
they all conclude there is room and all get allowed.

The code even carried a comment explaining why this was fine:

> Single eventlet worker, so no shared-state concerns.

That was true. **It is exactly the assumption this migration removes.**

We measured it. With a limit of 5 and 20 simultaneous requests:

| Run | Allowed through |
| --- | --- |
| 1 | 5 |
| 2 | **8** |
| 3 | **7** |

Up to 60% over the limit — on the interface that places live orders. Note run 1
was correct: the fault is intermittent, so a test that runs once would have
declared it fine.

**Fixed** by making the whole decision a single protected step.

## 2. Old tokens were never cleaned up

Each token kept its own record of recent activity. Those records were only
tidied when that *same* token came back. A token used once and never again kept
its entry **for the life of the process** — and the production server runs for
weeks.

**Fixed** with a periodic sweep that drops records whose activity has all
expired, while leaving active tokens alone.

## 3. Audit lines could vanish exactly when they matter

Every MCP action is written to an audit file. When that file grows past ~2 MB it
is trimmed: read the whole file, keep the most recent lines, write it back.

If another request appends **while** that read-and-rewrite is happening, its
line is in the copy that is about to be overwritten. It disappears.

This only happens when several requests arrive at once — which is precisely when
an audit trail is worth having.

**Fixed** by making appending and trimming share a lock, so a trim can never
overwrite a line written mid-operation.

## 4. Start-up could run twice

The server sets itself up once at boot. But if MCP requests arrive before that
finishes, they trigger set-up themselves — and the "have we already started?"
check was not protected, so **two requests could both decide the answer was no**
and both set up, building two API clients.

**Fixed** with the standard double-check: test, take the lock, test again.

## How we know it works

`test/test_gthread_mcp.py` — **11 checks, all passing.**

The quota tests come in a matched pair:

- **Unprotected version:** over-admits (the control above).
- **Protected version:** admits **exactly** the limit, asserted across 5
  separate trials — because a single trial can pass by luck.

The audit test runs 8 threads writing 50 entries each, then checks all 400
lines are present **and that every one is valid, complete JSON**. A torn write
would fail to parse even if the count happened to come out right.

The start-up test runs 8 threads into set-up simultaneously and asserts it ran
exactly once.

## Note

The tests initially tripped a code-quality warning about functions capturing
loop variables. In this case the behaviour was actually correct — each batch of
threads finishes inside its own loop iteration — but the values are now passed
in explicitly. The warning was right that the pattern is easy to get wrong, and
in a test whose whole purpose is catching timing bugs, ambiguity is not worth
defending.
