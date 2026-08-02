# Gthread implementation commit audit — 2026-08-01

## Scope

- Branch: `gthread`
- Plan baseline: `4fb6a8000` (Rev 12)
- Reviewed implementation range: `4a3335970..56763d38c`
- Commits reviewed: 23
- Changed files in the range: 109
- This document is audit-only. It does not change production code or tracker statuses.

## Verdict

The implementation is not ready for the default worker cutover. The tracker
reports 79 completed and 23 open items among 102 actionable rows (77.5%), but
at least 14 rows marked `done` do not yet satisfy their stated acceptance
criteria. On a strict fully-evidenced-row basis, implementation coverage is at
most about 64% (65/102). Several affected rows are partially implemented, so
this percentage is deliberately conservative.

The shipped default also remains eventlet. Gthread is currently an experimental
opt-in; the Gunicorn/eventlet dependency cutover is still PR-11b work.

## Findings

### 1. High — SQLite retry is not connected to production writers

Commit `64e30588e` adds `database/sqlite_retry.py` and tests the decorator in
test-local functions. No production function imports or applies
`retry_on_snapshot_conflict`. There are still 156 `commit()` call sites under
`database/` and `sandbox/`.

This leaves `GT-A4-02`, `GT-A4-05`, and `GT-A4-06` unimplemented despite their
`done` status. A real `SQLITE_BUSY_SNAPSHOT` on OpenAlgo, health, or sandbox
writes is still propagated rather than retried with a fresh read.

### 2. High — Symbol snapshot readers do not bind one generation

Commit `ffcd55172` correctly builds and publishes a replacement symbol snapshot
with one reference assignment, but accessors repeatedly evaluate properties
that each read `self._snap`. For example, `get_token()` checks membership in one
generation and indexes a newly published generation. Search paths do the same
for `by_exchange`.

A deterministic reproduction switches generations between those two property
reads and raises `KeyError`. The test only exercises direct whole-snapshot
assignments and does not drive the real accessors during a swap. `GT-A2-01`
therefore does not meet its complete-old-or-complete-new acceptance criterion.

### 3. Medium-high — Eight locked-cache rows retain compound races

`LockedTTLCache` correctly serializes each individual operation and explicitly
documents that `if key in cache: cache[key]` is still unsafe. That pattern, plus
membership-then-delete, remains in:

- `database/settings_db.py`
- `database/user_db.py`
- `database/flow_db.py`
- `database/strategy_db.py`
- `database/market_calendar_db.py`
- `database/leverage_db.py`
- `database/telegram_db.py`
- `database/whatsapp_db.py`

Expiry or concurrent invalidation between operations can still produce a
spurious `KeyError` or inconsistent cache result. The current test verifies the
cache class in all modules but checks atomic call sites only in `auth_db`.
`GT-A3-02`, `03`, `05`, `06`, `07`, `08`, `10`, and `11` are partial rather
than complete.

### 4. Medium — Telegram initialization is not single-flight after timeout

Commit `551afcfdd` releases `_init_lock` as soon as `future.result()` times out,
while the first future is still running. A retry then queues another initializer
on the one-worker executor. It does not overlap, but it runs immediately after
the first, so repeated retries can queue repeated state-changing initialization.

A reproduction produced calls `['first', 'second']`. The executor worker is
also non-daemon, contrary to the implementation comment, and the service never
shuts the executor down. `GT-T-01` does not meet “one initializer at a time; no
post-timeout state write.” The existing test refuses a second call only before
the first call reaches its timeout and specifically asserts that the lock is
released after timeout.

`stop_bot()` also does not take `_start_lock`, so a stop request can race the
start window and return “not running” immediately before the bot becomes live.

### 5. Medium — CI contains non-gating migration checks

- `scripts/gthread_sleep_inventory.py` always returns zero and has no expected
  baseline comparison, although CI says drift fails the gate.
- `test_gthread_worker_optin.sh` and `test_gthread_deploy_scripts.sh` pass
  locally but are not invoked by the CI shell-suite step.
- The real container gthread opt-in smoke test has `continue-on-error: true`.

The default eventlet boot remains blocking, which is appropriate before PR-11b,
but the experimental gthread path and two deployment suites can currently fail
without blocking a merge.

### 6. Medium — Proxy health acceptance is overstated

Generated Compose health checks probe Flask and TCP port 8765, but the
`Dockerfile` has no `HEALTHCHECK`. A direct `docker run` therefore has no Docker
health state. A TCP-open probe also proves that the proxy listener exists, not
that an upstream broker feed is connected. `GT-A7-03` is marked done with the
location “Dockerfile/compose healthcheck” and criterion “Never healthy with feed
dead”; the implementation does not fully meet either statement.

## Verification performed

- Gthread Python suites: 215 passed.
- Four gthread shell suites: 90 passed.
- Check-then-act gate: 31 pairs, 27 reviewed unlocked pairs, 0 unreviewed.
- Sleep inventory: 194 sites; 111 request-path sites across 48 files.
- Full repository test collection: failed before execution with seven collection
  errors. Six are sandbox-package import shadowing errors; one is the pre-existing
  `test/test_bot_web.py` import of missing `get_telegram_bot`. These appear to
  predate this commit range, but they prevent a clean whole-repository regression
  result for the branch.
- `git diff --check 4fb6a8000..56763d38c` reports trailing whitespace on the
  tracker CSV rows (CRLF line endings).

## Commit disposition

- Material blockers or incomplete acceptance: PR-2, PR-4, PR-5b, PR-6,
  PR-10/PR-11 CI wiring, and PR-10g.
- Runtime cutover intentionally incomplete: PR-11b, dependency repin/removal,
  deployment validation, rollback rehearsals, and soak/load criteria remain open.
- No additional release-blocking defect was identified in the reviewed final
  state of PR-1, PR-3, PR-5a, PR-7, PR-8, PR-9, PR-10b through PR-10f, or
  PR-10h through PR-10k. This is not a proof that undiscovered defects do not
  exist; it records the result of this review and its executed checks.

