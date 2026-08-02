# gthread Migration — Progress

We are replacing the web server's "worker" (the part that handles incoming
requests) from **eventlet** to **gthread**. Eventlet is retired software and
we are stuck on an old Gunicorn version because of it.

Each PR below is a separate step. Every step has its own page written in plain
language: what was broken, what we changed, and how we know it works.

## Steps

| Step | What it does | Status |
| --- | --- | --- |
| [PR-1](PR-01-systemd-unit-migration.md) | Make server upgrades able to change the worker safely | Done |
| [PR-2](PR-02-proxy-supervisor.md) | Stop the market-data process from dying unnoticed | Done |
| [PR-3](PR-03-emit-boundary.md) | Stop live updates from getting jumbled | Done |
| [PR-4](PR-04-cache-snapshot-swap.md) | Stop the symbol lookup going blank during its daily refresh | Done |
| [PR-5a](PR-05a-shared-resources.md) | Shared HTTP client, event bus cleanup, abuse counters | Done |
| [PR-5b](PR-05b-locked-caches.md) | Make shared memory caches safe for multiple threads | Done |
| [PR-6](PR-06-sqlite-retry.md) | Retry database writes that lose a race | Done |
| [PR-7](PR-07-mcp-hardening.md) | Make the MCP server's counters and logs accurate | Done |
| [PR-8](PR-08-sandbox-and-schedulers.md) | Fix sandbox shutdown and scheduler timing | Done |
| [PR-9](PR-09-diagnostics.md) | Report the running configuration correctly | Done |
| [PR-10](PR-10-ci-gates.md) | Add tests that boot the real container | Done |
| [PR-10b](PR-10b-registry-investigations.md) | Close the open registry questions | Done |
| [PR-10c](PR-10c-sandbox-orders.md) | Order cancellation and the catch-up sweep | Done |
| [PR-10d](PR-10d-service-lifecycles.md) | Telegram start-up, scalping engine, rooms | Done |
| [PR-10e](PR-10e-sandbox-fills.md) | Fills, square-off, and the last open questions | Done |
| [PR-10f](PR-10f-bounded-registries.md) | Unbounded caches, a double-locking limiter, one last money path | Done |
| [PR-10g](PR-10g-telegram-init.md) | Telegram start-up, and the last registry questions | Done |
| [PR-10h](PR-10h-stream-accounting.md) | Counting the streams that consume threads | Done |
| [PR-10i](PR-10i-platform-and-evidence.md) | Windows database checks, and making the emit question answerable | Done |
| [PR-10j](PR-10j-sandbox-concurrency-docs.md) | Writing down how the sandbox handles concurrency | Done |
| [PR-10k](PR-10k-self-review.md) | Reviewing my own changes | Done |
| [PR-11a](PR-11a-opt-in.md) | Make gthread available to try, default unchanged | Done |
| [PR-11a.1](PR-11a1-deploy-scripts.md) | Confirm the domain and Windows scripts need no change | Done |
| PR-11b | **The switch itself** — needs sign-off before starting | Awaiting sign-off |

## Numbers

| | |
| --- | --- |
| Total items tracked | 152 |
| Already fine, no work needed | 50 |
| Fixed and tested | 66 |
| Still to do | 36 |
| **Coverage of actionable rows** | **66 / 102 = 65%** |

## Correction, 2026-08-02

An external audit checked these claims against the code and found that **14 rows
marked done did not meet their own acceptance criteria**. It was right. Every
finding was reproduced before being accepted, and those rows are now open again.

This page previously said 79 done and implied the code work was complete. The
honest figure is **66 of 102 actionable rows**. The gap was not a rounding
error, it was rows marked done on the strength of a passing test that tested
the wrong thing.

Two of the findings are worth naming, because both were defects introduced by
this migration and then reported as fixed:

- **The symbol cache could still raise `KeyError` mid-refresh.** Publication was
  made atomic, but every accessor re-read the snapshot through a property, so a
  membership test and the lookup that followed it could land on different
  generations. Fixed, with a structural check that now covers methods that do
  not exist yet.
- **The SQLite retry helper had no callers.** It was written, tested against
  test-local functions, and never wired to a single production writer. Those
  rows are open again.

What let both through was the same thing: **checks that were not gating.** Two
shell suites, 63 checks, were never invoked by CI. The sleep-inventory gate
returned success unconditionally while the workflow claimed drift would fail it.
Both are fixed, and CI now fails if a suite exists without being run.

## Open questions

That is **not** the same as the migration being finished. Of the 23 items still
to do:

- **5 are the switch itself and the files it changes** — repinning Gunicorn,
  dropping eventlet, the multi-instance thread budget, the broker async flip,
  and the half of the documentation sweep that only becomes true once the
  default changes.
- **18 cannot be closed on a developer machine.** Seven need a real Ubuntu, RHEL
  or Arch server, a Docker daemon, or a multi-instance host. Four are rollback
  rehearsals against a deployed instance. Five are measurements that only mean
  something under real load, including the thread budget itself. The last two
  need a browser session and a paired WhatsApp account.

PR-11a shipped the opt-in, so gthread can now be tried without changing the
default for anyone. Several deployment items turned out to need no work at all:
because `.env` is bind-mounted into every Docker container, the setting reaches
the app without touching any compose generator. Those are recorded as resolved
with that evidence rather than marked done.

## How we work

1. One step per page, and each step can be undone on its own.
2. Nothing ships without a test that fails before the fix and passes after.
3. An item is only marked done once its test actually runs.
4. Every page says what would have gone wrong, not just what changed.

Full technical detail lives in
[the plan](../../plans/2026-08-01-eventlet-to-gthread-migration-plan.md) and
[the tracker](../../plans/2026-08-01-gthread-migration-tracker.csv).
