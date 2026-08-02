# PR-14 greenlet issues and 24x7 reliability validation

**Date:** 2026-08-02  
**Branch / HEAD:** `gthread` / `d1f42f940`  
**Reviewed commits:** `e9e2d27e7` (PR-14 issue mapping), `d1f42f940`
(`CLAUDE.md` runtime documentation)  
**Mode:** audit only; no runtime code changed.

## Verdict

PR-14 is directionally correct about the narrow eventlet failure class: when
Gunicorn runs the gthread worker, application code does not call
`eventlet.monkey_patch()`, so the eventlet hub/semaphore cross-OS-thread traces
reported in the linked issues cannot arise from these paths.

It does **not** validate all six issues as fixed, and it does not establish
24x7 reliability. PR-14 is documentation and one tracker row; it contains no
runtime fix or live reproduction. The issue set also contains failures that
were already fixed before this migration, multiple sub-issues that PR-14 does
not cover, historical code paths that no longer exist, and custom application
code outside this repository.

The correct current classification is:

- eventlet-specific `greenlet.error`: structurally removed when gthread is
  actually selected;
- `/python` psutil stop failure: already fixed independently of gthread;
- Socket.IO foreign-thread emit: protected against gthread packet
  interleaving, but not live-broker validated;
- 24x7 reliability: not yet demonstrated and currently blocked by open code
  and deployment gates.

## Findings

### F1 — High: “all six are one root cause” is factually incorrect

The PR-14 introduction says five issues are the same bug and one is a cousin,
but the next section says every issue has the eventlet
`fire_timers -> semaphore._do_acquire -> waiter.switch()` stack.

Issue #1467 has a different failure:

```text
psutil.Process.wait()
  -> select.poll()
AttributeError: module 'select' has no attribute 'poll'
```

It does not require a foreign OS thread and does not trace through an eventlet
semaphore. Eventlet removed `select.poll` from the patched module. Gthread does
remove that underlying condition, but the taxonomy and evidence in PR-14 must
be corrected.

### F2 — High: #1467 was already fixed on `main`, not by gthread

The #1467 issue thread records the fix in `b4a80e25`. The current branch keeps
`terminate_psutil_process_safely()`, avoids `psutil.Process.wait(timeout)`, and
has exact regressions for both the re-adopted stop path and dead-process reaper.

Validated locally:

- `test_stop_restored_psutil_process_does_not_call_wait`
- `test_cleanup_dead_processes_clears_restored_zombie`
- all 24 tests in `test/test_python_strategy_edge_cases.py`

This issue is fixed under eventlet as well as gthread. It should be attributed
to the existing fix, with gthread described as removing the need for the
eventlet-specific workaround in the future.

### F3 — High: #1441 is three issues, and PR-14 covers only part of one

Issue #1441 reports:

1. a historical APScheduler session-expiry crash;
2. Telegram Updater polling failures;
3. a loopback health probe failing on native Unix-socket installs.

Current source no longer has an APScheduler session-expiry job. Session expiry
runs from `app.py::check_session_expiry()` as a `before_request` hook. PR-14's
statement that open `GT-A15-07` touches “the same scheduler as #1441” is
therefore unsupported: `GT-A15-07` concerns the `/python` strategy scheduler,
not a current session-expiry scheduler.

Gthread removes the eventlet/asyncio conflict from the Telegram path, and the
bot deliberately owns a real thread and event loop. Current tests mock Telegram
polling; they do not establish a stable live Telegram connection.

The loopback probe is unrelated to eventlet. Current
`blueprints/admin.py::_check_loopback_http()` tries direct TCP and then
`HOST_SERVER` through nginx for Unix-socket installs, but the issue-specific
native deployment path was not run in this audit.

The whole GitHub issue cannot be closed from PR-14's evidence.

### F4 — High: #1402 is already reported resolved by the proxy topology change

The #1402 issue thread reports that PR #1438 resolved the problem. Current
Gunicorn topology keeps `websocket_proxy` in a subprocess under both eventlet
and gthread, while Docker runs it externally.

Gthread supplies an additional structural guarantee in the Flask process, but
PR-14 should not present #1402 as an open failure newly repaired by this
migration. A login/cache-invalidation regression test is still useful because
#1569 was explicitly reported after #1438 and demonstrates that the broader
eventlet contamination class remained elsewhere.

### F5 — High: #1473 cannot be certified from this repository alone

Issue #1473 explicitly says some listed files are custom code. Gthread removes
the eventlet cross-thread greenlet failure from OpenAlgo's runtime, but it
cannot guarantee that custom webhook strategies are free of:

- blocking calls that consume all worker threads;
- lock-order deadlocks;
- unbounded queues or executor submissions;
- SQLite write contention;
- subprocess or descriptor leaks.

The webhook-order symptom needs a live workload soak. Absence of
`greenlet.error` proves only that one failure class disappeared.

### F6 — Medium: #1474 is structurally addressed, but the evidence is narrower
than reported

The branch has exactly one production `SocketIO` construction:
`extensions.socketio`, an instance of `SerializedSocketIO`. Its process-wide
`RLock` prevents concurrent server emits from interleaving multi-packet
messages under gthread.

