# Strategy Release-Blockers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/strategy` keep every accepted-but-unfilled exit managed, correlate signal-flip retries to the correct position across fills/rejections/restart, render broker-authoritative books, and restore a hermetic full backend test suite.

**Architecture:** New strategy orders carry a durable `position_ref`, while active runs persist stop intent separately from final stop completion. The engine finalises only after flatness, recovery rebuilds overlapping flip positions by reference, and the frontend reconciles broker rows with local strategy context instead of treating the audit store as broker truth.

**Tech Stack:** Python 3.14, Flask, SQLAlchemy/SQLite, pytest, React 19, TypeScript, TanStack Query, Vitest, Biome, Ruff, PowerShell QA runner.

**Spec:** `docs/superpowers/specs/2026-08-30-strategy-release-blockers-design.md`

## Global Constraints

- Entry intent is durable before broker dispatch; an entry without a durable row is refused.
- An exit may dispatch without a row during a database outage, but must remain claimed to prevent duplicate covers.
- Exit ownership is a position instance, not merely a leg ID.
- Run locks protect only in-memory state; no database or broker I/O occurs while held.
- `run_stopped` and terminal frames occur only after confirmed flatness.
- Signal entries are refused while a persisted stop request is pending; exits and repeated stop attempts remain allowed.
- SQLite uses `NullPool`; every schema change is idempotently applied by `upgrade/migrate_strategy_module.py` and supports `--status`.
- No new thread, executor, async runtime, socket, or blocking primitive is introduced.
- Broker fields are authoritative; local rows only enrich broker data with Run/Leg/Kind/audit context.
- The SMTP test may not read operator settings or make a network connection.
- Python changes use Ruff; frontend changes use Biome; no icons or emojis are introduced.

---

## Task 1: Persist position identity and pending-stop intent

**Files:**

- Modify: `database/strategy_module_db.py`
- Modify: `upgrade/migrate_strategy_module.py`
- Create: `test/test_migrate_strategy_module.py`
- Modify: `test/test_strategy_module_db.py`

**Interfaces:**

- Produces `SmStrategyOrder.position_ref: str | None` and exposes it through `order_to_dict`.
- Produces `SmStrategyRun.stop_requested_at` and `stop_requested_reason` and exposes them through `run_to_dict`.
- Produces `request_run_stop(run_id: int, reason: str) -> bool`.
- `record_order(run_id, leg_id, kind, order={"position_ref": ref})` persists the reference.
- `finish_run` preserves final `stop_reason` and clears pending request fields.

- [ ] **Step 1: Add failing ORM/serializer tests**

```python
def test_order_round_trip_preserves_position_ref():
    run = _run()
    row = sm.record_order(run.id, 1, "entry", {**ORDER, "position_ref": "pos-a"})
    assert sm.order_to_dict(row)["position_ref"] == "pos-a"


def test_request_run_stop_is_pending_until_finish():
    run = _run()
    assert sm.request_run_stop(run.id, "manual")
    pending = sm.run_to_dict(sm.get_run(run.id))
    assert pending["stopped_at"] is None
    assert pending["stop_requested_reason"] == "manual"
    assert pending["stop_requested_at"] is not None
    sm.finish_run(run.id, "manual")
    complete = sm.run_to_dict(sm.get_run(run.id))
    assert complete["stop_reason"] == "manual"
    assert complete["stop_requested_reason"] is None
```

- [ ] **Step 2: Run the focused DB tests and verify RED**

Run: `uv run pytest -q test/test_strategy_module_db.py -k "position_ref or request_run_stop" --tb=short`

Expected: failures because the columns/functions are absent.

- [ ] **Step 3: Add failing populated-database migration tests**

```python
def test_apply_adds_runtime_safety_columns_without_changing_rows(tmp_path):
    engine = _legacy_strategy_engine(tmp_path)
    before = _row_counts(engine)
    assert migration.apply(engine)
    assert _column_names(engine, "sm_strategy_order") >= {"position_ref"}
    assert _column_names(engine, "sm_strategy_run") >= {
        "stop_requested_at",
        "stop_requested_reason",
    }
    assert _row_counts(engine) == before
    assert migration.apply(engine)
```

- [ ] **Step 4: Run the migration test and verify RED**

Run: `uv run pytest -q test/test_migrate_strategy_module.py --tb=short`

Expected: migration leaves all three columns missing.

- [ ] **Step 5: Implement the ORM, store helpers, and migration**

Add nullable ORM columns:

