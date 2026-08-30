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
        qa._event(exit_row["broker_order_id"], status="rejected"),
    )
    broker.clear()
    strategy = store.get_strategy(strategy_id, qa.USER)

    signals.handle_signal(strategy, "long_exit", leg_id=1)

    assert broker.actions == ["SELL"], "the rejected outgoing long can no longer be exited"
