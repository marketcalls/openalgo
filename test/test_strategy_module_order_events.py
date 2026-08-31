"""Broker order updates driving strategy state.

This is the link that makes the module event-driven rather than polling: the
platform already publishes an OrderUpdateEvent for every asynchronous status
change, and the strategy engine needs the fill price out of it because that is
what every stop and target is measured from.

The pool is bypassed throughout: `_apply_update` is called directly so the
assertions are deterministic rather than racing a worker.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

# restx_api first: see the note in test_strategy_module_order_dispatch.py.
import restx_api  # noqa: F401
from database import strategy_module_db as store
from services.strategy_module import engine, order_events, state
from services.strategy_module.order_dispatch import DispatchResult

USER = "order_events_user"


def _event(orderid, status="complete", avg=100.0, filled=None, rejection=""):
    if filled is None:
        filled = 0 if str(status).strip().lower() in {"rejected", "cancelled", "canceled"} else 75
    return SimpleNamespace(
        orderid=orderid,
        order_status=status,
        average_price=avg,
        filled_quantity=filled,
        rejection_reason=rejection,
    )


@pytest.fixture(autouse=True)
def clean_slate():
    store.db_session.remove()
    store.init_db()

    def purge():
        for row in store.list_strategies(USER):
            for run in store.list_runs(row["id"]):
                state.clear_run_state(run["id"])
            store.set_strategy_status(row["id"], "stopped", None)
            store.delete_strategy(row["id"], USER)
        store.clear_strategy_module_cache()

    purge()
    yield
    purge()


@pytest.fixture
def order():
    """A strategy with one run and one entry order awaiting its fill."""
    created, error = store.create_strategy(
        USER,
        {
            "name": "Order events",
            "underlying": "NIFTY",
            "underlying_exchange": "NSE_INDEX",
            "universe_tab": "weekly_monthly",
            "legs": [{"id": 1, "segment": "options", "position": "S", "lots": 1}],
        },
    )
    assert error is None, error
    run = store.create_run(created["id"], "sandbox", "zerodha")
    row = store.record_order(
        run.id,
        leg_id=1,
        kind="entry",
        order={
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "SELL",
            "qty": 75,
            "broker_order_id": "BRK-1",
            "status": "open",
        },
    )
    return SimpleNamespace(strategy_id=created["id"], run_id=run.id, order_id=row.id)


def _install_pending_entry(order):
    """Make the fixture row the exact in-flight entry owned by live state."""
    assert store.set_strategy_status(order.strategy_id, "running", order.run_id)
    state.init_run_state(
        order.run_id,
        order.strategy_id,
        [
            {
                "leg_id": 1,
                "position": "S",
                "symbol": "NIFTY28MAY2624000CE",
                "exchange": "NFO",
                "quantity": 75,
            }
        ],
    )
    with state.run_state(order.run_id) as run:
        leg = run["legs"]["1"]
        leg["entry_order_id"] = order.order_id
        leg["entry_status"] = "open"
        leg["status"] = "open"


def _install_live_exit(
    order,
    *,
    broker_order_id="BRK-MONOTONIC-EXIT",
    position_ref="monotonic-owner",
    quantity=75,
):
    """Install one priced position and its exact working exit row."""
    assert store.update_order(
        order.order_id,
        status="complete",
        avg_fill_price=100.0,
        filled_qty=quantity,
    )
    assert store.set_strategy_status(order.strategy_id, "running", order.run_id)
    state.init_run_state(
        order.run_id,
        order.strategy_id,
        [
            {
                "leg_id": 1,
                "position": "B",
                "position_ref": position_ref,
                "symbol": "NIFTY28MAY2624000CE",
                "exchange": "NFO",
                "quantity": quantity,
            }
        ],
    )
    exit_row = store.record_order(
        order.run_id,
        1,
        "exit_close_all",
        {
            "position_ref": position_ref,
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "SELL",
            "qty": quantity,
            "broker_order_id": broker_order_id,
            "status": "open",
        },
    )
    assert exit_row is not None
    with state.run_state(order.run_id) as run:
        leg = run["legs"]["1"]
        leg["entry_order_id"] = order.order_id
        leg["entry_status"] = "complete"
        leg["entry_avg"] = 100.0
        leg["status"] = "open"
        leg["exit_order_id"] = exit_row.id
        leg["exit_kind"] = "exit_close_all"
    return exit_row


# ---------------------------------------------------------------------------


def test_an_update_for_somebody_elses_order_does_nothing(order):
    # Most order updates on this bus belong to another surface. Deciding that
    # must cost one indexed lookup and nothing more.
    with patch("services.strategy_module.engine.apply_fill") as apply_fill:
        order_events._apply_update("NOT-OURS", _event("NOT-OURS"))

    assert apply_fill.call_count == 0
    assert store.list_orders(order.run_id)[0]["status"] == "open"


def test_a_fill_updates_the_row_and_seeds_the_leg(order):
    with patch("services.strategy_module.engine.apply_fill") as apply_fill:
        order_events._apply_update("BRK-1", _event("BRK-1", avg=101.5))

    row = store.list_orders(order.run_id)[0]
    assert row["status"] == "complete"
    assert row["avg_fill_price"] == 101.5
    assert row["filled_qty"] == 75
    assert row["filled_at"] is not None

    # filled_qty rides along so the engine manages the size that actually
    # traded rather than the size that was asked for.
    apply_fill.assert_called_once_with(
        order.run_id, 1, 101.5, is_entry=True, filled_qty=75, order_row_id=order.order_id
    )


def test_the_same_fill_arriving_twice_is_applied_once(order):
    # A fill can arrive from a broker postback AND from the order-update
    # stream. Applying it twice would add the leg's realized profit to the run
    # a second time, and the strategy would then be judged against a total it
    # never made.
    with patch("services.strategy_module.engine.apply_fill") as apply_fill:
        order_events._apply_update("BRK-1", _event("BRK-1", avg=101.5))
        order_events._apply_update("BRK-1", _event("BRK-1", avg=101.5))
        order_events._apply_update("BRK-1", _event("BRK-1", status="COMPLETE", avg=101.5))

    assert apply_fill.call_count == 1


def test_an_exit_fill_is_applied_as_an_exit_not_an_entry(order):
    exit_row = store.record_order(
        order.run_id,
        leg_id=1,
        kind="exit_sl",
        order={
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "BUY",
            "qty": 75,
            "broker_order_id": "BRK-2",
            "status": "open",
        },
    )
    assert exit_row is not None

    with patch("services.strategy_module.engine.apply_fill") as apply_fill:
        order_events._apply_update("BRK-2", _event("BRK-2", avg=80.0))

    apply_fill.assert_called_once_with(
        order.run_id, 1, 80.0, is_entry=False, filled_qty=75, order_row_id=exit_row.id
    )


def test_a_rejection_marks_the_row_and_seeds_nothing(order):
    with patch("services.strategy_module.engine.apply_fill") as apply_fill:
        order_events._apply_update(
            "BRK-1",
            _event(
                "BRK-1",
                status="rejected",
                avg=0,
                filled=0,
                rejection="Insufficient margin",
            ),
        )

    row = store.list_orders(order.run_id)[0]
    assert row["status"] == "rejected"
    assert row["reject_reason"] == "Insufficient margin"
    assert apply_fill.call_count == 0


@pytest.mark.parametrize("ended", ["rejected", "cancelled"])
def test_a_terminal_partial_entry_is_real_exposure_and_pending_stop_exits_exact_fill(order, ended):
    _install_pending_entry(order)
    assert store.request_run_stop(order.run_id, "manual") is True
    dispatched = []

    def accept(**kwargs):
        dispatched.append(kwargs["order"])
        return DispatchResult(ok=True, broker_order_id="BRK-PARTIAL-EXIT", response={})

    with (
        patch.object(engine, "_api_key_for", return_value="test-key"),
        patch.object(engine.order_dispatch, "dispatch_order", side_effect=accept),
    ):
        order_events._apply_update(
            "BRK-1",
            _event("BRK-1", status=ended, avg=101.25, filled=25, rejection="remainder dead"),
        )

    durable = store.list_orders(order.run_id)[0]
    assert durable["status"] == ended
    assert durable["avg_fill_price"] == pytest.approx(101.25)
    assert durable["filled_qty"] == 25
    live = state.get_run_state(order.run_id)
    leg = live["legs"]["1"]
    assert leg["status"] == "open"
    assert leg["entry_status"] == "complete"
    assert leg["entry_avg"] == pytest.approx(101.25)
    assert leg["qty"] == 25
    assert dispatched[0]["quantity"] == "25"
    assert store.get_run(order.run_id).stopped_at is None


def test_terminal_zero_fields_preserve_a_previously_reported_partial_fill(order):
    _install_pending_entry(order)

    order_events._apply_update("BRK-1", _event("BRK-1", status="open", avg=101.25, filled=25))
    order_events._apply_update(
        "BRK-1",
        _event("BRK-1", status="cancelled", avg=0, filled=0, rejection="remainder dead"),
    )

    durable = store.list_orders(order.run_id)[0]
    assert durable["status"] == "cancelled"
    assert durable["avg_fill_price"] == pytest.approx(101.25)
    assert durable["filled_qty"] == 25
    leg = state.get_run_state(order.run_id)["legs"]["1"]
    assert leg["status"] == "open"
    assert leg["entry_avg"] == pytest.approx(101.25)
    assert leg["qty"] == 25


@pytest.mark.parametrize("ended", ["rejected", "cancelled"])
def test_terminal_partial_entry_without_price_remains_exact_managed_exposure(order, ended):
    """A positive broker quantity is exposure even when valuation is unavailable."""
    _install_pending_entry(order)

    order_events._apply_update(
        "BRK-1",
        _event("BRK-1", status=ended, avg=0, filled=25, rejection="remainder dead"),
    )

    durable = store.list_orders(order.run_id)[0]
    assert durable["status"] == ended
    assert durable["filled_qty"] == 25
    leg = state.get_run_state(order.run_id)["legs"]["1"]
    assert leg["status"] == "open"
    assert leg["entry_status"] == "complete"
    assert leg["entry_avg"] == 0.0
    assert leg["qty"] == 25
    critical = [
        event for event in store.list_events(order.strategy_id) if event["severity"] == "critical"
    ]
    assert any("price" in event["message"].lower() for event in critical)
    assert any("managed" in event["message"].lower() for event in critical)


def test_zero_fill_terminal_entry_completes_a_pending_stop_as_confirmed_flat(order):
    _install_pending_entry(order)
    assert store.request_run_stop(order.run_id, "scheduler") is True

    with (
        patch.object(engine, "_api_key_for", return_value=None),
        patch.object(engine.order_dispatch, "dispatch_order") as dispatch,
        patch.object(engine, "_unsubscribe_run"),
    ):
        order_events._apply_update(
            "BRK-1",
            _event("BRK-1", status="rejected", avg=0, filled=0, rejection="no fill"),
        )

    assert dispatch.call_count == 0
    assert store.get_run(order.run_id).stopped_at is not None
    assert store.get_run(order.run_id).stop_reason == "scheduler"
    assert state.get_run_state(order.run_id) is None
    assert [event["kind"] for event in store.list_events(order.strategy_id)].count(
        "run_stopped"
    ) == 1


def test_entry_fill_after_initial_unfilled_stop_is_immediately_kept_managed_and_exited(order):
    _install_pending_entry(order)
    exits = []

    def accept(**kwargs):
        exits.append(kwargs["order"])
        return DispatchResult(ok=True, broker_order_id="BRK-LATE-EXIT", response={})

    with (
        patch.object(engine, "_api_key_for", return_value="test-key"),
        patch.object(engine.order_dispatch, "dispatch_order", side_effect=accept),
    ):
        initial = engine.stop_run(order.run_id, USER, reason="manual")
        assert initial["ok"] is False
        assert initial["stop_pending"] is True
        assert exits == []

        order_events._apply_update("BRK-1", _event("BRK-1", status="complete", avg=99.5, filled=75))

    assert len(exits) == 1
    assert exits[0]["action"] == "BUY"
    assert exits[0]["quantity"] == "75"
    live = state.get_run_state(order.run_id)
    assert live is not None
    assert live["stopping"] is True
    assert live["legs"]["1"]["exit_kind"] == "exit_close_all"
    assert store.get_run(order.run_id).stopped_at is None


def test_late_fill_after_confirmed_zero_cancel_reopens_pending_stop_and_exits_exposure(order):
    """A corrected terminal fact after flat finalisation must become managed again."""
    _install_pending_entry(order)
    assert store.request_run_stop(order.run_id, "manual") is True

    with (
        patch.object(engine, "_api_key_for", return_value=None),
        patch.object(engine, "_unsubscribe_run"),
    ):
        order_events._apply_update(
            "BRK-1",
            _event("BRK-1", status="cancelled", avg=0, filled=0),
        )

    assert store.get_run(order.run_id).stopped_at is not None
    assert state.get_run_state(order.run_id) is None
    exits = []

    def accept_exit(**kwargs):
        exits.append(kwargs["order"])
        return DispatchResult(ok=True, broker_order_id="BRK-LATE-CORRECTION-EXIT", response={})

    with (
        patch.object(engine, "_api_key_for", return_value="test-key"),
        patch.object(engine.order_dispatch, "dispatch_order", side_effect=accept_exit),
        patch.object(engine, "_subscribe_run"),
        patch.object(engine, "_unsubscribe_run"),
    ):
        order_events._apply_update(
            "BRK-1",
            _event("BRK-1", status="complete", avg=101.5, filled=75),
        )

        durable = store.get_run(order.run_id)
        assert durable.stopped_at is None
        assert durable.stop_requested_reason == "manual"
        assert store.get_strategy(order.strategy_id, USER).current_run_id == order.run_id
        entry = store.get_order_by_broker_id("BRK-1")
        assert entry.status == "complete"
        assert entry.filled_qty == 75
        live = state.get_run_state(order.run_id)
        assert live["stopping"] is True
        assert live["legs"]["1"]["status"] == "open"
        assert live["legs"]["1"]["qty"] == 75
        assert exits[0]["quantity"] == "75"

        order_events._apply_update(
            "BRK-LATE-CORRECTION-EXIT",
            _event("BRK-LATE-CORRECTION-EXIT", status="complete", avg=102.0, filled=75),
        )

    assert store.get_run(order.run_id).stopped_at is not None
    assert state.get_run_state(order.run_id) is None


def test_late_fill_residual_finishes_without_releasing_a_newer_current_run(order):
    """An older corrected run is independent once a newer run owns the strategy."""
    _install_pending_entry(order)
    assert store.request_run_stop(order.run_id, "manual") is True

    with (
        patch.object(engine, "_api_key_for", return_value=None),
        patch.object(engine, "_unsubscribe_run"),
    ):
        order_events._apply_update(
            "BRK-1",
            _event("BRK-1", status="cancelled", avg=0, filled=0),
        )

    newer = store.create_run(order.strategy_id, "sandbox", "zerodha")
    assert newer is not None
    newer_id = newer.id
    assert store.set_strategy_status(order.strategy_id, "running", newer_id)

    with (
        patch.object(engine, "_api_key_for", return_value="test-key"),
        patch.object(
            engine.order_dispatch,
            "dispatch_order",
            return_value=DispatchResult(
                ok=True,
                broker_order_id="BRK-DETACHED-RESIDUAL-EXIT",
                response={},
            ),
        ),
        patch.object(engine, "_subscribe_run"),
        patch.object(engine, "_unsubscribe_run"),
    ):
        order_events._apply_update(
            "BRK-1",
            _event("BRK-1", status="complete", avg=101.5, filled=75),
        )

        assert store.get_run(order.run_id).stopped_at is None
        strategy = store.get_strategy(order.strategy_id, USER)
        assert strategy.current_run_id == newer_id
        assert strategy.status == "running"

        order_events._apply_update(
            "BRK-DETACHED-RESIDUAL-EXIT",
            _event(
                "BRK-DETACHED-RESIDUAL-EXIT",
                status="complete",
                avg=102.0,
                filled=75,
            ),
        )

    assert store.get_run(order.run_id).stopped_at is not None
    assert state.get_run_state(order.run_id) is None
    strategy = store.get_strategy(order.strategy_id, USER)
    assert strategy.current_run_id == newer_id
    assert strategy.status == "running"


def test_higher_complete_evidence_after_rejection_is_applied_as_one_positive_delta(order):
    _install_pending_entry(order)
    order_events._apply_update(
        "BRK-1", _event("BRK-1", status="rejected", avg=0, filled=0)
    )

    order_events._apply_update(
        "BRK-1", _event("BRK-1", status="complete", avg=101.5, filled=50)
    )

    durable = store.list_orders(order.run_id)[0]
    leg = state.get_run_state(order.run_id)["legs"]["1"]
    assert durable["status"] == "complete"
    assert durable["filled_qty"] == 50
    assert leg["status"] == "open"
    assert leg["qty"] == 50
    assert leg["entry_avg"] == pytest.approx(101.5)


def test_working_entry_fill_then_lower_cancellation_keeps_the_larger_cumulative_fact(order):
    _install_pending_entry(order)

    order_events._apply_update("BRK-1", _event("BRK-1", status="open", avg=101.5, filled=50))
    order_events._apply_update(
        "BRK-1", _event("BRK-1", status="cancelled", avg=99.0, filled=25)
    )

    durable = store.list_orders(order.run_id)[0]
    leg = state.get_run_state(order.run_id)["legs"]["1"]
    assert durable["status"] == "cancelled"
    assert durable["filled_qty"] == 50
    assert durable["avg_fill_price"] == pytest.approx(101.5)
    assert leg["status"] == "open"
    assert leg["qty"] == 50
    assert leg["entry_avg"] == pytest.approx(101.5)


@pytest.mark.parametrize("late_status", ["open", "complete"])
def test_higher_exit_correction_after_cancellation_reduces_exposure_once(order, late_status):
    exit_row = _install_live_exit(order)

    order_events._apply_update(
        "BRK-MONOTONIC-EXIT",
        _event("BRK-MONOTONIC-EXIT", status="cancelled", avg=0, filled=0),
    )
    order_events._apply_update(
        "BRK-MONOTONIC-EXIT",
        _event("BRK-MONOTONIC-EXIT", status=late_status, avg=110.0, filled=50),
    )
    order_events._apply_update(
        "BRK-MONOTONIC-EXIT",
        _event("BRK-MONOTONIC-EXIT", status="cancelled", avg=90.0, filled=25),
    )
    order_events._apply_update(
        "BRK-MONOTONIC-EXIT",
        _event("BRK-MONOTONIC-EXIT", status="complete", avg=110.0, filled=50),
    )

    durable = next(row for row in store.list_orders(order.run_id) if row["id"] == exit_row.id)
    leg = state.get_run_state(order.run_id)["legs"]["1"]
    expected_status = "complete" if late_status == "complete" else "cancelled"
    assert durable["status"] == expected_status
    assert durable["filled_qty"] == 50
    assert durable["avg_fill_price"] == pytest.approx(110.0)
    assert leg["status"] == "open"
    assert leg["qty"] == 25
    assert leg["realized_pnl"] == pytest.approx((110.0 - 100.0) * 50)


def test_working_exit_fill_then_lower_cancellation_applies_only_the_working_delta(order):
    _install_live_exit(order)

    order_events._apply_update(
        "BRK-MONOTONIC-EXIT",
        _event("BRK-MONOTONIC-EXIT", status="open", avg=110.0, filled=50),
    )
    order_events._apply_update(
        "BRK-MONOTONIC-EXIT",
        _event("BRK-MONOTONIC-EXIT", status="cancelled", avg=105.0, filled=25),
    )

    leg = state.get_run_state(order.run_id)["legs"]["1"]
    durable = store.get_order_by_broker_id("BRK-MONOTONIC-EXIT")
    assert durable.status == "cancelled"
    assert durable.filled_qty == 50
    assert float(durable.avg_fill_price) == pytest.approx(110.0)
    assert leg["qty"] == 25
    assert leg["realized_pnl"] == pytest.approx((110.0 - 100.0) * 50)
    assert leg["exit_order_id"] is None


def test_terminal_cumulative_exit_applies_only_delta_and_retry_uses_exact_remainder(order):
    """A terminal cumulative 50 after working 25 settles 25 more, never 50 more."""
    exit_row = _install_live_exit(order, broker_order_id="BRK-CUMULATIVE-EXIT")

    order_events._apply_update(
        "BRK-CUMULATIVE-EXIT",
        _event("BRK-CUMULATIVE-EXIT", status="open", avg=110.0, filled=25),
    )
    order_events._apply_update(
        "BRK-CUMULATIVE-EXIT",
        _event("BRK-CUMULATIVE-EXIT", status="cancelled", avg=112.0, filled=50),
    )

    durable = store.get_order(exit_row.id)
    leg = state.get_run_state(order.run_id)["legs"]["1"]
    assert durable.status == "cancelled"
    assert durable.filled_qty == 50
    assert float(durable.avg_fill_price) == pytest.approx(112.0)
    assert leg["qty"] == 25
    assert leg["realized_pnl"] == pytest.approx((112.0 - 100.0) * 50)
    assert leg["exit_order_id"] is None
    assert leg["exit_kind"] is None

    retries = []

    def accept_retry(**kwargs):
        retries.append(kwargs["order"])
        return DispatchResult(ok=True, broker_order_id="BRK-CUMULATIVE-RETRY", response={})

    with (
        patch.object(engine, "_api_key_for", return_value="test-key"),
        patch.object(engine.order_dispatch, "dispatch_order", side_effect=accept_retry),
    ):
        result = engine.stop_run(order.run_id, USER, reason="manual")

    assert result["ok"] is True
    assert result["stop_pending"] is True
    assert retries[0]["quantity"] == "25"
    retry = store.get_order_by_broker_id("BRK-CUMULATIVE-RETRY")
    assert retry.qty == 25
    assert state.get_run_state(order.run_id)["legs"]["1"]["exit_order_id"] == retry.id


def test_late_correction_cancels_and_replaces_an_already_working_retry(order, monkeypatch):
    original = _install_live_exit(order, broker_order_id="BRK-ORIGINAL")
    order_events._apply_update(
        "BRK-ORIGINAL",
        _event("BRK-ORIGINAL", status="cancelled", avg=110.0, filled=25),
    )
    retry = store.record_order(
        order.run_id,
        1,
        "exit_close_all",
        {
            "position_ref": "monotonic-owner",
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "SELL",
            "qty": 50,
            "broker_order_id": "BRK-RETRY",
            "status": "open",
        },
    )
    assert retry is not None
    retry_id = retry.id
    original_id = original.id
    with state.run_state(order.run_id) as run:
        leg = run["legs"]["1"]
        leg["exit_order_id"] = retry_id
        leg["exit_kind"] = "exit_close_all"

    cancel = Mock(return_value=DispatchResult(ok=True, broker_order_id="BRK-RETRY"))
    monkeypatch.setattr(
        engine.order_dispatch,
        "cancel_exit_order",
        cancel,
        raising=False,
    )
    with patch.object(engine, "_api_key_for", return_value="test-key"):
        order_events._apply_update(
            "BRK-ORIGINAL",
            _event("BRK-ORIGINAL", status="complete", avg=110.0, filled=50),
        )

    leg = state.get_run_state(order.run_id)["legs"]["1"]
    durable_retry = store.get_order_by_broker_id("BRK-RETRY")
    assert leg["qty"] == 25
    assert leg["exit_order_id"] == retry_id
    assert durable_retry.qty == 50
    cancel.assert_called_once()
    assert cancel.call_args.kwargs["broker_order_id"] == "BRK-RETRY"

    order_events._apply_update(
        "BRK-RETRY", _event("BRK-RETRY", status="cancelled", avg=0, filled=0)
    )
    assert state.get_run_state(order.run_id)["legs"]["1"]["exit_order_id"] is None

    replacement_orders = []

    def accept_replacement(**kwargs):
        replacement_orders.append(kwargs["order"])
        return DispatchResult(ok=True, broker_order_id="BRK-SAFE-REPLACEMENT", response={})

    with (
        patch.object(engine, "_api_key_for", return_value="test-key"),
        patch.object(engine.order_dispatch, "dispatch_order", side_effect=accept_replacement),
    ):
        result = engine.stop_run(order.run_id, USER, reason="manual")

    assert result["stop_pending"] is True
    assert replacement_orders[0]["quantity"] == "25"

    with patch.object(engine, "_unsubscribe_run"):
        order_events._apply_update(
            "BRK-SAFE-REPLACEMENT",
            _event("BRK-SAFE-REPLACEMENT", status="complete", avg=111.0, filled=25),
        )
    assert store.get_run(order.run_id).stopped_at is not None
    assert state.get_run_state(order.run_id) is None
    assert store.get_order_by_broker_id("BRK-ORIGINAL").filled_qty == 50
    assert original_id != retry_id


def test_failed_retry_cancel_audits_with_scalars_after_session_cleanup(order):
    """A broker helper may remove scoped sessions before the refusal is audited."""
    retry = store.record_order(
        order.run_id,
        1,
        "exit_close_all",
        {
            "position_ref": "detached-retry-owner",
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "SELL",
            "qty": 25,
            "broker_order_id": "BRK-DETACHED-RETRY",
            "status": "open",
        },
    )
    assert retry is not None
    retry_id = retry.id
    assert store.request_run_stop(order.run_id, "manual") is True

    def refuse_after_cleanup(**_kwargs):
        # A real broker path can log/commit before its scoped-session cleanup;
        # the commit expires every ORM instance held by this caller.
        store.record_event(
            order.strategy_id,
            USER,
            "leg_exit_placed",
            "broker cancellation attempt",
            run_id=order.run_id,
            leg_id=1,
        )
        store.db_session.remove()
        return DispatchResult(
            ok=False,
            broker_order_id="BRK-DETACHED-RETRY",
            error="broker busy",
        )

    with (
        patch.object(engine, "_api_key_for", return_value="test-key"),
        patch.object(
            engine.order_dispatch,
            "cancel_exit_order",
            side_effect=refuse_after_cleanup,
        ),
    ):
        cancelled = order_events._cancel_working_retry(order.run_id, retry_id)

    assert cancelled is False
    failures = [
        event
        for event in store.list_events(order.strategy_id)
        if event["kind"] == "run_stop_failed"
    ]
    assert len(failures) == 1
    assert "BRK-DETACHED-RETRY" in failures[0]["message"]
    assert failures[0]["leg_id"] == 1


def test_live_flip_rejection_is_retryable_not_reported_as_closed(order):
    """A dead outgoing exit remains owned by the active, managed run."""
    state.init_run_state(
        order.run_id,
        order.strategy_id,
        [
            {
                "leg_id": 1,
                "position": "S",
                "position_ref": "live-short",
                "symbol": "NIFTY28MAY2624000CE",
                "exchange": "NFO",
                "quantity": 75,
            }
        ],
    )
    exit_row = store.record_order(
        order.run_id,
        leg_id=1,
        kind="exit_signal",
        order={
            "position_ref": "outgoing-long",
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "SELL",
            "qty": 75,
            "broker_order_id": "BRK-FLIP",
            "status": "open",
        },
    )
    with state.run_state(order.run_id) as run:
        run["legs"]["1"]["status"] = "open"
        run["legs"]["1"]["entry_status"] = "complete"
        run["legs"]["1"]["superseded"] = {
            "position_ref": "outgoing-long",
            "entry_order_id": order.order_id,
            "exit_order_id": exit_row.id,
            "position": "B",
            "entry_avg": 100.0,
            "qty": 75,
        }

    order_events._apply_update(
        "BRK-FLIP",
        _event("BRK-FLIP", status="rejected", avg=0, filled=0),
    )

    leg = state.get_run_state(order.run_id)["legs"]["1"]
    assert leg["superseded"]["exit_order_id"] is None
    events = store.list_events(order.strategy_id)
    assert any(event["kind"] == "flip_outgoing_exit_rejected" for event in events)
    assert not any(event["kind"] == "run_stop_failed" for event in events)


@pytest.mark.parametrize("ended", ["rejected", "cancelled"])
def test_pending_stop_dead_exit_releases_exact_owner_and_reports_managed_retry(order, ended):
    """A dead stop exit leaves its position active, owned, and retryable."""
    state.init_run_state(
        order.run_id,
        order.strategy_id,
        [
            {
                "leg_id": 1,
                "position": "S",
                "position_ref": "pending-stop-position",
                "symbol": "NIFTY28MAY2624000CE",
                "exchange": "NFO",
                "quantity": 75,
            }
        ],
    )
    exit_row = store.record_order(
        order.run_id,
        leg_id=1,
        kind="exit_close_all",
        order={
            "position_ref": "pending-stop-position",
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "BUY",
            "qty": 75,
            "broker_order_id": "BRK-STOP",
            "status": "open",
        },
    )
    with state.run_state(order.run_id) as run:
        leg = run["legs"]["1"]
        leg["status"] = "open"
        leg["entry_status"] = "complete"
        leg["entry_avg"] = 100.0
        leg["exit_order_id"] = exit_row.id
        leg["exit_kind"] = "exit_close_all"
    assert store.request_run_stop(order.run_id, "manual") is True

    order_events._apply_update("BRK-STOP", _event("BRK-STOP", status=ended, avg=0))

    run = store.get_run(order.run_id)
    leg = state.get_run_state(order.run_id)["legs"]["1"]
    assert run.stopped_at is None
    assert run.stop_requested_reason == "manual"
    assert leg["position_ref"] == "pending-stop-position"
    assert leg["exit_order_id"] is None
    assert leg["exit_kind"] is None
    failures = [
        event
        for event in store.list_events(order.strategy_id)
        if event["kind"] == "run_stop_failed"
    ]
    assert len(failures) == 1
    assert "managed" in failures[0]["message"].lower()
    assert "retry" in failures[0]["message"].lower()
    assert not any(event["kind"] == "run_stopped" for event in store.list_events(order.strategy_id))


def test_cancelled_live_exit_preserves_prior_partial_fill_and_retries_only_remainder(order):
    _install_pending_entry(order)
    assert (
        engine.apply_fill(
            order.run_id,
            1,
            100.0,
            is_entry=True,
            filled_qty=75,
            order_row_id=order.order_id,
        )
        is False
    )
    exit_row = store.record_order(
        order.run_id,
        1,
        "exit_close_all",
        {
            "position_ref": None,
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "BUY",
            "qty": 75,
            "broker_order_id": "BRK-PARTIAL-LIVE",
            "status": "open",
        },
    )
    exit_row_id = exit_row.id
    with state.run_state(order.run_id) as run:
        leg = run["legs"]["1"]
        leg["exit_order_id"] = exit_row_id
        leg["exit_kind"] = "exit_close_all"
    assert store.request_run_stop(order.run_id, "manual") is True
    assert state.mark_stopping(order.run_id) is True

    order_events._apply_update(
        "BRK-PARTIAL-LIVE",
        _event("BRK-PARTIAL-LIVE", status="open", avg=105.0, filled=25),
    )
    order_events._apply_update(
        "BRK-PARTIAL-LIVE",
        _event(
            "BRK-PARTIAL-LIVE",
            status="cancelled",
            avg=0,
            filled=0,
            rejection="remainder cancelled",
        ),
    )

    durable = next(row for row in store.list_orders(order.run_id) if row["id"] == exit_row_id)
    assert durable["status"] == "cancelled"
    assert durable["filled_qty"] == 25
    assert durable["avg_fill_price"] == pytest.approx(105.0)
    leg = state.get_run_state(order.run_id)["legs"]["1"]
    assert leg["status"] == "open"
    assert leg["qty"] == 50
    assert leg["realized_pnl"] == pytest.approx((105.0 - 100.0) * 25 * -1)
    assert leg["exit_order_id"] is None
    assert leg["exit_kind"] is None

    retried = []

    def accept(**kwargs):
        retried.append(kwargs["order"])
        return DispatchResult(ok=True, broker_order_id="BRK-LIVE-RETRY", response={})

    with (
        patch.object(engine, "_api_key_for", return_value="test-key"),
        patch.object(engine.order_dispatch, "dispatch_order", side_effect=accept),
    ):
        result = engine.stop_run(order.run_id, USER, reason="manual")

    assert result["stop_pending"] is True
    assert retried[0]["quantity"] == "50"


def test_rejected_superseded_exit_reduces_exact_owner_and_retries_only_remainder(order):
    state.init_run_state(
        order.run_id,
        order.strategy_id,
        [
            {
                "leg_id": 1,
                "position": "S",
                "position_ref": "live-short",
                "symbol": "NIFTY28MAY2624000CE",
                "exchange": "NFO",
                "quantity": 10,
            }
        ],
    )
    exit_row = store.record_order(
        order.run_id,
        1,
        "exit_signal",
        {
            "position_ref": "old-long",
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "SELL",
            "qty": 10,
            "broker_order_id": "BRK-PARTIAL-OLD",
            "status": "open",
        },
    )
    exit_row_id = exit_row.id
    with state.run_state(order.run_id) as run:
        leg = run["legs"]["1"]
        leg.update(
            {
                "status": "open",
                "entry_status": "complete",
                "entry_avg": 120.0,
                "superseded": {
                    "position_ref": "old-long",
                    "entry_order_id": order.order_id,
                    "exit_order_id": exit_row_id,
                    "exit_claim_token": None,
                    "position": "B",
                    "entry_avg": 100.0,
                    "qty": 10,
                },
            }
        )

    order_events._apply_update(
        "BRK-PARTIAL-OLD",
        _event("BRK-PARTIAL-OLD", status="open", avg=110.0, filled=4),
    )
    order_events._apply_update(
        "BRK-PARTIAL-OLD",
        _event("BRK-PARTIAL-OLD", status="rejected", avg=0, filled=0),
    )

    durable = next(row for row in store.list_orders(order.run_id) if row["id"] == exit_row_id)
    assert durable["filled_qty"] == 4
    assert durable["avg_fill_price"] == pytest.approx(110.0)
    leg = state.get_run_state(order.run_id)["legs"]["1"]
    assert leg["status"] == "open"
    assert leg["superseded"]["qty"] == 6
    assert leg["superseded"]["exit_order_id"] is None
    assert leg["realized_pnl"] == pytest.approx((110.0 - 100.0) * 4)

    retry = state.claim_superseded_exit(order.run_id, 1, "B")
    assert retry["position_ref"] == "old-long"
    assert retry["quantity"] == 6


def test_terminal_partial_exit_without_price_still_reduces_the_exact_live_owner(order):
    _install_pending_entry(order)
    engine.apply_fill(
        order.run_id,
        1,
        100.0,
        is_entry=True,
        filled_qty=75,
        order_row_id=order.order_id,
    )
    exit_row = store.record_order(
        order.run_id,
        1,
        "exit_close_all",
        {
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "BUY",
            "qty": 75,
            "broker_order_id": "BRK-UNPRICED-EXIT",
            "status": "open",
        },
    )
    with state.run_state(order.run_id) as run:
        leg = run["legs"]["1"]
        leg["exit_order_id"] = exit_row.id
        leg["exit_kind"] = "exit_close_all"

    order_events._apply_update(
        "BRK-UNPRICED-EXIT",
        _event("BRK-UNPRICED-EXIT", status="cancelled", avg=0, filled=25),
    )

    leg = state.get_run_state(order.run_id)["legs"]["1"]
    assert leg["status"] == "open"
    assert leg["qty"] == 50
    assert leg["realized_pnl"] == 0.0
    assert leg["exit_order_id"] is None
    assert leg["exit_kind"] is None


def test_full_unpriced_exit_records_unverifiable_pnl_before_pending_stop_finalises(order):
    position_ref = "full-unpriced-short"
    assert store.set_strategy_status(order.strategy_id, "running", order.run_id)
    state.init_run_state(
        order.run_id,
        order.strategy_id,
        [
            {
                "leg_id": 1,
                "position": "S",
                "position_ref": position_ref,
                "symbol": "NIFTY28MAY2624000CE",
                "exchange": "NFO",
                "quantity": 10,
            }
        ],
    )
    exit_row = store.record_order(
        order.run_id,
        1,
        "exit_close_all",
        {
            "position_ref": position_ref,
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "BUY",
            "qty": 10,
            "broker_order_id": "BRK-FULL-UNPRICED",
            "status": "open",
        },
    )
    with state.run_state(order.run_id) as run:
        leg = run["legs"]["1"]
        leg["entry_order_id"] = order.order_id
        leg["entry_status"] = "complete"
        leg["entry_avg"] = 100.0
        leg["status"] = "open"
        leg["exit_order_id"] = exit_row.id
        leg["exit_kind"] = "exit_close_all"
    assert store.request_run_stop(order.run_id, "manual") is True
    assert state.mark_stopping(order.run_id) is True

    with patch.object(engine, "_unsubscribe_run"):
        order_events._apply_update(
            "BRK-FULL-UNPRICED",
            _event("BRK-FULL-UNPRICED", status="complete", avg=0, filled=10),
        )

    durable_run = store.get_run(order.run_id)
    assert durable_run.stopped_at is not None
    assert durable_run.pnl_realized == 0.0
    assert state.get_run_state(order.run_id) is None
    valuation_events = [
        event
        for event in store.list_events(order.strategy_id)
        if event["severity"] == "critical" and "BRK-FULL-UNPRICED" in event["message"]
    ]
    assert len(valuation_events) == 1
    message = valuation_events[0]["message"].lower()
    assert "p&l" in message and "unverifiable" in message
    assert "remaining exposure" not in message
    assert not any(
        event["kind"] == "run_stop_failed" for event in store.list_events(order.strategy_id)
    )


def test_full_dead_superseded_exit_emits_no_retry_or_pending_stop_failure(order):
    state.init_run_state(
        order.run_id,
        order.strategy_id,
        [
            {
                "leg_id": 1,
                "position": "S",
                "position_ref": "live-short",
                "symbol": "NIFTY28MAY2624000CE",
                "exchange": "NFO",
                "quantity": 10,
            }
        ],
    )
    exit_row = store.record_order(
        order.run_id,
        1,
        "exit_signal",
        {
            "position_ref": "old-long",
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "SELL",
            "qty": 10,
            "broker_order_id": "BRK-FULL-DEAD-OLD",
            "status": "open",
        },
    )
    with state.run_state(order.run_id) as run:
        leg = run["legs"]["1"]
        leg["status"] = "open"
        leg["entry_status"] = "complete"
        leg["entry_avg"] = 120.0
        leg["superseded"] = {
            "position_ref": "old-long",
            "entry_order_id": order.order_id,
            "exit_order_id": exit_row.id,
            "exit_claim_token": None,
            "position": "B",
            "entry_avg": 100.0,
            "qty": 10,
        }
    assert store.request_run_stop(order.run_id, "manual") is True

    order_events._apply_update(
        "BRK-FULL-DEAD-OLD",
        _event("BRK-FULL-DEAD-OLD", status="rejected", avg=110.0, filled=10),
    )

    leg = state.get_run_state(order.run_id)["legs"]["1"]
    assert leg["status"] == "open"
    assert leg["superseded"] is None
    kinds = [event["kind"] for event in store.list_events(order.strategy_id)]
    assert "flip_outgoing_exit_rejected" not in kinds
    assert "run_stop_failed" not in kinds


def test_state_gone_stranding_event_is_reserved_for_a_genuine_zero_fill(order):
    exit_row = store.record_order(
        order.run_id,
        1,
        "exit_close_all",
        {
            "position_ref": "closed-owner",
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "BUY",
            "qty": 10,
            "broker_order_id": "BRK-FULL-DEAD-NO-STATE",
            "status": "open",
        },
    )
    assert exit_row is not None
    exit_row_id = exit_row.id
    assert store.finish_run(order.run_id, "manual") is True
    assert state.get_run_state(order.run_id) is None

    order_events._apply_update(
        "BRK-FULL-DEAD-NO-STATE",
        _event("BRK-FULL-DEAD-NO-STATE", status="cancelled", avg=110.0, filled=10),
    )

    durable = next(row for row in store.list_orders(order.run_id) if row["id"] == exit_row_id)
    assert durable["status"] == "cancelled"
    assert durable["filled_qty"] == 10
    assert not any(
        event["kind"] == "run_stop_failed" for event in store.list_events(order.strategy_id)
    )

    zero_fill = store.record_order(
        order.run_id,
        1,
        "exit_close_all",
        {
            "position_ref": "closed-owner",
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "BUY",
            "qty": 10,
            "broker_order_id": "BRK-ZERO-DEAD-NO-STATE",
            "status": "open",
        },
    )
    assert zero_fill is not None

    fold_order_broker_frame = store.fold_order_broker_frame

    def fold_then_remove_session(*args, **kwargs):
        folded = fold_order_broker_frame(*args, **kwargs)
        # The fold commits and expires its input ORM row. Model the normal
        # worker cleanup boundary before the legacy stranded reporter runs.
        store.db_session.remove()
        return folded

    with patch.object(
        store,
        "fold_order_broker_frame",
        side_effect=fold_then_remove_session,
    ):
        order_events._apply_update(
            "BRK-ZERO-DEAD-NO-STATE",
            _event("BRK-ZERO-DEAD-NO-STATE", status="cancelled", avg=0, filled=0),
        )

    failures = [
        event
        for event in store.list_events(order.strategy_id)
        if event["kind"] == "run_stop_failed"
    ]
    assert len(failures) == 1
    assert "BRK-ZERO-DEAD-NO-STATE" in failures[0]["message"]
    assert "BUY of 10 NIFTY28MAY2624000CE" in failures[0]["message"]
    assert "did not happen" in failures[0]["message"].lower()


def test_priced_dead_exit_after_state_cleanup_reconciles_the_stopped_short_run(order):
    assert store.update_order(
        order.order_id,
        status="complete",
        avg_fill_price=100.0,
        filled_qty=10,
    )
    exit_row = store.record_order(
        order.run_id,
        1,
        "exit_close_all",
        {
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "BUY",
            "qty": 75,
            "broker_order_id": "BRK-DEAD-PNL-NO-STATE",
            "status": "open",
        },
    )
    assert exit_row is not None
    assert store.finish_run(order.run_id, "manual", pnl_realized=0.0) is True
    assert state.get_run_state(order.run_id) is None

    order_events._apply_update(
        "BRK-DEAD-PNL-NO-STATE",
        _event("BRK-DEAD-PNL-NO-STATE", status="cancelled", avg=101.0, filled=10),
    )

    durable_run = store.get_run(order.run_id)
    assert durable_run.stopped_at is not None
    assert float(durable_run.pnl_realized) == pytest.approx(-10.0)
    durable_exit = next(row for row in store.list_orders(order.run_id) if row["id"] == exit_row.id)
    assert durable_exit["status"] == "cancelled"
    assert durable_exit["filled_qty"] == 10


def _apply_two_updates_after_both_read(
    monkeypatch: pytest.MonkeyPatch, broker_order_id: str, event
) -> None:
    """Hold two update workers after their identical pre-terminal read."""
    _apply_updates_after_both_read(monkeypatch, broker_order_id, [event, event])


def _apply_updates_after_both_read(
    monkeypatch: pytest.MonkeyPatch, broker_order_id: str, events
) -> None:
    """Hold update workers after their identical pre-fold order lookup."""
    real_lookup = store.get_order_by_broker_id
    both_read = Barrier(len(events))

    def synchronized_lookup(candidate_order_id):
        row = real_lookup(candidate_order_id)
        both_read.wait(timeout=5)
        return row

    monkeypatch.setattr(store, "get_order_by_broker_id", synchronized_lookup)
    with ThreadPoolExecutor(max_workers=len(events)) as workers:
        futures = [
            workers.submit(order_events._apply_update, broker_order_id, event) for event in events
        ]
        for future in futures:
            future.result(timeout=10)


def test_concurrent_terminal_fills_have_exactly_one_state_winner(order, monkeypatch):
    with patch("services.strategy_module.engine.apply_fill") as apply_fill:
        _apply_two_updates_after_both_read(monkeypatch, "BRK-1", _event("BRK-1"))

    assert apply_fill.call_count == 1


def test_concurrent_working_and_terminal_frames_keep_terminal_status_and_largest_fill(
    order, monkeypatch
):
    events = [
        _event("BRK-1", status="open", avg=101.5, filled=50),
        _event("BRK-1", status="cancelled", avg=99.0, filled=25),
    ]
    with patch("services.strategy_module.engine.apply_fill") as apply_fill:
        _apply_updates_after_both_read(monkeypatch, "BRK-1", events)

    durable = next(row for row in store.list_orders(order.run_id) if row["broker_order_id"] == "BRK-1")
    applied = sum(call.kwargs.get("filled_qty") or 0 for call in apply_fill.call_args_list)
    assert durable["status"] == "cancelled"
    assert durable["filled_qty"] == 50
    assert durable["avg_fill_price"] == pytest.approx(101.5)
    assert applied == 50


def test_duplicate_outgoing_rejection_does_not_clear_an_unrelated_live_exit(order, monkeypatch):
    state.init_run_state(
        order.run_id,
        order.strategy_id,
        [
            {
                "leg_id": 1,
                "position": "S",
                "position_ref": "live-short",
                "symbol": "NIFTY28MAY2624000CE",
                "exchange": "NFO",
                "quantity": 75,
            }
        ],
    )
    live_exit = store.record_order(
        order.run_id,
        1,
        "exit_signal",
        {
            "position_ref": "live-short",
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "BUY",
            "qty": 75,
            "broker_order_id": "BRK-LIVE",
            "status": "open",
        },
    )
    live_exit_id = live_exit.id
    outgoing_exit = store.record_order(
        order.run_id,
        1,
        "exit_signal",
        {
            "position_ref": "outgoing-long",
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "SELL",
            "qty": 75,
            "broker_order_id": "BRK-OUTGOING",
            "status": "open",
        },
    )
    with state.run_state(order.run_id) as run:
        leg = run["legs"]["1"]
        leg["status"] = "open"
        leg["entry_status"] = "complete"
        leg["exit_order_id"] = live_exit_id
        leg["exit_kind"] = "exit_signal"
        leg["superseded"] = {
            "position_ref": "outgoing-long",
            "entry_order_id": order.order_id,
            "exit_order_id": outgoing_exit.id,
            "position": "B",
            "entry_avg": 100.0,
            "qty": 75,
        }

    _apply_two_updates_after_both_read(
        monkeypatch,
        "BRK-OUTGOING",
        _event("BRK-OUTGOING", status="rejected", avg=0),
    )

    leg = state.get_run_state(order.run_id)["legs"]["1"]
    assert leg["exit_order_id"] == live_exit_id
    assert leg["exit_kind"] == "exit_signal"


def test_legacy_rejection_releases_only_its_exact_live_exit_row(order):
    state.init_run_state(
        order.run_id,
        order.strategy_id,
        [
            {
                "leg_id": 1,
                "position": "S",
                "symbol": "NIFTY28MAY2624000CE",
                "exchange": "NFO",
                "quantity": 75,
            }
        ],
    )
    live_exit = store.record_order(
        order.run_id,
        1,
        "exit_signal",
        {
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "BUY",
            "qty": 75,
            "broker_order_id": "BRK-LIVE-LEGACY",
            "status": "open",
        },
    )
    live_exit_id = live_exit.id
    store.record_order(
        order.run_id,
        1,
        "exit_signal",
        {
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "BUY",
            "qty": 75,
            "broker_order_id": "BRK-OTHER-LEGACY",
            "status": "open",
        },
    )
    with state.run_state(order.run_id) as run:
        leg = run["legs"]["1"]
        leg["status"] = "open"
        leg["entry_status"] = "complete"
        leg["exit_order_id"] = live_exit_id
        leg["exit_kind"] = "exit_signal"

    order_events._apply_update(
        "BRK-OTHER-LEGACY", _event("BRK-OTHER-LEGACY", status="rejected", avg=0)
    )

    leg = state.get_run_state(order.run_id)["legs"]["1"]
    assert leg["exit_order_id"] == live_exit_id
    assert leg["exit_kind"] == "exit_signal"


def test_a_zero_fill_working_status_is_recorded_but_changes_no_exposure(order):
    with patch("services.strategy_module.engine.apply_fill") as apply_fill:
        order_events._apply_update(
            "BRK-1", _event("BRK-1", status="trigger pending", avg=0, filled=0)
        )

    assert store.list_orders(order.run_id)[0]["status"] == "open"
    assert apply_fill.call_count == 0


def test_a_positive_fill_with_no_price_is_recorded_and_managed_at_exact_quantity(order):
    # Quantity proves broker exposure even when risk valuation is unavailable.
    with patch("services.strategy_module.engine.apply_fill") as apply_fill:
        order_events._apply_update("BRK-1", _event("BRK-1", avg=0, filled=25))

    assert store.list_orders(order.run_id)[0]["status"] == "complete"
    apply_fill.assert_called_once_with(
        order.run_id,
        1,
        None,
        is_entry=True,
        filled_qty=25,
        order_row_id=order.order_id,
    )


def test_a_failure_applying_one_update_does_not_escape(order):
    # This runs on a shared pool. An exception escaping would kill the worker
    # and take later fills with it.
    with patch("services.strategy_module.engine.apply_fill", side_effect=RuntimeError("boom")):
        order_events._apply_update("BRK-1", _event("BRK-1", avg=101.5))


def test_the_callback_returns_without_doing_the_work_itself():
    # The bus dispatches every subscriber in turn, so this one is called for
    # every order the platform places and must not do anything slow inline.
    with patch.object(order_events._POOL, "submit") as submit:
        order_events._on_order_update(_event("BRK-1"))

    assert submit.call_count == 1


def test_an_event_without_an_order_id_is_ignored():
    with patch.object(order_events._POOL, "submit") as submit:
        order_events._on_order_update(_event(""))

    assert submit.call_count == 0


def test_subscribing_twice_registers_one_subscriber():
    order_events._started = False
    try:
        with patch("services.strategy_module.order_events.bus") as fake_bus:
            assert order_events.start() is True
            assert order_events.start() is False
            assert fake_bus.subscribe.call_count == 1
    finally:
        order_events._started = False


def test_a_fill_that_arrives_before_its_row_exists_is_not_lost(order):
    """The sandbox fills a MARKET order inside the dispatch call.

    engine._place_entries dispatches and only then records the order row, so
    the sandbox's "complete" event is published while no row carries that
    broker id yet. Keyed on broker id alone, the update reads as somebody
    else's order and is dropped, and the leg keeps entry_avg 0.0: no stop, no
    target, no mark to market. In sandbox that is not a race, it happens every
    time, so the risk engine manages nothing at all. A live broker whose fill
    beats the insert lands in the same place.

    The update has to survive until its row appears.
    """
    unrecorded = "BRK-LATE"

    # The fill arrives first. Nothing on the platform knows this order yet.
    with patch("services.strategy_module.engine.apply_fill") as apply_fill:
        order_events._apply_update(unrecorded, _event(unrecorded, avg=142.5))
    assert apply_fill.call_count == 0, "there is no row to apply it to yet"

    # The engine now records the row, exactly as _place_entries does.
    row = store.record_order(
        order.run_id,
        leg_id=2,
        kind="entry",
        order={
            "symbol": "NIFTY28MAY2624000PE",
            "exchange": "NFO",
            "action": "SELL",
            "qty": 75,
            "broker_order_id": unrecorded,
            "status": "open",
        },
    )
    assert row is not None

    with patch("services.strategy_module.engine.apply_fill") as apply_fill:
        order_events.replay_for(unrecorded)

    apply_fill.assert_called_once_with(
        order.run_id, 2, 142.5, is_entry=True, filled_qty=75, order_row_id=row.id
    )
    stored = [o for o in store.list_orders(order.run_id) if o["broker_order_id"] == unrecorded][0]
    assert stored["status"] == "complete"
    assert stored["avg_fill_price"] == 142.5


def test_replaying_an_id_nothing_buffered_is_harmless(order):
    with patch("services.strategy_module.engine.apply_fill") as apply_fill:
        order_events.replay_for("BRK-1")
    assert apply_fill.call_count == 0