```python
position_ref = Column(String(32), nullable=True)
stop_requested_at = Column(DateTime, nullable=True)
stop_requested_reason = Column(String(30), nullable=True)
```

Persist stop intent atomically:

```python
def request_run_stop(run_id: int, reason: str) -> bool:
    updated = (
        db_session.query(SmStrategyRun)
        .filter(SmStrategyRun.id == run_id, SmStrategyRun.stopped_at.is_(None))
        .update(
            {
                "stop_requested_at": utcnow(),
                "stop_requested_reason": reason,
            },
            synchronize_session=False,
        )
    )
    db_session.commit()
    return updated == 1
```

Extend `ADDED_COLUMNS` with exact SQLite DDL and create the composite index
`ix_sm_order_run_leg_position` after columns exist. Make `status()` report both
missing columns and the missing index. Preserve existing rows and NULL values.

- [ ] **Step 6: Verify GREEN and migration idempotence**

Run: `uv run pytest -q test/test_strategy_module_db.py test/test_migrate_strategy_module.py --tb=short`

Expected: all tests pass.

- [ ] **Step 7: Lint and commit**

Run: `uv run ruff check database/strategy_module_db.py upgrade/migrate_strategy_module.py test/test_migrate_strategy_module.py test/test_strategy_module_db.py`

Commit:

```bash
git add database/strategy_module_db.py upgrade/migrate_strategy_module.py test/test_migrate_strategy_module.py test/test_strategy_module_db.py
git commit -m "feat(strategy): persist position and stop intent"
```

## Task 2: Correlate flip-exit retries to the outgoing position

**Files:**

- Modify: `services/strategy_module/state.py`
- Modify: `services/strategy_module/signals.py`
- Modify: `services/strategy_module/engine.py`
- Modify: `services/strategy_module/order_events.py`
- Modify: `database/strategy_module_db.py`
- Modify: `test/test_strategy_residual_safety.py`
- Modify: `test/test_strategy_module_signals.py`
- Modify: `test/test_strategy_module_order_events.py`

**Interfaces:**

- `state.new_position_ref() -> str` produces UUID hex references.
- Every new leg state carries `position_ref` and superseded state carries the outgoing reference and entry order ID.
- `claim_superseded_exit` returns a snapshot containing `claim_token` and `position_ref`.
- `bind_superseded_exit(run_id, leg_id, claim_token, order_row_id) -> bool` binds only the claimed outgoing position.
- `signals._place(strategy, run_id, leg, kind, position, exiting=False, exit_owner="live")` records the matching `position_ref` and arms only its owner.
- `database.strategy_module_db.EVENT_KINDS` includes `flip_outgoing_exit_rejected`.

- [ ] **Step 1: Copy the two failing independent probes into product CI**

Add these safe-outcome tests from `D:/algomirror/QA Audit/probes/test_strategy_residual_safety.py` unchanged in meaning:

```python
def test_fill_of_retried_flip_exit_settles_outgoing_not_live_position(broker):
    strategy = _signal_strategy()
    strategy_id = strategy.id
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = _run_of(strategy)
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    signals.handle_signal(strategy, "short_entry", leg_id=1)
    first_exit = next(row for row in store.list_orders(run_id) if row["kind"] == "exit_signal")
    order_events._apply_update(
        first_exit["broker_order_id"],
        _event(first_exit["broker_order_id"], status="rejected"),
    )
    strategy = store.get_strategy(strategy_id, USER)
    signals.handle_signal(strategy, "long_exit", leg_id=1)
    retry = max(
        (row for row in store.list_orders(run_id) if row["kind"] == "exit_signal"),
        key=lambda row: row["id"],
    )
    order_events._apply_update(
        retry["broker_order_id"],
        _event(retry["broker_order_id"], status="complete", avg=101.0),
    )
    live = state.get_run_state(run_id)["legs"]["1"]
    assert live["position"] == "S" and live["status"] == "open"
    assert live["superseded"] is None


def test_rejected_retry_of_flip_exit_can_be_retried_again(broker):
    strategy = _signal_strategy()
    strategy_id = strategy.id
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = _run_of(strategy)
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    signals.handle_signal(strategy, "short_entry", leg_id=1)
    first_exit = next(row for row in store.list_orders(run_id) if row["kind"] == "exit_signal")
    order_events._apply_update(
        first_exit["broker_order_id"],
        _event(first_exit["broker_order_id"], status="rejected"),
    )
    strategy = store.get_strategy(strategy_id, USER)
    signals.handle_signal(strategy, "long_exit", leg_id=1)
    retry = max(
        (row for row in store.list_orders(run_id) if row["kind"] == "exit_signal"),
        key=lambda row: row["id"],
    )
    order_events._apply_update(
        retry["broker_order_id"],
        _event(retry["broker_order_id"], status="rejected"),
    )
    broker.clear()
    signals.handle_signal(store.get_strategy(strategy_id, USER), "long_exit", leg_id=1)
    assert broker.actions == ["SELL"]
```

