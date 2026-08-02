# Gthread follow-up audit — commit 2bec605c2

## Scope

- Reviewed commit: `2bec605c2`
- Parent: `56763d38c`
- Review date: 2026-08-02
- Audit only; no production code or tracker statuses changed.

## Verdict

The three implemented corrections are effective:

- the 11 symbol-cache accessors now use one snapshot generation;
- all four `test_gthread_*.sh` suites are invoked by CI;
- the sleep inventory now returns non-zero when its numeric baseline drifts.

The tracker arithmetic is also correct: 66 `done`, 50 `resolved`, and 36
`open` rows total 152; actionable coverage is 66 / (66 + 36) = 64.7%, reported
as 65%.

The four deliberately reopened implementation areas remain open: SQLite retry
wiring, eight compound-cache groups, Telegram initialization/lifecycle, and
Docker/proxy health semantics.

## Remaining findings

### 1. Medium — the future-accessor structural test has a blind spot

`test_no_method_reads_a_snapshot_field_twice()` detects repeated property access
such as `self.by_symbol_exchange`, but it does not detect repeated direct access
through `self._snap`, which the corrected class documentation recommends.

For example, this future regression is not flagged by the AST predicate:

```python
if key in self._snap.by_symbol_exchange:
    return self._snap.by_symbol_exchange[key]
```

For that shape the test records zero field reads because the `by_symbol_exchange`
attribute is rooted at an `Attribute` node (`self._snap`), not directly at the
`Name` node `self`. The current 11 accessors are covered behaviorally and are
correct; only the claim that the structural test protects methods not yet
written is overstated.

### 2. Low — the sleep baseline omits the tracker file counts

The gate checks 111 request-path sites, 78 streaming sites, 5 background sites,
194 total sites, and the 111-site budget term. Tracker rows GT-B2-01/02/03 also
record 48, 34, and 3 files respectively, and the plan records 85 total files.
Those file counts are computed by the script but not compared with a baseline.
The gate can therefore stay green while the tracker locations drift.

The numeric thread-budget gate works as claimed; “matches tracker rows” is only
partially enforced.

### 3. Low — progress reporting still contains stale and incorrect prose

`docs/progress/gthread/README.md` correctly reports 36 open rows in its table,
then says “Of the 23 items still to do” and retains the old 5 + 18 breakdown.

It also says the missing shell suites and non-failing sleep inventory are what
allowed the symbol-cache and SQLite defects through. That causal claim is not
supported by the workflow:

- the symbol-cache and SQLite Python tests were already included by
  `test/test_gthread_*.py` and ran in CI;
- the two omitted shell suites cover deployment/runtime scripts, not either
  defect;
- the sleep inventory does not inspect caches or SQLite callers.

The actual cause was narrower tests: publication rather than accessor behavior
for the symbol cache, and a test-local retry function rather than production
callers for SQLite.

The Rev-12 plan also remains a historical snapshot and still says implementation
and test completion are 0%. If the plan is intended to remain the current status
document, it needs a correction banner or a link to the current tracker/README.

## Verification evidence

- `pytest test/test_gthread_*.py -q --timeout=120`: 232 passed.
- All four `test/test_gthread_*.sh` suites: 90 passed.
- `gthread_check_then_act.py`: 0 unreviewed pairs.
- `gthread_sleep_inventory.py`: baseline green.
- Independently changing the in-memory expected total from 194 to 195 made
  `main()` return 1.
- Ruff on the four touched Python files reports five findings, all in unchanged
  lines of `database/token_db_enhanced.py`, matching the stated baseline.

