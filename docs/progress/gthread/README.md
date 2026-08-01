# gthread Migration — Progress

Running log of the eventlet → gthread migration. One entry per completed
tracker row, newest last.

- **Plan:** [`docs/plans/2026-08-01-eventlet-to-gthread-migration-plan.md`](../../plans/2026-08-01-eventlet-to-gthread-migration-plan.md)
- **Tracker:** [`docs/plans/2026-08-01-gthread-migration-tracker.csv`](../../plans/2026-08-01-gthread-migration-tracker.csv)
- **Branch:** `gthread`

## Status

| Metric | Value |
| --- | --- |
| Tracker rows | 152 |
| Resolved (no work needed) | 27 |
| Completed by implementation | 2 |
| Open | 123 |
| PRs merged to branch | PR-1 |

## Rules this log follows

1. One PR per tracker `rollback_boundary`, each independently revertible.
2. Nothing merges without a test that fails before the change and passes after.
3. Tracker `status` moves `open` → `done` only when the test exists and runs.
4. Every entry names the failure the change prevents, not just the change.

---

## PR-1 — `update.sh` systemd unit migration

**Rows:** `GT-C2-01`, `GT-R-02` · **Gate:** C2 · **Ships on:** eventlet

### The failure this prevents

`install/update.sh` updated dependencies and ran `systemctl daemon-reload`
with the comment *"in case service file changed"* — but nothing ever rewrote
`ExecStart`. It was a reload with no edit.

So an upgrade that installs Gunicorn 26 (which has no eventlet worker) would
restart a unit still specifying `--worker-class eventlet`. The service dies,
and the operator has no automatic way back. This is broken today, before any
part of the gthread migration lands.

### What was implemented

`install/update.sh`:

- `migrate_systemd_worker_class()` — backs up the unit, rewrites
  `--worker-class`, adds or updates `--threads`, verifies the resulting
  `ExecStart` **before** anything is pruned, then reloads systemd.
- `restore_systemd_unit()` — puts the backup back and reloads.
- Step 7 now migrates before starting. If the service fails to start on the
  migrated unit, the previous unit is restored, the service is started again,
  and the script exits non-zero with an explicit message.

### The deliberate no-op

`TARGET_WORKER_CLASS` defaults to `eventlet`, so on today's installs the
migration detects "already correct" and changes nothing. PR-1 ships the
*mechanism*; PR-11 flips the value. This means the migration path is exercised
on every upgrade well before it is ever asked to change anything.

`UNIT_PATH_OVERRIDE` was added so the function can be driven against a
temporary unit without root or systemd.

### Tests

`test/test_gthread_unit_migration.sh` — extracts the real functions from
`update.sh` and sources them, so it tests shipped code rather than a copy.
10 assertions, all passing:

```
passed: 10  failed: 0  skipped: 0
```

Covering: missing unit is a safe no-op; a unit with no `--worker-class` is
untouched; an already-correct class does not rewrite; `eventlet` → `gthread`
leaves no eventlet reference; `--threads` is inserted when absent, updated
when present, and never duplicated; a backup is written before the rewrite;
and restore round-trips the original file byte-for-byte.

### Notes

Writing the test surfaced a portability trap: macOS BSD `sed` parses
`sed -i -E` as `-i` with backup suffix `-E`. `update.sh` only ever runs on
Linux/systemd so the shipped code is correct, but the test now shims `gsed`
onto `PATH` when present so the rewrite cases actually execute on a developer
machine instead of silently skipping.

The first version of this test reimplemented the `sed` calls instead of
invoking the function — it would have passed while testing nothing. That is
why `UNIT_PATH_OVERRIDE` exists.
