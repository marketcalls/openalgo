# `/python` gthread migration audit

**Date:** 2026-08-02

**Branch:** `gthread`

**Committed baseline:** `68689cec5` (`PR-12c`)
**Reviewed state:** PR-12 (`7021c82e8`) through the committed PR-12c
correction.
At the final verification point, `blueprints/python_strategy.py` had Git blob
ID `04b3b8646bef1826a69e876fd74ce2c88221f380`.

## Verdict

The `/python` feature **does require more work before the gthread cutover is
certified**.

The strategy programs themselves do not consume Gunicorn threads: each program
runs in a separate subprocess. The long-lived Gunicorn cost is the SSE
dashboard connection, one thread per open `/python` tab. The remaining risk is
the control plane: starting, stopping, editing, scheduling, persisting, and
restoring those subprocesses from concurrent request and scheduler threads.

PR-12 fixes some live-dictionary iteration and lookup errors. PR-12a removes
the unsafe `preexec_fn`, fixes the missed status comprehension, and improves
initialization, but introduced three regressions. PR-12b fixes those immediate
regressions but leaves generation ordering and shutdown escape paths. PR-12c
correctly adds generation-ordered publication, shutdown admission control,
Windows tree termination, the original NPROC limit, and a real `Popen`
environment check. Persistence reporting is still incomplete on the user-facing
start/stop paths, and the test suite itself writes production-relative strategy
configuration and logs. Several lifecycle interleavings and scheduler session
cleanup remain open by design.

## Findings

The findings in this section record the original PR-12 baseline and explain why
the follow-up was needed. The current disposition of every item changed by
PR-12a is in the commit recheck below; that recheck is authoritative for
`9bb961e6a`.

### PY-GT-01 — Blocker — `preexec_fn` can deadlock a strategy start

`create_subprocess_args()` installs `set_resource_limits` as `preexec_fn` on
Linux and macOS, and `start_strategy_process()` passes it to `Popen` while the
Gunicorn worker has many native threads.

Python's subprocess documentation is explicit: `preexec_fn` is not safe in a
threaded application because the child can deadlock before `exec`. The risk is
stronger here because `set_resource_limits()` can also invoke logging in the
post-fork child. Python 3.12 additionally warns that mixing `fork()` and threads
has never been a supported POSIX design, with macOS more likely to expose a
deadlock.

References:

- `blueprints/python_strategy.py`, `create_subprocess_args()` and
  `set_resource_limits()` (currently around lines 389-475)
- `blueprints/python_strategy.py`, `subprocess.Popen()` (currently around line
  591)
