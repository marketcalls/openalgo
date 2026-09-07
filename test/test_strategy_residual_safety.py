"""Adversarial residual probes for the audited /strategy production paths.

These tests deliberately assert the safe outcome. They live outside the product
test tree so they can document release-blocking behavior without modifying the
repository under audit. A failure is audit evidence, not an approved xfail.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import dotenv
import pytest

# Match the repository test harness before importing application modules.
dotenv.load_dotenv = lambda *args, **kwargs: False
dotenv.main.load_dotenv = dotenv.load_dotenv
os.environ["DATABASE_URL"] = "sqlite:///db/openalgo-test.db"
os.environ["SANDBOX_DATABASE_URL"] = "sqlite:///db/sandbox-test.db"
os.environ["LOGS_DATABASE_URL"] = "sqlite:///db/logs-test.db"
os.environ["LATENCY_DATABASE_URL"] = "sqlite:///db/latency-test.db"
os.environ["LOG_DIR"] = "log/test"
os.environ.setdefault("API_KEY_PEPPER", "0" * 64)
os.environ.setdefault("APP_KEY", "test-only-app-key")
REPO_ROOT = Path(__file__).resolve().parents[2] / "openalgo"
sys.path.insert(0, str(REPO_ROOT))

from database import strategy_module_db as store  # noqa: E402
from services.strategy_module import engine, order_events, signals, state  # noqa: E402
from services.strategy_module.order_dispatch import DispatchResult  # noqa: E402
from test import test_strategy_module_qa_edges as qa  # noqa: E402


def _purge() -> None:
    for row in store.list_strategies(qa.USER):
        for run in store.list_runs(row["id"]):
            state.clear_run_state(run["id"])
            if run["stopped_at"] is None:
                store.finish_run(run["id"], "error")
        state.clear_run_state(row["current_run_id"] or -1)
        store.set_strategy_status(row["id"], "stopped", None)
        store.delete_strategy(row["id"], qa.USER)
    for run_id in list(state.active_run_ids()):
        state.clear_run_state(run_id)
    store.clear_strategy_module_cache()


@pytest.fixture(autouse=True)
def isolated_strategy_state(monkeypatch: pytest.MonkeyPatch):
    store.db_session.remove()
    store.init_db()
    _purge()
    monkeypatch.setattr(engine, "_api_key_for", lambda _user_id: "qa-api-key")
    monkeypatch.setattr(signals, "_api_key_for", lambda _user_id: "qa-api-key")
    monkeypatch.setattr(engine, "_subscribe_run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(engine, "_unsubscribe_run", lambda *_args, **_kwargs: None)
    yield
    _purge()


@pytest.fixture
def broker(monkeypatch: pytest.MonkeyPatch) -> qa.Broker:
    fake = qa.Broker()
    monkeypatch.setattr(engine.order_dispatch, "dispatch_order", fake)
    return fake


def test_signal_entry_is_not_dispatched_when_its_intent_row_cannot_be_written(
    broker: qa.Broker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A signal order must have the same durable-first invariant as batch mode."""
    strategy = qa._signal_strategy()
    monkeypatch.setattr(store, "record_order", lambda *_args, **_kwargs: None)

    signals.handle_signal(strategy, "long_entry", leg_id=1)

    assert broker.orders == [], "the broker received an entry with no durable strategy row"


def test_batch_entry_persists_the_live_position_reference(broker: qa.Broker) -> None:
    """Batch live state and durable intent must name one position incarnation."""
    strategy_id = qa._make()

    result = qa._start(strategy_id)

    entry = store.list_orders(result.run_id)[0]
    leg = state.get_run_state(result.run_id)["legs"]["1"]
    assert entry["position_ref"] is not None
    assert len(entry["position_ref"]) == 32
    assert leg.get("position_ref") == entry["position_ref"]