- [ ] **Step 2: Add direct ownership assertions**

```python
def test_retried_outgoing_exit_binds_only_superseded(broker):
    strategy = _signal_strategy()
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = _run_of(strategy)
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    signals.handle_signal(strategy, "short_entry", leg_id=1)
    first_exit = next(row for row in store.list_orders(run_id) if row["kind"] == "exit_signal")
    order_events._apply_update(
        first_exit["broker_order_id"],
        _event(first_exit["broker_order_id"], status="rejected"),
    )
    signals.handle_signal(strategy, "long_exit", leg_id=1)
    retry = max(store.list_orders(run_id), key=lambda row: row["id"])
    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["superseded"]["exit_order_id"] == retry["id"]
    assert leg["superseded"]["position_ref"] == retry["position_ref"]
    assert leg["exit_order_id"] is None
    assert leg["exit_kind"] is None
```

- [ ] **Step 3: Run the new flip tests and verify RED**

Run: `uv run pytest -q test/test_strategy_residual_safety.py test/test_strategy_module_signals.py test/test_strategy_module_order_events.py -k "retried or outgoing or superseded" --tb=short`

Expected: fill closes the live short, and rejection leaves superseded claimed.

- [ ] **Step 4: Implement explicit ownership and durable position references**

Generate references before entry intent is written:

```python
def new_position_ref() -> str:
    return uuid.uuid4().hex
```

Bind the outgoing row under the run lock:

```python
def bind_superseded_exit(run_id, leg_id, claim_token, order_row_id):
    with run_state(run_id) as run:
        superseded = run["legs"][str(leg_id)].get("superseded") if run else None
        if not superseded or superseded.get("exit_order_id") != claim_token:
            return False
        superseded["exit_order_id"] = order_row_id
        return True
```

Before dispatch, `_place` writes `position_ref` into the order row and calls the
owner-specific bind. On success it must skip live `exit_order_id` bookkeeping
when `exit_owner == "superseded"`. On synchronous failure, `_exit` releases the
exact row ID or claim token returned by `_Placement`.

- [ ] **Step 5: Correct live flip rejection event semantics**

When `release_superseded_exit` succeeds on an active run, record
`flip_outgoing_exit_rejected` with a message that the old side is held,
managed, and retryable. Do not call `_report_stranded_exit` or emit
`run_stop_failed` claiming the run already closed.

- [ ] **Step 6: Verify GREEN and run the independent probes**

Run: `uv run pytest -q test/test_strategy_residual_safety.py test/test_strategy_module_signals.py test/test_strategy_module_order_events.py --tb=short`

Run: `uv run pytest -q "D:/algomirror/QA Audit/probes/test_strategy_residual_safety.py" --tb=short`

Expected: both suites pass; the independent probe reports five passed.

- [ ] **Step 7: Lint and commit**

Run: `uv run ruff check services/strategy_module/state.py services/strategy_module/signals.py services/strategy_module/engine.py services/strategy_module/order_events.py database/strategy_module_db.py test/test_strategy_residual_safety.py test/test_strategy_module_signals.py test/test_strategy_module_order_events.py`

Commit:

```bash
git add services/strategy_module/state.py services/strategy_module/signals.py services/strategy_module/engine.py services/strategy_module/order_events.py database/strategy_module_db.py test/test_strategy_residual_safety.py test/test_strategy_module_signals.py test/test_strategy_module_order_events.py
git commit -m "fix(strategy): correlate retried flip exits"
```

## Task 3: Keep stop requests managed until confirmed flatness

**Files:**

- Modify: `services/strategy_module/engine.py`
- Modify: `services/strategy_module/signals.py`
- Modify: `services/strategy_module/order_events.py`
- Modify: `services/strategy_module/recovery.py`
- Modify: `database/strategy_module_db.py`
- Modify: `test/test_strategy_module_qa_edges.py`
- Modify: `test/test_strategy_module_order_events.py`
- Modify: `test/test_strategy_module_signals.py`
- Modify: `test/test_strategy_module_recovery.py`

