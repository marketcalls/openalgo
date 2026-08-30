"""Broker order updates driving strategy state.

This is the link that makes the module event-driven rather than polling: the
platform already publishes an OrderUpdateEvent for every asynchronous status
change, and the strategy engine needs the fill price out of it because that is
what every stop and target is measured from.

The pool is bypassed throughout: `_apply_update` is called directly so the
assertions are deterministic rather than racing a worker.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

# restx_api first: see the note in test_strategy_module_order_dispatch.py.
import restx_api  # noqa: F401
from database import strategy_module_db as store
from services.strategy_module import order_events

USER = "order_events_user"


def _event(orderid, status="complete", avg=100.0, filled=75, rejection=""):
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
            "BRK-1", _event("BRK-1", status="rejected", avg=0, rejection="Insufficient margin")
        )

    row = store.list_orders(order.run_id)[0]
    assert row["status"] == "rejected"
    assert row["reject_reason"] == "Insufficient margin"
    assert apply_fill.call_count == 0


def test_a_rejection_cannot_be_talked_back_into_a_fill(order):
    # A rejection is a fact. A late, out-of-order "complete" for the same
    # reference must not resurrect it into a position the account never held.
    order_events._apply_update("BRK-1", _event("BRK-1", status="rejected", avg=0))

    with patch("services.strategy_module.engine.apply_fill") as apply_fill:
        order_events._apply_update("BRK-1", _event("BRK-1", status="complete", avg=101.5))

    assert store.list_orders(order.run_id)[0]["status"] == "rejected"
    assert apply_fill.call_count == 0


def test_a_working_status_is_recorded_but_changes_nothing_the_engine_acts_on(order):
    with patch("services.strategy_module.engine.apply_fill") as apply_fill:
        order_events._apply_update("BRK-1", _event("BRK-1", status="trigger pending", avg=0))

    assert store.list_orders(order.run_id)[0]["status"] == "open"
    assert apply_fill.call_count == 0


def test_a_fill_with_no_price_is_recorded_but_not_applied(order):
    # A fill price is what a stop is measured from. Applying a leg with no
    # entry price would give it a stop derived from zero.
    with patch("services.strategy_module.engine.apply_fill") as apply_fill:
        order_events._apply_update("BRK-1", _event("BRK-1", avg=0))

    assert store.list_orders(order.run_id)[0]["status"] == "complete"
    assert apply_fill.call_count == 0


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