def test_fill_between_exit_claim_and_classification_cannot_finalize_without_an_exit(
    broker: qa.Broker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fill in the two-lock window must be exited or leave the run managed."""
    sid = qa._make()
    run_id = qa._start(sid).run_id
    broker.clear()
    original_claim = state.claim_leg_exit
    injected = False

    def fill_after_failed_claim(candidate_run_id, leg_id, kind):
        nonlocal injected
        claimed = original_claim(candidate_run_id, leg_id, kind)
        if claimed is None and not injected:
            injected = True
            engine.apply_fill(candidate_run_id, leg_id, 100.0, is_entry=True)
        return claimed

    monkeypatch.setattr(state, "claim_leg_exit", fill_after_failed_claim)
    engine.stop_run(run_id, qa.USER, reason="manual")

    stopped = store.get_run(run_id).stopped_at is not None
    assert not (stopped and broker.orders == []), (
        "the run finalized after the entry filled without sending any exit"
    )


def test_rejected_signal_flip_exit_keeps_the_outgoing_position_exitable(
    broker: qa.Broker,
) -> None:
    """A dead superseded exit must not erase the operator's route to the old side."""
    strategy = qa._signal_strategy()
    strategy_id = strategy.id
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = qa._run_of(strategy)
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    signals.handle_signal(strategy, "short_entry", leg_id=1)
    exit_row = next(row for row in store.list_orders(run_id) if row["kind"] == "exit_signal")
    order_events._apply_update(
        exit_row["broker_order_id"],
        qa._event(exit_row["broker_order_id"], status="rejected", avg=0, filled=0),
    )
    broker.clear()
    strategy = store.get_strategy(strategy_id, qa.USER)

    signals.handle_signal(strategy, "long_exit", leg_id=1)

    assert broker.actions == ["SELL"], "the rejected outgoing long can no longer be exited"


def test_fill_of_retried_flip_exit_settles_outgoing_not_live_position(
    broker: qa.Broker,
) -> None:
    """The retry order id must stay attached to superseded, not the new side."""
    strategy = qa._signal_strategy()
    strategy_id = strategy.id
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = qa._run_of(strategy)
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    signals.handle_signal(strategy, "short_entry", leg_id=1)
    first_exit = next(row for row in store.list_orders(run_id) if row["kind"] == "exit_signal")
    order_events._apply_update(
        first_exit["broker_order_id"],
        qa._event(first_exit["broker_order_id"], status="rejected", avg=0, filled=0),
    )
    strategy = store.get_strategy(strategy_id, qa.USER)
    signals.handle_signal(strategy, "long_exit", leg_id=1)
    retry = max(
        (row for row in store.list_orders(run_id) if row["kind"] == "exit_signal"),
        key=lambda row: row["id"],
    )

    order_events._apply_update(
        retry["broker_order_id"],
        qa._event(retry["broker_order_id"], status="complete", avg=101.0, filled=100),
    )

    live = state.get_run_state(run_id)["legs"]["1"]
    assert live["position"] == "S" and live["status"] == "open", (
        "the outgoing long's retry fill closed the newly opened short"
    )
    assert live.get("superseded") is None, "the filled outgoing position remained tracked"


def test_rejected_retry_of_flip_exit_can_be_retried_again(broker: qa.Broker) -> None:
    """A retry rejection must clear the replacement id from superseded."""
    strategy = qa._signal_strategy()
    strategy_id = strategy.id
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = qa._run_of(strategy)
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    signals.handle_signal(strategy, "short_entry", leg_id=1)
    first_exit = next(row for row in store.list_orders(run_id) if row["kind"] == "exit_signal")
    order_events._apply_update(
        first_exit["broker_order_id"],
        qa._event(first_exit["broker_order_id"], status="rejected", avg=0, filled=0),
    )
    strategy = store.get_strategy(strategy_id, qa.USER)
    signals.handle_signal(strategy, "long_exit", leg_id=1)
    retry = max(
        (row for row in store.list_orders(run_id) if row["kind"] == "exit_signal"),
        key=lambda row: row["id"],
    )
    order_events._apply_update(
        retry["broker_order_id"],
        qa._event(retry["broker_order_id"], status="rejected", avg=0, filled=0),
    )
    broker.clear()
    strategy = store.get_strategy(strategy_id, qa.USER)

    signals.handle_signal(strategy, "long_exit", leg_id=1)

    assert broker.actions == ["SELL"], "a rejected retry left superseded permanently claimed"


def test_retried_outgoing_exit_binds_only_superseded(broker: qa.Broker) -> None:
    """A retry must arm only the outgoing position it closes."""
    strategy = qa._signal_strategy()
    strategy_id = strategy.id
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = qa._run_of(strategy)
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    signals.handle_signal(strategy, "short_entry", leg_id=1)
    first_exit = next(row for row in store.list_orders(run_id) if row["kind"] == "exit_signal")
    order_events._apply_update(
        first_exit["broker_order_id"],
        qa._event(first_exit["broker_order_id"], status="rejected", avg=0, filled=0),
    )

    strategy = store.get_strategy(strategy_id, qa.USER)
    signals.handle_signal(strategy, "long_exit", leg_id=1)

    retry = max(store.list_orders(run_id), key=lambda row: row["id"])
    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["superseded"]["exit_order_id"] == retry["id"]
    assert leg["superseded"]["position_ref"] == retry["position_ref"]
    assert leg["exit_order_id"] is None
    assert leg["exit_kind"] is None


def test_outgoing_claim_is_released_when_retry_fails_before_its_row(
    broker: qa.Broker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-persistence refusal must release the exact outgoing claim token."""
    strategy = qa._signal_strategy()
    strategy_id = strategy.id
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = qa._run_of(strategy)
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    signals.handle_signal(strategy, "short_entry", leg_id=1)
    first_exit = next(row for row in store.list_orders(run_id) if row["kind"] == "exit_signal")
    order_events._apply_update(
        first_exit["broker_order_id"],
        qa._event(first_exit["broker_order_id"], status="rejected", avg=0, filled=0),
    )
    strategy = store.get_strategy(strategy_id, qa.USER)
    monkeypatch.setattr(signals, "_api_key_for", lambda _user_id: None)
    before_events = sum(
        event["kind"] == "flip_outgoing_exit_rejected" for event in store.list_events(strategy_id)
    )

    result = signals.handle_signal(strategy, "long_exit", leg_id=1)

    assert result.ok is False
    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["superseded"]["exit_order_id"] is None
    events = [
        event
        for event in store.list_events(strategy_id)
        if event["kind"] == "flip_outgoing_exit_rejected"
    ]
    assert len(events) == before_events + 1
    event = events[0]
    assert all(word in event["message"].lower() for word in ("held", "managed", "retry"))


def _rejected_flip(broker: qa.Broker):
    """A live short plus an outgoing long whose first exit was rejected."""
    strategy = qa._signal_strategy()
    strategy_id = strategy.id
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = qa._run_of(strategy)
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    signals.handle_signal(strategy, "short_entry", leg_id=1)
    engine.apply_fill(run_id, 1, 95.0, is_entry=True)
    first_exit = next(row for row in store.list_orders(run_id) if row["kind"] == "exit_signal")
    order_events._apply_update(
        first_exit["broker_order_id"],
        qa._event(first_exit["broker_order_id"], status="rejected", avg=0, filled=0),
    )
    broker.clear()
    return strategy_id, run_id


def _live_identity(run_id: int) -> dict:
    leg = state.get_run_state(run_id)["legs"]["1"]
    return {
        "entry_order_id": leg["entry_order_id"],
        "entry_status": leg["entry_status"],
        "status": leg["status"],
        "position_ref": leg["position_ref"],
        "entry_avg": leg["entry_avg"],
        "exit_avg": leg["exit_avg"],
    }


def _assert_live_short_is_exitable(strategy_id: int, broker: qa.Broker) -> None:
    broker.clear()
    result = signals.handle_signal(store.get_strategy(strategy_id, qa.USER), "short_exit", leg_id=1)
    assert result.acted
    assert broker.actions == ["BUY"]


def test_accepted_outgoing_retry_does_not_rewrite_live_entry_bookkeeping(
    broker: qa.Broker,
) -> None:
    strategy_id, run_id = _rejected_flip(broker)
    before = _live_identity(run_id)

    result = signals.handle_signal(store.get_strategy(strategy_id, qa.USER), "long_exit", leg_id=1)

    assert result.acted
    assert _live_identity(run_id) == before
    _assert_live_short_is_exitable(strategy_id, broker)


def test_refused_outgoing_retry_preserves_live_entry_and_emits_retryable_event(
    broker: qa.Broker,
) -> None:
    strategy_id, run_id = _rejected_flip(broker)
    before = _live_identity(run_id)
    broker.refuse = True

    result = signals.handle_signal(store.get_strategy(strategy_id, qa.USER), "long_exit", leg_id=1)

    broker.refuse = False
    assert result.ok is False
    assert _live_identity(run_id) == before
    event = next(
        event
        for event in store.list_events(strategy_id)
        if event["kind"] == "flip_outgoing_exit_rejected"
    )
    assert all(word in event["message"].lower() for word in ("held", "managed", "retry"))
    _assert_live_short_is_exitable(strategy_id, broker)


def test_rowless_outgoing_retry_does_not_rewrite_live_entry_bookkeeping(
    broker: qa.Broker, monkeypatch: pytest.MonkeyPatch
) -> None:
    strategy_id, run_id = _rejected_flip(broker)
    before = _live_identity(run_id)
    record_order = store.record_order
    monkeypatch.setattr(store, "record_order", lambda *_args, **_kwargs: None)

    result = signals.handle_signal(store.get_strategy(strategy_id, qa.USER), "long_exit", leg_id=1)

    monkeypatch.setattr(store, "record_order", record_order)
    assert result.acted
    assert _live_identity(run_id) == before
    _assert_live_short_is_exitable(strategy_id, broker)


def test_second_flip_is_retry_neutral_while_the_first_outgoing_side_is_unsettled(
    broker: qa.Broker,
) -> None:
    strategy = qa._signal_strategy()
    strategy_id = strategy.id
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = qa._run_of(strategy)
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    signals.handle_signal(strategy, "short_entry", leg_id=1)
    engine.apply_fill(run_id, 1, 95.0, is_entry=True)
    superseded = state.get_run_state(run_id)["legs"]["1"]["superseded"]
    broker.clear()

    result = signals.handle_signal(store.get_strategy(strategy_id, qa.USER), "long_entry", leg_id=1)

    assert result.ok is True
    assert result.note == "flip_pending"
    assert broker.orders == []
    assert state.get_run_state(run_id)["legs"]["1"]["superseded"] == superseded


def test_position_mismatch_warning_runs_after_the_run_lock_is_released(
    broker: qa.Broker, monkeypatch: pytest.MonkeyPatch
) -> None:
    strategy = qa._signal_strategy()
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = qa._run_of(strategy)
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    lock_states = []

    def observe_warning(*_args, **_kwargs):
        lock_states.append(state.get_state_lock(run_id).locked())

    monkeypatch.setattr(engine.logger, "warning", observe_warning)

    engine.apply_fill(
        run_id,
        1,
        101.0,
        is_entry=False,
        order_row_id=99999,
        position_ref="not-the-live-position",
    )

    assert lock_states == [False]


def test_reentrant_opposite_entries_share_one_atomic_flip_claim(
    broker: qa.Broker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two short alerts racing a filled long may send one flip, not a hybrid."""
    strategy = qa._signal_strategy()
    strategy_id = strategy.id
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = qa._run_of(strategy)
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    original_entry = next(row for row in store.list_orders(run_id) if row["kind"] == "entry")
    broker.clear()
    real_exit = signals._exit
    nested_result = None
    reentered = False

    def exit_after_second_alert(*args, **kwargs):
        nonlocal nested_result, reentered
        if not reentered:
            reentered = True
            nested_result = signals.handle_signal(
                store.get_strategy(strategy_id, qa.USER), "short_entry", leg_id=1
            )
        return real_exit(*args, **kwargs)

    monkeypatch.setattr(signals, "_exit", exit_after_second_alert)

    first_result = signals.handle_signal(strategy, "short_entry", leg_id=1)

    entries = sorted(
        (row for row in store.list_orders(run_id) if row["kind"] == "entry"),
        key=lambda row: row["id"],
    )
    live = state.get_run_state(run_id)["legs"]["1"]
    assert first_result.ok is True
    assert nested_result.ok is True and nested_result.note == "flip_pending"
    assert broker.actions == ["SELL", "SELL"]
    assert len(entries) == 2
    assert live["position_ref"] == entries[-1]["position_ref"]
    assert live["superseded"]["position_ref"] == original_entry["position_ref"]
    assert live["superseded"]["exit_kind"] == "exit_signal"


def test_rejected_replacement_cannot_hide_and_duplicate_the_superseded_position(
    broker: qa.Broker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rejected short replacement must leave its still-held long authoritative."""
    strategy = qa._signal_strategy()
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = qa._run_of(strategy)
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    broker.clear()
    dispatch_count = 0

    def accept_exit_refuse_entry(**kwargs):
        nonlocal dispatch_count
        dispatch_count += 1
        broker.orders.append(kwargs["order"])
        if dispatch_count == 1:
            return DispatchResult(ok=True, broker_order_id="FLIP-EXIT", response={})
        return DispatchResult(ok=False, error="replacement refused")

    monkeypatch.setattr(signals.order_dispatch, "dispatch_order", accept_exit_refuse_entry)
    flip = signals.handle_signal(strategy, "short_entry", leg_id=1)
    before = state.get_run_state(run_id)["legs"]["1"]
    assert flip.ok is False
    assert before["status"] == "rejected"
    assert before["superseded"]["position"] == "B"
    broker.clear()

    repeated = signals.handle_signal(strategy, "long_entry", leg_id=1)

    after = state.get_run_state(run_id)["legs"]["1"]
    assert repeated.ok is True and repeated.note == "already_long"
    assert broker.orders == []
    assert after["superseded"] == before["superseded"]


def test_signal_entry_claim_is_released_after_resolution_failure(
    broker: qa.Broker, monkeypatch: pytest.MonkeyPatch
) -> None:
    strategy = qa._signal_strategy()
    real_resolve = signals._resolve_signal_leg
    monkeypatch.setattr(signals, "_resolve_signal_leg", lambda *_args: (None, "bad contract"))

    refused = signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = qa._run_of(strategy)

    assert refused.ok is False
    assert state.get_run_state(run_id).get("signal_entry_claims") == {}
    monkeypatch.setattr(signals, "_resolve_signal_leg", real_resolve)
    assert signals.handle_signal(strategy, "long_entry", leg_id=1).ok is True


def test_signal_entry_claim_is_released_after_intent_persistence_failure(
    broker: qa.Broker, monkeypatch: pytest.MonkeyPatch
) -> None:
    strategy = qa._signal_strategy()
    real_record_order = store.record_order
    monkeypatch.setattr(store, "record_order", lambda *_args, **_kwargs: None)

    refused = signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = qa._run_of(strategy)

    assert refused.ok is False
    assert state.get_run_state(run_id).get("signal_entry_claims") == {}
    monkeypatch.setattr(store, "record_order", real_record_order)
    assert signals.handle_signal(strategy, "long_entry", leg_id=1).ok is True


def test_flip_entry_claim_is_released_after_exit_refusal(broker: qa.Broker) -> None:
    strategy = qa._signal_strategy()
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = qa._run_of(strategy)
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    broker.refuse = True

    refused = signals.handle_signal(strategy, "short_entry", leg_id=1)

    assert refused.ok is False
    assert state.get_run_state(run_id).get("signal_entry_claims") == {}
    broker.refuse = False
    assert signals.handle_signal(strategy, "short_entry", leg_id=1).ok is True


def _terminal_after_ack(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    *,
    avg: float = 0.0,
    filled: int,
) -> None:
    """Inject a terminal frame after its broker id is durable, inside placement."""
    real_ack = engine._record_acknowledgement
    # Production handles the frame on another green thread with its own scoped
    # session. This deterministic same-stack injection must not detach the
    # placement's strategy ORM instance when the worker cleanup runs.
    monkeypatch.setattr("utils.db_sessions.remove_all_scoped_sessions", lambda: None)

    def acknowledge_then_publish(row_id, result, strategy_id, user_id, run_id, leg_id):
        acknowledged = real_ack(row_id, result, strategy_id, user_id, run_id, leg_id)
        order_events._apply_update(
            result.broker_order_id,
            qa._event(result.broker_order_id, status=status, avg=avg, filled=filled),
        )
        return acknowledged

    monkeypatch.setattr(engine, "_record_acknowledgement", acknowledge_then_publish)


def test_signal_exit_rejection_in_ack_window_releases_exact_owner_for_retry(
    broker: qa.Broker, monkeypatch: pytest.MonkeyPatch
) -> None:
    strategy = qa._signal_strategy()
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = qa._run_of(strategy)
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    broker.clear()
    _terminal_after_ack(monkeypatch, "rejected", filled=0)

    signals.handle_signal(strategy, "long_exit", leg_id=1)

    live = state.get_run_state(run_id)["legs"]["1"]
    assert live["exit_kind"] is None
    assert live["exit_order_id"] is None
    assert live.get("exit_claim_token") is None
    signals.handle_signal(strategy, "long_exit", leg_id=1)
    assert broker.actions == ["SELL", "SELL"]


def test_signal_entry_rejection_in_ack_window_is_not_overwritten_by_ack(
    broker: qa.Broker, monkeypatch: pytest.MonkeyPatch
) -> None:
    strategy = qa._signal_strategy()
    _terminal_after_ack(monkeypatch, "rejected", filled=0)

    signals.handle_signal(strategy, "long_entry", leg_id=1)

    run_id = qa._run_of(strategy)
    live = state.get_run_state(run_id)["legs"]["1"]
    assert live["entry_status"] == "rejected"
    assert live["status"] == "rejected"
    assert state.get_run_state(run_id)["signal_entry_claims"] == {}


def test_signal_flip_fill_in_ack_window_does_not_create_ghost_superseded_owner(
    broker: qa.Broker, monkeypatch: pytest.MonkeyPatch
) -> None:
    strategy = qa._signal_strategy()
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = qa._run_of(strategy)
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    broker.clear()
    _terminal_after_ack(monkeypatch, "complete", avg=101.0, filled=100)

    result = signals.handle_signal(strategy, "short_entry", leg_id=1)

    live = state.get_run_state(run_id)["legs"]["1"]
    assert result.ok is True
    assert live["position"] == "S"
    assert live["superseded"] is None


def _batch_exit(
    strategy_id: int,
    run_id: int,
) -> list[dict]:
    strategy = store.strategy_to_dict(store.get_strategy(strategy_id, qa.USER))
    return engine._exit_legs(
        run_id,
        strategy,
        [1],
        "exit_manual",
        "sandbox",
        "qa-api-key",
        qa.USER,
    )


def test_batch_exit_rejection_in_ack_window_releases_exact_owner_for_retry(
    broker: qa.Broker, monkeypatch: pytest.MonkeyPatch
) -> None:
    strategy_id = qa._make()
    run_id = qa._start(strategy_id).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    broker.clear()
    _terminal_after_ack(monkeypatch, "rejected", filled=0)

    _batch_exit(strategy_id, run_id)

    live = state.get_run_state(run_id)["legs"]["1"]
    assert live["exit_kind"] is None
    assert live["exit_order_id"] is None
    assert live.get("exit_claim_token") is None
    _batch_exit(strategy_id, run_id)
    assert broker.actions == ["BUY", "BUY"]


def test_batch_exit_fill_in_ack_window_observes_durable_bound_owner(
    broker: qa.Broker, monkeypatch: pytest.MonkeyPatch
) -> None:
    strategy_id = qa._make()
    run_id = qa._start(strategy_id).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    broker.clear()
    observed_owner_ids = []
    real_fill = engine.apply_fill

    def observe_bound_owner(*args, **kwargs):
        live = state.get_run_state(run_id)["legs"]["1"]
        observed_owner_ids.append(live["exit_order_id"])
        return real_fill(*args, **kwargs)

    monkeypatch.setattr(engine, "apply_fill", observe_bound_owner)
    _terminal_after_ack(monkeypatch, "complete", avg=101.0, filled=75)

    _batch_exit(strategy_id, run_id)

    exit_row = max(
        (row for row in store.list_orders(run_id) if row["kind"] == "exit_manual"),
        key=lambda row: row["id"],
    )
    assert observed_owner_ids == [exit_row["id"]]


def test_batch_entry_fill_in_ack_window_is_not_overwritten_by_ack(
    broker: qa.Broker, monkeypatch: pytest.MonkeyPatch
) -> None:
    strategy_id = qa._make()
    _terminal_after_ack(monkeypatch, "complete", avg=101.0, filled=75)

    run_id = qa._start(strategy_id).run_id

    live = state.get_run_state(run_id)["legs"]["1"]
    assert live["entry_status"] == "complete"
    assert live["status"] == "open"
    assert live["entry_avg"] == 101.0