**Interfaces:**

- `stop_run` returns `stop_pending: bool` on success.
- `apply_fill` finalises a flat run when `stop_requested_reason` is present, including signal runs.
- `handle_signal` rejects new entries with `note="run_stopping"` while stop intent is pending.
- Async rejected/cancelled exits release their exact owner and leave the active run retryable.
- `database.strategy_module_db.EVENT_KINDS` includes `run_stop_requested`.

- [ ] **Step 1: Write delayed-rejection and final-fill RED tests**

```python
def _filled_batch_run(broker):
    strategy_id = _make()
    run_id = _start(strategy_id).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    broker.clear()
    return run_id


def test_stop_acceptance_does_not_finalize_before_exit_fill(broker):
    run_id = _filled_batch_run(broker)
    result = engine.stop_run(run_id, USER)
    assert result["ok"] is True
    assert result["stop_pending"] is True
    assert store.get_run(run_id).stopped_at is None
    assert state.get_run_state(run_id) is not None


def test_async_rejected_stop_exit_stays_managed_and_retryable(broker):
    run_id = _filled_batch_run(broker)
    engine.stop_run(run_id, USER)
    exit_row = max(store.list_orders(run_id), key=lambda row: row["id"])
    order_events._apply_update(
        exit_row["broker_order_id"],
        _event(exit_row["broker_order_id"], status="rejected"),
    )
    assert store.get_run(run_id).stopped_at is None
    assert state.get_run_state(run_id)["legs"]["1"]["exit_kind"] is None
    assert engine.stop_run(run_id, USER)["ok"] is True


def test_final_exit_fill_completes_pending_stop(broker):
    run_id = _filled_batch_run(broker)
    engine.stop_run(run_id, USER)
    exit_row = max(store.list_orders(run_id), key=lambda row: row["id"])
    order_events._apply_update(
        exit_row["broker_order_id"],
        _event(exit_row["broker_order_id"], status="complete", avg=101.0),
    )
    assert store.get_run(run_id).stopped_at is not None
    assert state.get_run_state(run_id) is None
```

- [ ] **Step 2: Write signal-entry and recovery RED tests**

```python
def test_signal_entry_is_refused_while_stop_pending(broker):
    strategy = _signal_strategy()
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = _run_of(strategy)
    store.request_run_stop(run_id, "manual")
    broker.clear()
    result = signals.handle_signal(strategy, "long_entry", leg_id=1)
    assert result.ok is False
    assert result.note == "run_stopping"
    assert broker.orders == []


def test_recovery_preserves_pending_stop_and_rejected_exit_is_retryable():
    strategy_id = _strategy()
    run_id = _run(strategy_id)
    _order(run_id, kind="entry", status="complete", avg=100.0)
    _order(run_id, kind="exit_close_all", action="BUY", status="rejected")
    assert store.request_run_stop(run_id, "manual")
    recovered = recovery.recover_run(run_id)
    assert recovered.ok
    assert store.get_run(run_id).stop_requested_reason == "manual"
    assert state.get_run_state(run_id)["legs"]["1"]["exit_kind"] is None
```

- [ ] **Step 3: Run the lifecycle tests and verify RED**

Run: `uv run pytest -q test/test_strategy_module_qa_edges.py test/test_strategy_module_order_events.py test/test_strategy_module_signals.py test/test_strategy_module_recovery.py -k "stop_pending or before_exit_fill or async_rejected_stop or run_stopping or pending_stop" --tb=short`

Expected: current `stop_run` writes `stopped_at` immediately and clears state.

- [ ] **Step 4: Persist stop intent before exits and finalise only when flat**

Change `stop_run` to call `request_run_stop` before `_exit_legs`. After dispatch:

```python
with state.run_state(run_id) as run:
    still_held = bool(state.open_legs(run)) if run else False
if refused and still_held:
    return {"ok": False, "stop_pending": True, "error": message, "exits": exits}
if still_held:
    return {"ok": True, "stop_pending": True, "exits": exits}
`_finalise(run_id, strategy_id, user_id, requested_reason, message)`
return {"ok": True, "stop_pending": False, "exits": exits}
```

In `apply_fill`, read the run row after leaving the state lock. Finalise when
flat and either the strategy is batch or `stop_requested_reason` is non-null.
Use the persisted requested reason when present.

- [ ] **Step 5: Keep rejected exits managed and block new entries**