- [Python subprocess documentation](https://docs.python.org/3/library/subprocess.html)
- [Python `os.fork()` documentation](https://docs.python.org/3/library/os.html#os.fork)

Required change: remove `preexec_fn`. Run the strategy through a small, freshly
executed wrapper that applies POSIX resource limits before `runpy` executes the
user strategy, or use another post-exec isolation mechanism. Preserve
`start_new_session`/process-group termination separately.

Required gate: repeatedly start strategies while all request threads,
schedulers, and SSE streams are active on Linux and macOS; no `Popen` call may
hang and no start may remain in an indeterminate state.

### PY-GT-02 — Blocker — configuration persistence is not serialized

`save_configs()` writes every caller to the same
`strategy_configs.json.tmp`, serializes the live mutable
`STRATEGY_CONFIGS`, and catches failures without returning them to the route.
There are 24 call sites; 18 are outside `PROCESS_LOCK` in the reviewed tree.

Two concurrent calls were forced to reach `os.replace()` together. One failed
with:

```text
Failed to save configs: [Errno 2] No such file or directory:
strategy_configs.json.tmp -> strategy_configs.json
```

The other call had already moved the shared temporary file. The exception was
swallowed, so its caller could still report success. Concurrent mutation while
`json.dump()` walks the live dictionary introduces an additional inconsistent
snapshot/failure path.

References:

- `blueprints/python_strategy.py`, `save_configs()` (currently around lines
  235-251)
- unguarded callers include `scheduled_start_strategy()`,
  `market_hours_enforcer()`, `schedule_strategy()`, `new_strategy()`, the
  start/stop routes, `clear_error_state()`, `save_strategy()`, and restoration
  paths

Required change: serialize the complete state transition and persistence
ordering. A unique temporary filename alone is insufficient because an older
snapshot could finish last. Mutations must be protected, snapshots must be
consistent, disk publication must preserve generation order, and persistence
failures must reach mutating API callers.

Required gate: concurrent upload/start/stop/schedule/edit loops must always
leave valid JSON whose generation matches the in-memory committed generation.
The test must force interleavings with barriers rather than depend on timing.

### PY-GT-03 — High — lifecycle checks and actions are split across locks

The new accessors lock only long enough to return the original mutable `dict`.
The lock has already been released when callers inspect or mutate it. A shallow
registry snapshot likewise contains the original mutable config objects.

Important interleavings include:

- `stop_strategy()` releases the lifecycle lock after terminating, then sets
  `manually_stopped`. A scheduled start can run in that gap, so the Stop request
  can return success while the strategy is running again.
- `save_strategy()` checks `is_running`, then rewrites the script without
  `PROCESS_LOCK`. A concurrent start can execute a truncated/partially written
  script; a concurrent delete can be followed by creation of an orphan file.
- `schedule_strategy_route()` checks that the strategy is stopped, then changes
  APScheduler jobs and config outside the lifecycle lock. Concurrent start or
  delete can violate the check or leave an orphan job.
- `clear_logs()` checks `RUNNING_STRATEGIES`, releases no reservation, and then
  deletes logs. A concurrent start can open a log between the check and delete.
- `new_strategy()` derives IDs with one-second timestamp resolution. Two
  concurrent uploads with the same source filename in the same second use the
  same script path and registry key.
- scheduler jobs iterate shallow snapshots, then mutate the original configs or
  index the live registry after calls that can block.

References:

- `get_strategy_config()` and `snapshot_strategy_configs()` near the start of
  `blueprints/python_strategy.py`
- `scheduled_start_strategy()`, `market_hours_enforcer()`,
  `schedule_strategy()`, `new_strategy()`, `stop_strategy()`, `clear_logs()`,
  and `save_strategy()`

Required change: define atomic lifecycle transitions, such as
`STOPPED -> STARTING -> RUNNING -> STOPPING`, and perform the check plus state
reservation under one lock. Slow file/process work can occur outside the lock
only after a state reservation prevents incompatible operations. Script writes
should use temp-file + fsync + replace while start/delete are excluded.

Required gates: deterministic barrier tests for stop-vs-scheduled-start,
save-vs-start, save-vs-delete, schedule-vs-delete, clear-logs-vs-start, and two
same-name uploads in one second.

### PY-GT-04 — High — PR-12's green tests do not prove its stated rule

The PR-12 document says to never iterate the live registries, but
`status()` still has a list comprehension over
`STRATEGY_CONFIGS.items()`. The structural test scans `ast.For` only; Python
list comprehensions use `ast.comprehension`, so all seven PR-12 checks pass
while the unsafe iterator remains.

The behavioral tests exercise the newly added accessors directly. They do not
exercise concurrent Flask routes or scheduler jobs. They also prove only that
the outer list is copied, not that the returned config values form an immutable
or consistent snapshot.

References:

- `blueprints/python_strategy.py`, `status()` (currently around lines
  2232-2262)
- `test/test_gthread_python_strategy.py`,
  `test_no_direct_iteration_of_a_registry()`
- `docs/progress/gthread/PR-12-python-strategy.md`

Required change: cover `ast.comprehension` and generator expressions, then add
route-level concurrency tests. Do not mark registry work done until all direct
accesses are classified and state consistency—not only absence of Python
container exceptions—is tested.

### PY-GT-05 — High — initialization is not a readiness barrier

`initialize_with_app_context()` sets `_initialized = True` before restoration
finishes. A request arriving during startup sees `True` and proceeds against a
partially restored registry and scheduler. Restoration also publishes adopted
processes into `RUNNING_STRATEGIES` without the lifecycle lock.

This is especially relevant because `app.py` runs initialization in a daemon
background thread, while `/python/` and `/python/start/<id>` can call the same
initializer from request threads.

Required change: use a single-flight initialization state with an Event or
Condition (`NOT_STARTED`, `INITIALIZING`, `READY`, `FAILED`). Concurrent callers
must wait for READY or receive an explicit unavailable response; they must not
mistake `INITIALIZING` for completion.

Required gate: block restoration at a test barrier, issue concurrent status and
start requests, and prove neither observes or changes half-restored state.

### PY-GT-06 — Medium — scheduler database sessions lack per-job cleanup

The APScheduler jobs call auth and market-calendar functions backed by
`scoped_session`. `utils/db_sessions.py` explicitly requires background threads
to call `remove_all_scoped_sessions()` because Flask teardown does not run for
them. The `/python` scheduler entry points have no such `finally` cleanup.

With a persistent APScheduler thread pool, sessions and SQLite read
transactions can remain bound to executor threads. The pool bounds the number,
but does not make stale sessions or held read transactions correct.

Required change: wrap every scheduler entry point in a common `try/finally`
cleanup boundary, including success and exception paths.

Required gate: invoke each job repeatedly through the real scheduler executor
and assert all scoped-session registries are empty after every run and the file
descriptor count plateaus.

### PY-GT-07 — High — graceful shutdown is not bounded by Gunicorn's window

The module registers an `atexit` handler but never explicitly stops the Python
strategy scheduler. It then stops strategies serially. A stubborn strategy can
consume up to roughly seven seconds of terminate/kill waits, while Gunicorn's
configured graceful timeout is 30 seconds. Five or more stubborn strategies can
exceed the worker's entire shutdown allowance and be killed before cleanup
finishes.

Required change: stop new scheduler dispatch first, signal all process groups,
wait for them collectively within a single deadline, kill survivors, persist
final state, and finish comfortably inside the 30-second Gunicorn budget.

Required gate: rehearse restart with 1, 5, and 10 strategies, including a
strategy that ignores SIGTERM and one that creates a child process. No process
or process-group member may remain after the container exits.

### PY-GT-08 — Medium — test/tracker bookkeeping currently overstates completion

The PR-12 tracker change adds another `GT-A14-01` and `GT-A14-02`, but those IDs
already belong to Flask session and CSRF rows. The current file has 154 rows but
only 152 unique IDs. The tracker consistency tests do not enforce ID
uniqueness, so the README's totals count the duplicate rows and still pass.

The new registry row is marked `done` despite PY-GT-01 through PY-GT-07 and the
remaining live list comprehension. PR-12 should remain in progress and use a
new, unique gate/phase identifier.

Required gates: tracker IDs are unique, every linked progress document exists,
and a `done` row's named test is collected by CI and covers its measurable
criterion.

## What is already suitable for gthread

- A strategy is a subprocess, not a resident Gunicorn thread.
- Start and stop of the same registry entry are substantially serialized by
  `PROCESS_LOCK`; this is a useful foundation.
- The SSE subscriber list uses a real `threading.Lock`, each subscriber has a
  thread-safe `queue.Queue`, and generator cleanup removes disconnected
  subscribers in `finally`.
- The React page creates one `EventSource` on mount and closes it on unmount.
- PR-10h accounts for each `/python` SSE connection as one pinned gthread.
- APScheduler now sets explicit `coalesce`, `max_instances`, and a 300-second
  misfire grace.
- Gunicorn remains at one worker, which is required while these registries and
  the scheduler are process-local.

The five-stream planning assumption remains reasonable for normal steady
state. A live test should still measure temporary EventSource reconnect overlap
and verify ordinary HTTP capacity remains available while all five streams are
open.

## Cross-platform acceptance matrix

| Platform | Required `/python` coverage |
| --- | --- |
| Linux Docker + Gunicorn gthread | POSIX launch without `preexec_fn`; process-group stop; concurrent lifecycle and config persistence; 30-second container restart; SSE capacity |
| macOS threaded dev server | Same registry/file/lifecycle tests; subprocess launch is particularly important because Python documents a higher fork/thread deadlock risk on macOS |
| Windows threaded dev server | Registry/file/lifecycle tests; atomic replacement behavior; `CREATE_NEW_PROCESS_GROUP` + `taskkill /T`; document that POSIX resource limits do not apply |

## Verification performed

- `pytest -q test/test_gthread_*.py`: **246 passed**. This also emitted two
  shutdown-time logging errors from the module's `atexit` handler after pytest
  had closed its captured stream.
- `pytest -q test/test_python_strategy_exchange_aware.py
  test/test_python_strategy_edge_cases.py`: **40 passed**, with the same
  shutdown logging noise.
- Deterministic two-thread `save_configs()` collision: reproduced one swallowed
  `FileNotFoundError` at the shared temp-file rename.
- AST review: the new structural test was green while `status()` retained a
  live-registry list comprehension.
- Tracker parse: **154 rows, 152 unique IDs**; duplicate IDs are `GT-A14-01`
  and `GT-A14-02`.

The passing suites show the existing behavior is preserved and the narrow
registry helpers work. They do not clear the release blockers above.

## Recommended implementation order

1. Remove `preexec_fn` and add the post-exec strategy wrapper.
2. Introduce serialized, generation-ordered config persistence.
3. Define and enforce lifecycle state transitions across request/scheduler
   boundaries.
4. Make initialization single-flight and waitable.
5. Add scheduler session cleanup and bounded shutdown.
6. Replace the narrow registry detector with route-level deterministic
   concurrency tests, correct the tracker IDs, and then re-run the three-platform
   matrix and live soak.

## Recheck of PR-12 and PR-12a

### Commit `7021c82e8`

PR-12 is safe to retain as an incremental registry fix. In an isolated checkout,
its seven new checks plus the 40 existing `/python` tests passed (47/47). The
accessors, top-level registry snapshots, and publish-by-rebind load are useful
foundations.

The commit does not justify the broader title "make the `/python` registries
thread-safe" or the tracker state `done`: it leaves PY-GT-01 through PY-GT-07,
misses the `/python/status` list comprehension, and introduced duplicate tracker
IDs. Those are completion/reporting problems rather than reasons to revert the
useful code.

### Commit `9bb961e6a` (PR-12a)

PR-12a moves several findings in the right direction:

- removes the actual `preexec_fn` assignment;
- adds a post-exec resource-limit bootstrap;
- changes `/python/status` to use a registry snapshot and expands the AST gate to
  comprehension nodes;
- makes initialization single-flight and sets `_initialized` last;
- uses unique temp files for configuration writes;
- renumbers the new tracker rows to unique `GT-A15-*` IDs and records the
  lifecycle/session-cleanup work as open.

It is **not ready to be treated as complete or deployed under gthread** in the
reviewed state:

1. `save_configs()` acquires `_CONFIG_FILE_LOCK` and then `PROCESS_LOCK`, while
   lifecycle callers already hold `PROCESS_LOCK` and call `save_configs()`. Two
   threads can therefore acquire the locks in opposite order and deadlock. A
   timed reproduction showed the config-saving side unable to acquire
   `PROCESS_LOCK` until the lifecycle side timed out and released it. The new
   concurrent-save test uses only savers, so every thread takes the same order
   and cannot detect this ABBA cycle.
2. `create_subprocess_args()` adds the bootstrap limit variables to its `env`,
   but `start_strategy_process()` later replaces that entire environment with a
   fresh `os.environ.copy()`. The observed values changed from `1024/3600` to
   `None/None`; the launched strategy therefore receives no new memory or CPU
   limits unless the host happens to define those internal variables. The test
   invokes `_RLIMIT_BOOTSTRAP` directly with a hand-built environment, bypassing
   the production assembly path. The bootstrap also omits the previous
   `RLIMIT_NOFILE` and `RLIMIT_NPROC` protections.
3. The post-exec wrapper does not preserve `sys.path[0]`. A normal
   `python /path/strategy.py` launch can import a sibling helper module from the
   strategy directory, while the new `python -c <bootstrap> /path/strategy.py`
   launch cannot. A deterministic probe returned `0` and printed
   `sibling-import-ok` under the old launch, but the wrapper returned `1` with
   `ModuleNotFoundError`. The bootstrap must insert the strategy directory into
   `sys.path` (matching direct-script semantics), and the production-path test
   must cover a sibling import.
4. Config persistence errors are still caught and swallowed, so mutating routes
   can report success after the disk publication failed. The 18 mutation/save
   paths outside `PROCESS_LOCK` also mean taking that lock only around
   `json.dumps()` does not create a consistent snapshot.
5. Shutdown still does not stop APScheduler first, still stops subprocesses
   sequentially, and states that remaining children are reaped with the worker.
   That is false for bare-metal installs: without a parent-death signal or
   explicit termination, children are reparented and can keep running. The test
   checks only lexical lock placement and a constant smaller than 30; it does not
   run a stubborn child, a child process tree, or a scheduler race.
6. The lifecycle operations and scheduler scoped-session cleanup remain open,
   correctly recorded as `GT-A15-06` and `GT-A15-07`.

Verification of that working-tree state:

- focused `/python` tests: **52 passed**;
- gthread Python suite: **251 passed**;
- Ruff: **passed** for the changed Python source and test;
- both pytest runs emitted logging errors from `cleanup_on_exit()` after pytest
  had closed its capture stream;
- tracker: **159 rows / 159 unique IDs** after the follow-up renumbering;
- `git show --check 9bb961e6a` reports whitespace errors on the newly added
  tracker rows and on three Markdown hard-break lines from the committed audit;
  the current audit-only working-tree diff passes `git diff --check`.

The green tests do not supersede the deterministic lock-order, environment
assembly, and sibling-import reproductions above. `GT-A15-02`, `GT-A15-03`,
and `GT-A15-04` should remain open until production-path tests cover their full
acceptance criteria. The PR-12a progress page's `Done` status and its statements
that limits are applied, config writes are fully serialized, and the OS reaps
remaining children are not supported by the committed implementation.

### Recommended correction sequence for PR-12a

1. Build the final child environment once, retaining the two resource-limit
   variables and the strategy variables. Restore `RLIMIT_NOFILE` and
   `RLIMIT_NPROC`, preserve the strategy directory in `sys.path`, and test the
   exact `Popen` command/environment construction rather than the bootstrap in
   isolation.
2. Remove the `_CONFIG_FILE_LOCK -> PROCESS_LOCK` / `PROCESS_LOCK ->
   _CONFIG_FILE_LOCK` cycle. Define one lock order or use a generation-ordered
   persistence worker; protect all writers and propagate persistence failure to
   the mutating caller. Add a barrier test with one lifecycle operation and one
   independent saver taking the opposing paths.
3. Stop APScheduler dispatch before process cleanup, signal all strategy process
   groups first, wait against one shared deadline, kill every survivor, and
   verify a stubborn strategy plus its child leaves no process behind on bare
   metal and in Docker.
4. Complete the per-strategy lifecycle/state-machine and scheduler-session work
   already recorded as `GT-A15-06` and `GT-A15-07`.
5. Only then mark `GT-A15-02/03/04` and PR-12a done; keep the progress page and
   tracker measurable criteria aligned with the production-path tests.

### Commit `c6b2e6aee` (PR-12b)

PR-12b correctly fixes three important parts of PR-12a:

- limit variables are added to the final child environment rather than an
  environment that is later discarded;
- the post-exec wrapper restores the strategy directory at `sys.path[0]`, and
  the behavioral sibling-import test passes;
- `save_configs()` no longer acquires `PROCESS_LOCK` from inside
  `_CONFIG_FILE_LOCK`, so the reported ABBA lock cycle is removed;
- the POSIX shutdown fallback now contains a real `os.killpg()` call, and the
  scheduler is asked to stop before the registry snapshot.

The commit is **not complete for `GT-A15-03` or the shutdown portion of
`GT-A15-04`**:

1. `save_configs()` snapshots under `PROCESS_LOCK`, releases it, and only then
   waits for `_CONFIG_FILE_LOCK`. Publication is serialized, but generation
   order is not. A deterministic ordered-lock reproduction forced a generation
   1 writer to snapshot first and publish after generation 2. Both calls
   returned `True`; memory ended at generation 2 while the JSON file ended at
   generation 1. The current stress test proves absence of the old deadlock and
   parse corruption, not that the latest committed generation wins.
2. The new Boolean return does not propagate. AST classification found 24
   production `save_configs()` calls and every call is a standalone expression;
   none checks or returns the value. Routes can still report success after
   persistence fails. `test_save_configs_reports_failure()` checks only that
   the function annotation contains `-> bool`, so it passes without exercising
   a single caller.
3. `SCHEDULER.shutdown(wait=False)` prevents new scheduling but permits an
   already-running job to continue. Cleanup then snapshots the registry without
   a shutdown state/reservation. A deterministic reproduction let an in-flight
   job acquire `PROCESS_LOCK` immediately after that snapshot and add
   `started-after-snapshot`; cleanup returned without seeing or killing it.
4. The Windows force-kill fallback calls `proc.kill()` for a strategy skipped by
   the graceful loop. Unlike the existing `taskkill /F /T` path, this does not
   guarantee termination of the strategy's child process tree. The AST test
   asserts only the POSIX `os.killpg` call.
5. The claim that every new assertion is AST-based is inaccurate. The positive
   resource-limit check is still the textual assertion
   `"apply_strategy_limits_env(strategy_env)" in src`; it does not prove the
   call result reaches `Popen`. The helper assertions and live-container output
   are useful evidence, but the test should capture the actual `Popen` kwargs.
6. The restored `RLIMIT_NPROC` default changed from 256 to 64. That may be a
   deliberate tighter policy, but it is a compatibility change rather than a
   restoration of prior behavior. The reported container output covered AS,
   CPU, and NOFILE, not NPROC.

Verification of commit `c6b2e6aee`:

- focused `/python` suite: **58 passed** (18 gthread checks plus 40 existing
  tests);
- complete gthread Python suite: **257 passed**;
- all four shell suites: **90 passed**;
- Ruff: **passed** for the changed Python source and test;
- both pytest runs still emitted shutdown-time logging errors because the
  `atexit` handler logs after pytest closes its capture stream;
- `git show --check c6b2e6aee` still reports trailing whitespace on the three
  changed tracker rows.

Recommended correction:

1. Couple snapshot generation to publication. Either use one consistent
   `PROCESS_LOCK -> _CONFIG_FILE_LOCK` critical section for state changes that
   must persist, or attach a monotonic generation and prevent an older snapshot
   from replacing a newer one. Add the ordered generation-1/generation-2 test.
2. Make mutating operations fail or roll back when persistence returns `False`;
   test actual routes and scheduler entry points, not the helper annotation.
3. Add a shutdown state checked by every start path before process creation, so
   already-running scheduler jobs cannot launch behind cleanup. On Windows use
   tree termination for the survivor fallback as well.
4. Replace the remaining textual launch assertion with a captured `Popen`
   command/environment test and explicitly decide/test the NPROC compatibility
   policy.

### Commit `68689cec5` (PR-12c)

The main corrective mechanisms in PR-12c hold:

- the monotonic generation guard prevents the reproduced generation-1 writer
  from overwriting a persisted generation 2;
- `_SHUTTING_DOWN` is set under `PROCESS_LOCK`, and
  `start_strategy_process()` checks it both before and after acquiring that
  lock;
- the Windows survivor branch invokes `taskkill /F /T`;
- `STRATEGY_NPROC_LIMIT` is restored to 256;
- the environment test now captures the kwargs passed to the mocked `Popen`
  instead of merely looking for a source string.

PR-12c is still **not sufficient to close persistence reporting or the full
cross-platform shutdown gate**:

1. The claim that the other 19 ignored save results are internal is incorrect.
   `/python/start/<id>` has two direct unchecked saves and then calls
   `start_strategy_process()`, whose state save is also unchecked.
   `/python/stop/<id>` has two unchecked saves and calls
   `stop_strategy_process()`, whose save is unchecked. These are user-facing
   mutating routes and can still return success when the new state will not
   survive restart. The five-route AST test omits both route functions.
2. The new `Popen` test is not filesystem-isolated. Its autouse fixture restores
   only the in-memory registries; it does not monkeypatch `CONFIG_FILE` or
   `LOGS_DIR`. Calling the real start path therefore writes the ignored
   `strategies/strategy_configs.json` and creates `envprobe_*` logs. Eleven such
   logs were present in the reviewed workspace. The combined suite also left
   the real ignored config file with one test key (`m`), and no config backup
   was found. Running this suite against a live bind-mounted installation can
   overwrite the user's strategy registry.
3. The shutdown race implementation is correct, but its test proves only the
   pre-entry check: it sets `_SHUTTING_DOWN` before calling start. Removing the
   essential second check under `PROCESS_LOCK` would still pass. A deterministic
   test must pause start after the first check, let cleanup set the flag while
   holding the lock, then prove `Popen` is never reached.
4. The Windows survivor test remains textual: it slices the function source and
   searches for `taskkill` and `/T`. Its own explanatory comment contains both,
   so removing the real subprocess call while retaining the comment can still
   pass. It also does not cover `taskkill` timeout: the fallback permits 10
   seconds per survivor after the nominal 20-second budget, and
   `subprocess.TimeoutExpired` is not caught by the current exception handler.
5. The process-level pytest `atexit` logging errors remain. They do not fail the
   suite but are now three errors per run because scheduler shutdown adds another
   log after pytest closes its capture stream.

Verification was run from isolated temporary working directories to avoid
further writes to the repository's ignored runtime state:

- complete gthread Python suite: **262 passed**;
- existing `/python` suite: **40 passed**;
- the gthread run created one isolated strategy config and one isolated
  `envprobe` log, confirming the filesystem side effect;
- the previously verified four shell suites remain **90 passed**;
- `git show --check 68689cec5` reports trailing whitespace on tracker rows
  `GT-A15-03` and `GT-A15-04`.

Recommended correction:

1. Include start and stop in persistence-failure handling; classify the
   remaining callers by user-visible operation rather than direct helper name.
2. Monkeypatch `CONFIG_FILE`, `LOGS_DIR`, generation counters, and any process
   registry state for every test that drives the real start/save path. Add a
   guard that fails if tests create files outside `tmp_path`.
3. Add the lock-boundary shutdown test and an actual Windows taskkill-command
   capture. Bound or catch taskkill timeout so cleanup continues through every
   survivor.
4. Inspect and recover `strategies/strategy_configs.json` from an external
   deployment backup before running these tests again; do not treat the current
   ignored file as a trustworthy production copy.
