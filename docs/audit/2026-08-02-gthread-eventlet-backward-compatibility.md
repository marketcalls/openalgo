# Eventlet backward-compatibility audit for the gthread branch

**Date:** 2026-08-02

**Branch/HEAD:** `gthread` at `68689cec5`

**Comparison base:** `main` at `6577c782a`

## Verdict

Merging this branch does **not automatically move existing users to gthread**.
Every supported launch and upgrade surface still defaults to eventlet, Gunicorn
remains pinned below 26, and eventlet remains installed.

That is not sufficient to certify that no existing eventlet user can break.
The branch changes 122 files, and most correctness fixes are active regardless
of worker class. The current evidence supports a high-confidence opt-in design,
but not a zero-regression merge guarantee. Two gates remain: isolate the test
suite from runtime data, and run a real default-eventlet container regression
matrix rather than only unpatched Python tests plus a boot/health smoke.

## Deployment behavior confirmed

- `install/lib/gunicorn_runtime.sh` resolves a missing worker setting to
  `eventlet` and emits no `--threads` argument.
- `start.sh`, `install/install.sh`, and `install/install-multi.sh` use that
  resolver and retain eventlet unless `OPENALGO_WORKER_CLASS=gthread` is set.
- `install/update.sh` resolves an ordinary existing installation to eventlet;
  an eventlet systemd unit without a thread argument is left unchanged.
- Docker still installs `gunicorn>=25.0,<26` and eventlet.
- `requirements-nginx.txt` still includes eventlet.
- The CI workflow declares the default container expectation as eventlet and
  tests gthread as a separate explicit opt-in.

Therefore an existing user's worker class does not change merely because the
branch is merged or their installation is updated.

## Application compatibility evidence

An eventlet 0.41.1 overlay was loaded before application modules and
`eventlet.monkey_patch()` was applied, matching the important Gunicorn worker
ordering.

Targeted branch run:

- 83 tests covering `/python`, Telegram startup, Socket.IO emit serialization,
  MCP, proxy topology, and shared resources;
- 81 passed;
- two failed: the RLock test compares eventlet's truthy integer `1` with
  `True` by identity, and the Telegram startup test unexpectedly performs token
  validation.

The same two exact tests fail in the same way against an archived `main`
checkout under the same eventlet overlay. They are pre-existing test-harness
behavior, not regressions introduced by the gthread branch.

The new POSIX `/python` post-exec wrapper was also compared with direct
`python strategy.py` execution using a spawn-based `multiprocessing` strategy.
Both paths preserved `__main__`, `__file__`, child spawning, and returned
`CHILD 0 spawn-ok`.

The new Telegram `ThreadPoolExecutor` is constructed in both modes, but the
eventlet request branch continues to call `initialize_bot_sync()` rather than
the threaded initializer. Construction itself starts no executor worker.

## Why a no-break certification is still unavailable

### 1. Migration tests can overwrite an existing user's runtime files

The `/python` `Popen` test drives the real start path without monkeypatching
`CONFIG_FILE` or `LOGS_DIR`. The suite writes
`strategies/strategy_configs.json` and creates `envprobe_*` logs. In the
reviewed workspace, eleven envprobe logs were present and the ignored strategy
config contained one test key, `m`; no local config backup was found.

An isolated run of the 262 gthread tests independently created one strategy
config and one envprobe log. A user or contributor who runs tests in their live
checkout can therefore lose the on-disk strategy registry even while remaining
on eventlet.

### 2. Most migration tests do not run inside eventlet

The 262 `test_gthread_*.py` checks run under ordinary Python threading. The
default container job checks boot and health, but it is not a feature matrix for
Telegram, MCP SSE, Socket.IO, `/python`, broker calls, schedulers, and shutdown
under eventlet monkey-patching.

The targeted 81-test differential is useful evidence, but it does not cover all
122 changed files or every broker integration.

### 3. Shared runtime behavior changes even when the worker remains eventlet

These are not guarded by `OPENALGO_WORKER_CLASS`:

- `SerializedSocketIO` wraps all server emits in a process-wide RLock;
- SQLite retry and transaction changes affect existing request paths;
- shared HTTP and WebSocket client lifecycle changes affect broker traffic;
- cache snapshot/locking changes affect symbols and order sizing;
- sandbox managers and scheduler defaults changed;
- `/python` uses the post-exec wrapper, generation-ordered persistence, and new
  shutdown handling on eventlet too;
- Docker `start.sh` is now a shell supervisor instead of `exec`-ing Gunicorn.

The changes are generally defensive and the targeted eventlet checks found no
branch-specific failure, but the worker selector alone cannot prove their
backward compatibility.

### 4. Full container verification was not reproduced locally

The local Docker daemon was unavailable, so this audit could not independently
run the repository's default-eventlet container smoke, WebSocket upgrade, proxy
restart, or SIGTERM/graceful-shutdown rehearsal. A direct monkey-patched app
import was also contaminated by the live workspace database and hit a SQLite
lock, so it is not accepted as compatibility evidence.

## Required merge gates

1. Fix test isolation first: every strategy test must monkeypatch
   `CONFIG_FILE`, `LOGS_DIR`, generation counters, and process state to
   `tmp_path`. Add a gate that fails if the suite changes ignored runtime files.
2. Add a default-eventlet CI job that starts the actual Gunicorn eventlet worker
   and exercises, at minimum: login/API request, Socket.IO connect and emit,
   MCP SSE, Telegram initialization branch, `/python` start/stop with a harmless
   strategy, proxy WebSocket health, and scheduler/background-session cleanup.
3. Rehearse Docker SIGTERM with the new shell supervisor and verify Gunicorn's
   exit status, proxy termination, strategy process-tree cleanup, and the
   platform stop-grace window.
4. Run the broker compatibility matrix for the active broker SDKs or explicitly
   scope the first merge/canary to the brokers exercised in CI and live testing.
5. Keep `OPENALGO_WORKER_CLASS` unset in the release and verify the built image
   reports `eventlet` before publishing it.

## Merge recommendation

The opt-in architecture is backward-compatible at the deployment-selection
layer, and the targeted eventlet differential found no new failure. Do not
describe the current branch as guaranteed not to break existing eventlet users,
and do not merge it as generally safe until the runtime-file isolation and real
eventlet container gates above pass. After those gates, merging with eventlet as
the unchanged default is a reasonable low-risk rollout; changing the default to
gthread remains a separate release decision.