For a live run, async dead exits release their `position_ref` owner and emit an
accurate `run_stop_failed`. `handle_signal` checks active run stop intent after
`_day_run`; entry actions return `SignalResult(ok=False, note="run_stopping")`,
while exit actions continue.

- [ ] **Step 6: Verify GREEN across lifecycle/recovery tests**

Run: `uv run pytest -q test/test_strategy_module_qa_edges.py test/test_strategy_module_order_events.py test/test_strategy_module_signals.py test/test_strategy_module_recovery.py --tb=short`

Expected: all tests pass.

- [ ] **Step 7: Lint and commit**

Run: `uv run ruff check services/strategy_module/engine.py services/strategy_module/signals.py services/strategy_module/order_events.py services/strategy_module/recovery.py database/strategy_module_db.py test/test_strategy_module_qa_edges.py test/test_strategy_module_order_events.py test/test_strategy_module_signals.py test/test_strategy_module_recovery.py`

Commit:

```bash
git add services/strategy_module/engine.py services/strategy_module/signals.py services/strategy_module/order_events.py services/strategy_module/recovery.py database/strategy_module_db.py test/test_strategy_module_qa_edges.py test/test_strategy_module_order_events.py test/test_strategy_module_signals.py test/test_strategy_module_recovery.py
git commit -m "fix(strategy): finalize stops only after fills"
```

## Task 4: Recover both position instances of an unsettled flip

**Files:**

- Modify: `services/strategy_module/recovery.py`
- Modify: `services/strategy_module/state.py`
- Modify: `test/test_strategy_module_recovery.py`
- Modify: `test/test_strategy_residual_safety.py`

**Interfaces:**

- Recovery groups new-format entry/exit rows by `position_ref`.
- A recovered leg may contain one live position plus one `superseded` position.
- More than two simultaneously held references raises a recovery error and creates the existing critical recovery event.

- [ ] **Step 1: Write restart RED tests for working and rejected outgoing exits**

Extend the existing `_order` test helper with a `position_ref` argument and pass
it into `store.record_order`.

```python
@pytest.mark.parametrize("outgoing_status", ["open", "rejected"])
def test_recovery_restores_live_and_superseded_flip_positions(outgoing_status):
    strategy_id = _strategy()
    run_id = _run(strategy_id)
    old_entry = _order(
        run_id,
        kind="entry",
        action="BUY",
        status="complete",
        avg=100.0,
        position_ref="old-position",
    )
    old_exit = _order(
        run_id,
        kind="exit_signal",
        action="SELL",
        status=outgoing_status,
        position_ref="old-position",
    )
    _order(
        run_id,
        kind="entry",
        action="SELL",
        status="complete",
        avg=102.0,
        position_ref="new-position",
    )
    state.clear_run_state(run_id)
    result = recovery.recover_run(run_id)
    leg = state.get_run_state(run_id)["legs"]["1"]
    assert result.ok
    assert leg["position_ref"] == "new-position"
    assert leg["superseded"]["position_ref"] == "old-position"
    assert leg["superseded"]["entry_order_id"] == old_entry
    assert leg["superseded"]["exit_order_id"] == (
        old_exit if outgoing_status == "open" else None
    )
```

- [ ] **Step 2: Write the overexposure RED test**

```python
def test_recovery_refuses_to_drop_a_third_held_position_reference():
    strategy_id = _strategy()
    run_id = _run(strategy_id)
    _order(run_id, kind="entry", action="BUY", status="complete", avg=100.0, position_ref="one")
    _order(run_id, kind="entry", action="SELL", status="complete", avg=101.0, position_ref="two")
    _order(run_id, kind="entry", action="BUY", status="complete", avg=102.0, position_ref="three")
    result = recovery.recover_run(run_id)
    assert result.ok is False
    assert result.finalised is False
    assert store.get_run(run_id).stopped_at is None
    assert "more than two" in result.error
```

- [ ] **Step 3: Run recovery tests and verify RED**

Run: `uv run pytest -q test/test_strategy_module_recovery.py test/test_strategy_residual_safety.py -k "superseded_flip or position_reference or third_held" --tb=short`

Expected: recovery returns a single decisive position and omits `superseded`.

- [ ] **Step 4: Implement reference-grouped recovery with legacy fallback**

Partition rows with non-null references, fold each group into a position record,
then select held groups by entry/exit terminal state. Install the newest as live
and the preceding held group as:

```python
leg["superseded"] = {
    "position_ref": old["position_ref"],
    "entry_order_id": old["entry_order_id"],
    "exit_order_id": old["exit_order_id"],
    "position": old["position"],
    "entry_avg": old["entry_avg"],
    "qty": old["qty"],
}
```