Validated:

- the serialized-boundary tests pass;
- no second production `SocketIO(...)` construction was found;
- no direct `socketio.server.emit` bypass was found.

The published count is stale: the current tree has 129 syntactic
`socketio`/`_socketio` emit sites across 49 application files, not 130 across
60. More importantly, the tests prove serialization with a recording stub;
they do not drive the complete live broker-thread -> market-data callback ->
Flask-SocketIO transport chain.

This is sufficient code-level evidence for the design, not production closure
of #1474.

### F7 — High: current open migration work blocks a 24x7 claim

The progress page itself reports 40 remaining items and only 71/111 actionable
rows complete (64%). The most relevant open code items include:

- `GT-A15-06`: `/python` start/stop/schedule/edit/delete are not atomic
  lifecycle operations;
- `GT-A15-07`: `/python` APScheduler jobs lack per-job scoped-session cleanup;
- `GT-A15-05`: the concurrency detector has known blind spots and five
  unguarded sites remain;
- SQLite retry wiring and cache compound-operation rows reopened by prior
  review;
- container/proxy health and live-load acceptance gates.

PR-13 is also still not safe despite being marked done. On the current HEAD,
both deterministic pool lifecycle checks fail:

```text
stale_disconnect_preserves_replacement=False
invalidation_disconnects_selected_old=False
invalidation_preserves_replacement=False
```

A stale wrapper can remove a replacement pool, and user invalidation can
disconnect the replacement rather than the pool it selected. For a 24x7
system this can strand or hide a live broker feed after credential rotation.

### F8 — Low: the automated suites pass but process shutdown is not clean

All assertions passed, but both relevant pytest runs emitted three logging
errors during interpreter shutdown:

```text
ValueError: I/O operation on closed file
blueprints/python_strategy.py::cleanup_on_exit
```

This is caused by the atexit cleanup logging after pytest/colorama has closed
its captured stream. It is not evidence of a live-server failure, but “all
suites green” should distinguish assertion success from clean process output.

## Issue-by-issue disposition

| Issue | Current disposition | Required before closing |
| --- | --- | --- |
| #1569 | Eventlet greenlet stack structurally absent under gthread; not reproduced live | Multi-hour live ZMQ/Socket.IO run plus clean error log and stable logging |
| #1441 | Historical scheduler path changed; Telegram and Unix-socket probe not live validated | Forced expiry-boundary test, live Telegram polling, native Unix-socket probe |
| #1467 | Already fixed independently in `b4a80e25`; exact tests pass | Release/user confirmation if project policy requires it |
| #1473 | Greenlet class removed, broader resource symptom unproven; custom code included | Two-strategy webhook soak with resource and latency metrics |
| #1402 | Issue thread reports resolved by #1438; gthread adds isolation | Login/token-refresh/cache-invalidation test under deployed gthread |
| #1474 | Single serialized Socket.IO boundary is code-level sound | Live broker callback and concurrent emit soak |

## Verification performed

```text
uv run pytest -q test/test_gthread_*.py
269 passed

four test/test_gthread_*.sh suites
90 passed

issue-adjacent /python, session, emit, Telegram and proxy suites
103 passed

test/test_python_strategy_edge_cases.py
24 passed (included in the 103 issue-adjacent run)
```

Environment limits:

- macOS, Python 3.12;
- no Docker daemon validation;
- no Linux pidfd runtime in this audit (covered by mocked exact regression);
- no live broker, Telegram bot, nginx Unix socket, or multi-day soak.

## 24x7 acceptance gate

Do not close the six issues or make gthread the default solely because
`greenlet.error` is structurally unavailable. Require a deployed soak that
covers at least these conditions:

1. **Duration:** seven consecutive days, spanning daily token/session rollover,
   a market close/open, and a weekend boundary. A one-trading-day run does not
   establish 24x7 reliability.
2. **`/python`:** start several strategies, restart OpenAlgo while they remain
   alive, re-adopt them, stop them, exercise scheduled start/stop, and run
   concurrent lifecycle requests for one strategy.
3. **Realtime:** live broker market data, dashboard Socket.IO clients, multiple
   `/python` SSE tabs, MCP SSE, reconnects, and credential rotation.
4. **Automation:** two concurrent webhook strategies, Telegram polling and
   alerts, scheduler jobs, sandbox execution, and proxy restart recovery.
5. **Failure injection:** kill/restart the proxy, interrupt a broker connection,
   restart Gunicorn gracefully, and verify no orphan strategy or adapter
   processes remain.
6. **Metrics:** thread count/utilization, request queueing, p95/p99 HTTP and
   order overhead, SQLite lock errors, FD count, RSS, executor queue depth,
   Socket.IO reconnects, proxy feed freshness, and zombie processes.
7. **Pass conditions:** no `greenlet.error`, no unhandled `database is locked`,
   no stale `is_running`, no lost replacement pool, no FD/RSS upward slope,
   no orphan/zombie process, and all health probes remain meaningful.

Only after the open correctness rows are closed and this soak passes should
the project claim that gthread is ready for reliable 24x7 operation.