Rows with NULL references keep the current `_decisive` behavior. Checkpoint
volatile fields overlay only the matching live/superseded position.

- [ ] **Step 5: Verify GREEN and run all recovery tests**

Run: `uv run pytest -q test/test_strategy_module_recovery.py test/test_strategy_residual_safety.py --tb=short`

Expected: all tests pass.

- [ ] **Step 6: Lint and commit**

Run: `uv run ruff check services/strategy_module/recovery.py services/strategy_module/state.py test/test_strategy_module_recovery.py test/test_strategy_residual_safety.py`

Commit:

```bash
git add services/strategy_module/recovery.py services/strategy_module/state.py test/test_strategy_module_recovery.py test/test_strategy_residual_safety.py
git commit -m "fix(strategy): recover unsettled flip positions"
```

## Task 5: Make the SMTP test hermetic

**Files:**

- Modify: `test/test_email_functionality.py`

**Interfaces:**

- The CLI calls `check_smtp_connection()`.
- Pytest uses `isolated_settings_database` and a monkeypatched validator.
- No production email module changes.

- [ ] **Step 1: Write the isolated fixture and safe assertion before changing the helper**

```python
@pytest.fixture(autouse=True)
def isolated_settings_database(tmp_path, monkeypatch):
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'settings.db'}",
        poolclass=NullPool,
        connect_args={"check_same_thread": False},
    )
    test_session = scoped_session(sessionmaker(bind=test_engine))
    monkeypatch.setattr(settings_db, "engine", test_engine)
    monkeypatch.setattr(settings_db, "db_session", test_session)
    settings_db.Base.query = test_session.query_property()
    settings_db.init_db()
    yield
    test_session.remove()
    test_engine.dispose()
```

The collected test seeds `smtp.invalid`, monkeypatches
`validate_smtp_settings`, calls the future `check_smtp_connection`, and asserts
the validator received the isolated values.

- [ ] **Step 2: Run the email test and verify RED**

Run: `uv run pytest -q test/test_email_functionality.py --tb=short`

Expected: failure because `check_smtp_connection` does not exist.

- [ ] **Step 3: Rename the CLI helper and retain one real pytest test**

Rename the current helper to `check_smtp_connection`; update `main()` to call
it. Define `test_smtp_connection(monkeypatch)` as the hermetic assertion. Do not
call the real `smtplib` path.

- [ ] **Step 4: Verify GREEN and commit**

Run: `uv run pytest -q test/test_email_functionality.py --tb=short`

Run: `uv run ruff check test/test_email_functionality.py`

Commit:

```bash
git add test/test_email_functionality.py
git commit -m "test: isolate SMTP diagnostic settings"
```

## Task 6: Make Orderbook and Tradebook broker-authoritative

**Files:**

- Modify: `frontend/src/types/strategy_module.ts`
- Modify: `frontend/src/api/strategy_module.ts`
- Modify: `frontend/src/pages/strategy/Detail.tsx`
- Modify: `frontend/src/pages/strategy/strategy_module.test.ts`
- Create: `frontend/src/pages/strategy/Detail.test.tsx`

**Interfaces:**

- `useBrokerBook` accepts `runId` and includes it in the query key and fetcher.
- Typed `BrokerOrder`, `BrokerTrade`, `ReconciledBrokerOrder`, and `ReconciledBrokerTrade` replace raw records.
- Pure reconciliation functions attach local `run_id`, `leg_id`, `kind`, and rejection context by normalized broker order ID.
- Tabs visibly separate broker-confirmed current/latest-run rows from local-only audit rows.

- [ ] **Step 1: Add API/query-key RED tests**

```typescript
it('passes run_id to the broker book request', async () => {
  mockGet.mockResolvedValue({ data: { status: 'success', data: [] } })
  await fetchStrategyTradebook(7, 42)
  expect(mockGet).toHaveBeenCalledWith('/strategy/api/strategies/7/tradebook', {
    params: { run_id: 42 },
  })
})
```

Render the hook, rerender with a different run ID, and assert the fetcher sees
both IDs rather than reusing one cache entry.

- [ ] **Step 2: Add pure reconciliation RED tests**

```typescript
it('uses broker truth while retaining strategy context', () => {
  const result = reconcileBrokerOrders(
    [{ orderid: 'A1', order_status: 'complete', quantity: 25, price: 101 }],
    [Object.assign({}, localOrder, { broker_order_id: 'A1', status: 'open', qty: 50 })]
  )
  expect(result.confirmed[0]).toMatchObject({
    order_status: 'complete',
    quantity: 25,
    price: 101,
    run_id: localOrder.run_id,
    leg_id: localOrder.leg_id,
    kind: localOrder.kind,
  })
})
```

Also assert a local row without broker ID is `localOnly`, and a successful
empty broker response is not marked unavailable.

- [ ] **Step 3: Run frontend unit tests and verify RED**

Run from `frontend`: `npm run test:run -- src/pages/strategy/strategy_module.test.ts src/pages/strategy/Detail.test.tsx --maxWorkers=2`

Expected: missing types/helpers and local-only tab behavior fail.

- [ ] **Step 4: Add typed broker contracts and reconciliation helpers**

Use broker `orderid` normalization as the join key. Broker fields remain
unchanged; attach optional local context fields. `useBrokerBook` becomes:

```typescript
export function useBrokerBook<T>(strategyId, runId, book, fetcher, isRunning) {
  return useQuery({
    queryKey: strategyQueryKeys.brokerBook(strategyId ?? 0, runId ?? 0, book),
    queryFn: () => fetcher(strategyId as number, runId ?? undefined),
    enabled: strategyId !== null,
    refetchInterval: strategyId !== null && isRunning ? LIVE_POLL_MS : false,
  })
}
```

- [ ] **Step 5: Render broker-confirmed and audit sections**

`OrdersTab` and `TradesTab` receive `strategy`, `live`, `orders`, and `loading`.
They call their broker fetchers using `live.runId ?? strategy.current_run_id`.
The primary table shows broker values plus Run/Leg/Kind. The secondary table
shows local-only or no-longer-in-daily-book rows under “Strategy audit records”.
On null broker data, show: “Broker unavailable — showing recorded strategy
audit, which may lag.”

- [ ] **Step 6: Verify GREEN, full targeted frontend, lint and build**

Run from `frontend`:

```bash
npm run test:run -- src/pages/strategy --maxWorkers=2
npm run lint
npm run build -- --outDir ../tmp/strategy-release-blockers-dist --emptyOutDir
```

Expected: tests and build pass; Biome has no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/types/strategy_module.ts frontend/src/api/strategy_module.ts frontend/src/pages/strategy/Detail.tsx frontend/src/pages/strategy/strategy_module.test.ts frontend/src/pages/strategy/Detail.test.tsx
git commit -m "fix(strategy): use broker-backed books"
```

## Task 7: Align API, PRD, prompt, and BDD contracts

**Files:**

- Modify: `docs/api/strategy-services/stop.md`
- Modify: `docs/api/strategy-services/close_all.md`
- Modify: `docs/api/strategy-services/start.md`
- Modify: `docs/api/strategy-services/orders.md`
- Modify: `docs/api/strategy-services/events.md`
- Modify: `docs/api/strategy-services/README.md`
- Modify: `docs/prd/strategy-module-rms.md`
- Modify: `docs/prompt/strategy_rms_documentation.md`
- Modify: `docs/bdd/strategy_module_rms.feature`
- Modify: `D:/algomirror/QA Audit/tests/test_strategy_qa_audit.py`

**Interfaces:**

- Documents `stop_pending`, pending-stop fields, `position_ref`, broker-book truth source, unfilled entry refusal, `acknowledged`, and corrected event meanings.
- Refreshes BDD `# Source:` anchors to real current lines.
- Updates audit contract checks so they fail if stale immediate-finalisation claims return.

- [ ] **Step 1: Strengthen audit-doc RED checks**

Add assertions that both stop pages contain “confirmed flat” and
“accepted but not filled”, event docs distinguish `run_stop_requested`,
`run_stop_failed`, `flip_outgoing_exit_rejected`, and `run_stopped`, and the
book docs call broker rows authoritative.

- [ ] **Step 2: Run audit tooling and verify RED**

Run: `uv run pytest -q "D:/algomirror/QA Audit/tests" --tb=short`

Expected: new documentation contract assertions fail.

- [ ] **Step 3: Update all nine product documents**

Use one meaning consistently:

- accepted exit plus held position -> active run with `stop_pending: true`;
- refusal/rejection/cancellation/unfilled entry -> active, managed, retryable;
- final fill -> `run_stopped` and terminal frame;
- broker Orderbook/Tradebook -> broker-confirmed current/latest-run truth plus
  explicitly labelled local audit history;
- `acknowledged: false` -> broker response could not be persisted and requires
  reconciliation.

Remove the false `orders.md` claim that `exit_signal` is absent from
`ORDER_KINDS`. Refresh every affected BDD source anchor after the code settles.

- [ ] **Step 4: Verify GREEN and commit**

Run: `uv run pytest -q "D:/algomirror/QA Audit/tests" --tb=short`

Run: `uv run python "D:/algomirror/QA Audit/scripts/strategy_qa_audit.py" --repo "D:/algomirror/openalgo" --output "D:/algomirror/QA Audit/evidence" --test-runs-json "D:/algomirror/QA Audit/evidence/test_runs.json" --report "D:/algomirror/QA Audit/STRATEGY_QA_AUDIT_REPORT.md"`

Commit only repository documentation:

```bash
git add docs/api/strategy-services docs/prd/strategy-module-rms.md docs/prompt/strategy_rms_documentation.md docs/bdd/strategy_module_rms.feature
git commit -m "docs(strategy): align pending-stop and broker-book contracts"
```

## Task 8: Whole-change verification and fresh QA audit

**Files:**

- Modify if required by verified failures: only files already in Tasks 1-7
- Regenerate outside repository: `D:/algomirror/QA Audit/STRATEGY_QA_AUDIT_REPORT.md`
- Regenerate outside repository: `D:/algomirror/QA Audit/Strategy_QA_Audit_Register_Reaudit_<commit>.xlsx`
- Regenerate outside repository: `D:/algomirror/QA Audit/Strategy_QA_Test_Matrix_Reaudit_<commit>.xlsx`

**Interfaces:**

- Produces fresh evidence for the final commit, not cached prior results.
- Does not rewrite tracked `frontend/dist`; build output stays under `tmp` or QA evidence.
- Does not touch the pre-existing untracked database backup or `test_editor_strategy.py`.

- [ ] **Step 1: Run backend safety and migration gates**

```bash
uv run pytest -q test/test_strategy_residual_safety.py test/test_strategy_module_signals.py test/test_strategy_module_order_events.py test/test_strategy_module_qa_edges.py test/test_strategy_module_recovery.py test/test_migrate_strategy_module.py test/test_email_functionality.py --tb=short
uv run pytest -q "D:/algomirror/QA Audit/probes/test_strategy_residual_safety.py" --tb=short
uv run pytest -q test/test_eventlet_cross_thread_locks.py test/test_sqlite_lock_cooperative.py --tb=short
```

- [ ] **Step 2: Run static gates**

```bash
uv run ruff check database/strategy_module_db.py services/strategy_module upgrade/migrate_strategy_module.py test/test_strategy_module_db.py test/test_migrate_strategy_module.py test/test_strategy_residual_safety.py test/test_strategy_module_signals.py test/test_strategy_module_order_events.py test/test_strategy_module_qa_edges.py test/test_strategy_module_recovery.py test/test_email_functionality.py
cd frontend && npm run lint
cd frontend && npm run build -- --outDir ../tmp/strategy-release-blockers-dist --emptyOutDir
```

- [ ] **Step 3: Run complete source suites**

```bash
uv run pytest -q test -p no:cacheprovider --tb=short
cd frontend && npm run test:run -- --maxWorkers=2
```

- [ ] **Step 4: Run the repository FD audit procedure**

Read `.claude/skills/fd-audit/SKILL.md` completely and execute every check it
requires for the changed DB/event paths. Record commands and results in the SDD
report.

- [ ] **Step 5: Run the independent QA runner**

```powershell
& 'D:\algomirror\QA Audit\scripts\run_strategy_qa_audit.ps1' -RepoRoot 'D:\algomirror\openalgo'
```

Expected: all verification lanes pass and the refreshed report contains zero
open Critical or High findings for this scope. If unrelated Mediums remain,
their count and IDs are reported without relabelling them closed.

- [ ] **Step 6: Verify artifact integrity and repository status**

Check the report baseline equals `git rev-parse HEAD`, both XLSX files contain
`[Content_Types].xml`, `xl/workbook.xml`, styles and worksheets, and every row in
`evidence/artifact_hashes.csv` matches its file. Confirm repository status lists
only intentional changes plus the two preserved pre-existing untracked files.

- [ ] **Step 7: Commit any verification-only test/doc corrections**

```bash
git add test frontend/src docs upgrade database services
git commit -m "test(strategy): close release-blocker audit"
```

Skip this commit when verification required no repository correction.
