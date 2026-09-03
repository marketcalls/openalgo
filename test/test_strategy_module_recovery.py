"""Boot recovery for strategy runs, and the checkpoint writer that feeds it.

The engine keeps a run in an in-process dict, so a crash takes every live run
with it while the positions are still at the broker. What is tested here is
what comes back: which facts are taken from the order rows, which from the
newest checkpoint, what a run with no checkpoint at all can still reconstruct,
and what happens to a run that cannot be rebuilt at all.

The checkpoint writer is driven by calling its pass function directly. Waiting
on the loop would test the sleep, not the write.
"""

import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from database import strategy_module_db as store
from services.strategy_module import checkpoint, order_events, recovery, state

USER = "recovery_test_user"
CE = "NIFTY28MAY2624000CE"
PE = "NIFTY28MAY2624000PE"


def _leg(leg_id=1, position="S", sl_pts=20):
    return {
        "id": leg_id,
        "segment": "options",
        "expiry": "weekly",
        "lots": 1,
        "position": position,
        "option_type": "CE",
        "strike_mode": "atm",
        "atm_offset": "ATM",
        "sl_pts": sl_pts,
        "trail": {"x": 0, "y": 0},
    }


def _config(name="Recovery test", legs=None, **overrides):
    config = {
        "name": name,
        "underlying": "NIFTY",
        "underlying_exchange": "NSE_INDEX",
        "universe_tab": "weekly_monthly",
        "product": "NRML",
        "legs": legs if legs is not None else [_leg()],
    }
    config.update(overrides)
    return config


@pytest.fixture(autouse=True)
def clean_slate():
    store.init_db()

    def purge():
        for run_id in state.active_run_ids():
            state.clear_run_state(run_id)
        for row in store.list_strategies(USER):
            # Force to stopped first: delete refuses while a strategy is running.
            store.set_strategy_status(row["id"], "stopped", None)
            store.delete_strategy(row["id"], USER)
        # recover_all() is global by design, so an open run another suite left
        # behind after a failure would be recovered by these tests and would
        # show up in their results. Close them before starting.
        for run in store.list_open_runs():
            store.finish_run(run.id, "error")
        store.clear_strategy_module_cache()

    purge()
    yield
    purge()


# ---------------------------------------------------------------------------
# Fixture builders: the store is real, so these write actual rows.
# ---------------------------------------------------------------------------


def _strategy(name="Recovery test", legs=None, **overrides):
    created, error = store.create_strategy(USER, _config(name, legs, **overrides))
    assert error is None, error
    return created["id"]


def _run(strategy_id):
    run = store.create_run(strategy_id, "sandbox", "sandbox")
    assert run is not None
    run_id = run.id
    store.set_strategy_status(strategy_id, "running", run_id)
    return run_id


def _order(
    run_id,
    leg_id=1,
    kind="entry",
    action="SELL",
    symbol=CE,
    qty=75,
    status="complete",
    avg=None,
    filled_qty=None,
    position_ref=None,
    broker_order_id=None,
):
    row = store.record_order(
        run_id,
        leg_id,
        kind,
        {
            "symbol": symbol,
            "exchange": "NFO",
            "action": action,
            "qty": qty,
            "pricetype": "MARKET",
            "status": "open",
            "position_ref": position_ref,
        },
    )
    assert row is not None
    store.update_order(
        row.id,
        status=status,
        broker_order_id=broker_order_id,
        avg_fill_price=avg,
        filled_qty=filled_qty,
    )
    return row.id


def _event(order_id, status="complete", avg=100.0, filled=None, rejection=""):
    return SimpleNamespace(
        orderid=order_id,
        order_status=status,
        average_price=avg,
        filled_quantity=filled,
        rejection_reason=rejection,
    )


def _cp_leg(leg_id=1, **overrides):
    """One leg exactly as state.snapshot_for_checkpoint would have stored it."""
    leg = {
        "leg_id": leg_id,
        "position": "S",
        "symbol": CE,
        "exchange": "NFO",
        "lots": 1,
        "qty": 75,
        "entry_order_id": None,
        "entry_status": "complete",
        "entry_avg": 100.0,
        "exit_order_id": None,
        "exit_kind": None,
        "exit_avg": None,
        "ltp": 95.0,
        "mtm": 375.0,
        "realized_pnl": 0.0,
        "status": "open",
        "tick_source": "ws",
        "sl_pts": 20,
        "target_pts": None,
        "trail_x": 0,
        "trail_y": 0,
        "effective_sl": None,
        "effective_target": None,
        "trail_active": False,
        "highest_price": None,
        "lowest_price": None,
    }
    leg.update(overrides)
    return leg


def _checkpoint(run_id, leg_state, **run_level):
    snapshot = {
        "pnl_realized": 0.0,
        "pnl_unrealized": 0.0,
        "pnl_total": 0.0,
        "pnl_peak": 0.0,
        "pnl_trough": 0.0,
        "lock_floor": None,
        "trail_to_entry_active": False,
        "leg_state": leg_state,
    }
    snapshot.update(run_level)
    assert store.write_checkpoint(run_id, snapshot) is True


# ---------------------------------------------------------------------------
# Orders against checkpoint
# ---------------------------------------------------------------------------


def test_a_run_takes_fill_facts_from_its_orders_and_risk_state_from_its_checkpoint():
    # The checkpoint below is deliberately wrong about everything the order
    # rows know: a stale symbol, the wrong quantity, the wrong entry price and
    # the wrong side. Those are the facts the orders own.
    sid = _strategy()
    run_id = _run(sid)
    _order(run_id, 1, "entry", action="SELL", status="complete", avg=100.0)
    _checkpoint(
        run_id,
        {
            "1": _cp_leg(
                symbol="A-DIFFERENT-STRIKE",
                qty=1,
                entry_avg=999.0,
                position="B",
                ltp=95.0,
                effective_sl=120.0,
                effective_target=60.0,
                lowest_price=92.0,
                trail_active=True,
            )
        },
        pnl_peak=375.0,
        pnl_trough=-150.0,
        lock_floor=200.0,
        trail_to_entry_active=True,
    )

    resumed = recovery.recover_all()

    assert resumed[run_id] == {(CE, "NFO")}
    live = state.get_run_state(run_id)
    leg = live["legs"]["1"]

    # Identity and fill facts: the order rows.
    assert leg["symbol"] == CE
    assert leg["exchange"] == "NFO"
    assert leg["qty"] == 75
    assert leg["position"] == "S"
    assert leg["entry_avg"] == 100.0
    assert leg["entry_status"] == "complete"
    assert leg["status"] == "open"

    # Volatile risk state: the checkpoint, because nothing else records it.
    assert leg["ltp"] == 95.0
    assert leg["effective_sl"] == 120.0
    assert leg["effective_target"] == 60.0
    assert leg["lowest_price"] == 92.0
    assert leg["trail_active"] is True

    # Run aggregates: the checkpoint too.
    assert live["pnl_peak"] == 375.0
    assert live["pnl_trough"] == -150.0
    assert live["lock_floor"] == 200.0
    assert live["lock_armed"] is True
    assert live["trail_to_entry_active"] is True


def test_a_run_with_no_checkpoint_recovers_from_its_orders_alone():
    # A run that died within seconds of starting has no snapshot at all. The
    # book is still fully knowable; only the risk levels have to be re-derived,
    # which the next tick does from the configured points.
    sid = _strategy()
    run_id = _run(sid)
    _order(run_id, 1, "entry", action="SELL", status="complete", avg=100.0)
    assert store.latest_checkpoint(run_id) is None

    resumed = recovery.recover_all()

    assert resumed[run_id] == {(CE, "NFO")}
    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["status"] == "open"
    assert leg["position"] == "S"
    assert leg["entry_avg"] == 100.0
    # Nothing volatile survived, and nothing pretends it did.
    assert leg["ltp"] is None
    assert leg["effective_sl"] is None
    assert leg["highest_price"] is None
    assert leg["lowest_price"] is None
    # The configured stop is back from the strategy, so the level re-derives.
    assert leg["sl_pts"] == 20


def test_restart_binds_an_accepted_ack_event_to_its_exact_pending_entry_row():
    sid = _strategy()
    run_id = _run(sid)
    row_id = _order(
        run_id,
        1,
        "entry",
        status="pending",
        position_ref="ack-restart-owner",
    )
    store.record_event(
        sid,
        USER,
        "order_ack_unrecorded",
        "Accepted acknowledgement is pending automatic reconciliation",
        run_id=run_id,
        leg_id=1,
        severity="critical",
        payload={
            "version": 1,
            "order_id": row_id,
            "run_id": run_id,
            "leg_id": 1,
            "broker_order_id": "ACK-ENTRY-RESTART",
            "accepted": True,
            "status": "open",
            "reject_reason": None,
        },
    )

    recovered = recovery.recover_run(run_id)

    assert recovered.ok is True
    durable = store.get_order(row_id)
    assert durable.broker_order_id == "ACK-ENTRY-RESTART"
    assert durable.status == "open"
    live = state.get_run_state(run_id)
    assert live is not None
    assert live["legs"]["1"]["entry_order_id"] == row_id
    assert live["legs"]["1"]["entry_status"] == "open"
    assert store.get_run(run_id).stopped_at is None


def test_legacy_unstructured_ack_event_keeps_possible_exposure_open_and_reserved():
    sid = _strategy()
    run_id = _run(sid)
    _order(run_id, 1, "entry", status="pending")
    store.record_event(
        sid,
        USER,
        "order_ack_unrecorded",
        "Legacy accepted broker acknowledgement without structured linkage",
        run_id=run_id,
        leg_id=1,
        severity="critical",
    )

    recovered = recovery.recover_run(run_id)

    assert recovered.ok is False
    assert recovered.finalised is False
    assert "could not be linked" in str(recovered.error).lower()
    assert store.get_run(run_id).stopped_at is None
    assert store.get_strategy(sid, USER).current_run_id == run_id
    assert state.get_run_state(run_id) is None


def test_ack_witness_read_failure_cannot_be_misread_as_no_ambiguous_exposure():
    sid = _strategy()
    run_id = _run(sid)
    _order(run_id, 1, "entry", status="pending")

    with patch.object(store, "list_order_ack_events", return_value=None):
        recovered = recovery.recover_run(run_id)

    assert recovered.ok is False
    assert recovered.finalised is False
    assert store.get_run(run_id).stopped_at is None
    assert store.get_strategy(sid, USER).current_run_id == run_id
    assert state.get_run_state(run_id) is None


def test_the_checkpoint_may_witness_a_fill_the_order_row_has_not_caught_up_with():
    # The checkpoint is written from the same fill engine.apply_fill applies to
    # live state, so it can see a fill before the row is updated. That upgrade
    # is the one direction it is allowed to move a fill fact.
    sid = _strategy()
    run_id = _run(sid)
    _order(run_id, 1, "entry", action="SELL", status="open", avg=None)
    _checkpoint(run_id, {"1": _cp_leg(entry_status="complete", entry_avg=100.0, status="open")})

    recovery.recover_all()

    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["status"] == "open"
    assert leg["entry_avg"] == 100.0


def test_a_rejected_entry_is_never_upgraded_by_a_checkpoint():
    # The other direction. An entry the broker refused is a leg holding
    # nothing, and no snapshot may say otherwise. Leg 2 filled, so the run
    # itself stays live and the rejected leg can be inspected.
    sid = _strategy(legs=[_leg(1, "S"), _leg(2, "S")])
    run_id = _run(sid)
    _order(run_id, 1, "entry", action="SELL", symbol=CE, status="rejected")
    _order(run_id, 2, "entry", action="SELL", symbol=PE, status="complete", avg=50.0)
    _checkpoint(
        run_id,
        {
            "1": _cp_leg(1, symbol=CE, entry_status="complete", entry_avg=100.0, status="open"),
            "2": _cp_leg(2, symbol=PE, entry_avg=50.0),
        },
    )

    resumed = recovery.recover_all()

    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["status"] == "rejected"
    assert leg["entry_avg"] == 0.0
    # It holds nothing, so it is not worth a subscription either.
    assert resumed[run_id] == {(PE, "NFO")}


@pytest.mark.parametrize("ended", ["rejected", "cancelled"])
def test_recovery_treats_terminal_partial_entry_fields_as_actual_exposure(ended):
    sid = _strategy()
    run_id = _run(sid)
    _order(
        run_id,
        1,
        "entry",
        action="SELL",
        status=ended,
        avg=101.5,
        filled_qty=25,
        position_ref="partial-entry",
    )
    assert store.request_run_stop(run_id, "scheduler") is True

    recovered = recovery.recover_run(run_id)

    assert recovered.ok is True
    live = state.get_run_state(run_id)
    assert live is not None
    assert live["stopping"] is True
    leg = live["legs"]["1"]
    assert leg["status"] == "open"
    assert leg["entry_status"] == "complete"
    assert leg["entry_avg"] == pytest.approx(101.5)
    assert leg["qty"] == 25
    assert leg["position_ref"] == "partial-entry"
    assert store.get_run(run_id).stop_requested_reason == "scheduler"


@pytest.mark.parametrize("ended", ["rejected", "cancelled"])
def test_recovery_keeps_terminal_partial_entry_quantity_when_price_is_unavailable(ended):
    sid = _strategy()
    run_id = _run(sid)
    _order(
        run_id,
        1,
        "entry",
        action="SELL",
        status=ended,
        avg=0,
        filled_qty=25,
        position_ref="unpriced-partial-entry",
    )
    assert store.request_run_stop(run_id, "scheduler") is True

    recovered = recovery.recover_run(run_id)

    assert recovered.ok is True
    assert recovered.finalised is False
    assert store.get_run(run_id).stopped_at is None
    live = state.get_run_state(run_id)
    assert live is not None
    assert live["stopping"] is True
    leg = live["legs"]["1"]
    assert leg["status"] == "open"
    assert leg["entry_status"] == "complete"
    assert leg["entry_avg"] == 0.0
    assert leg["qty"] == 25
    assert leg["position_ref"] == "unpriced-partial-entry"


def test_recovery_finalizes_zero_fill_pending_stop_with_persisted_reason_and_stop_event():
    sid = _strategy()
    run_id = _run(sid)
    _order(run_id, 1, "entry", action="SELL", status="rejected", avg=0, filled_qty=0)
    assert store.request_run_stop(run_id, "scheduler") is True

    recovered = recovery.recover_run(run_id)

    assert recovered.finalised is True
    durable = store.get_run(run_id)
    assert durable.stopped_at is not None
    assert durable.stop_reason == "scheduler"
    matching = [event for event in store.list_events(sid) if event["run_id"] == run_id]
    assert [event["kind"] for event in matching].count("run_stopped") == 1
    assert "scheduler" in matching[-1]["message"]


def test_an_entry_still_working_holds_nothing_yet_but_is_still_watched():
    sid = _strategy()
    run_id = _run(sid)
    _order(run_id, 1, "entry", action="SELL", status="open")

    resumed = recovery.recover_all()

    leg = state.get_run_state(run_id)["legs"]["1"]
    # Not open: a rule must not be able to exit a position that does not exist,
    # and an unfilled leg must not be marked from an entry price of zero.
    assert leg["status"] == "configured"
    assert leg["entry_avg"] == 0.0
    # Still subscribed, so the fill is priced the moment it lands.
    assert resumed[run_id] == {(CE, "NFO")}


# ---------------------------------------------------------------------------
# Exits
# ---------------------------------------------------------------------------


def test_a_leg_whose_exit_already_filled_comes_back_closed_and_is_not_resubscribed():
    sid = _strategy(legs=[_leg(1, "S"), _leg(2, "S")])
    run_id = _run(sid)
    _order(run_id, 1, "entry", action="SELL", symbol=CE, status="complete", avg=100.0)
    _order(run_id, 1, "exit_sl", action="BUY", symbol=CE, status="complete", avg=80.0)
    _order(run_id, 2, "entry", action="SELL", symbol=PE, status="complete", avg=50.0)

    resumed = recovery.recover_all()

    legs = state.get_run_state(run_id)["legs"]
    assert legs["1"]["status"] == "closed"
    assert legs["1"]["exit_avg"] == 80.0
    assert legs["1"]["exit_kind"] == "exit_sl"
    # Short covered 20 points lower: a profit, derived from the two fills
    # because the run never checkpointed after the exit.
    assert legs["1"]["realized_pnl"] == pytest.approx((80.0 - 100.0) * 75 * -1)
    assert legs["2"]["status"] == "open"
    # Only the leg still held is worth a subscription.
    assert resumed[run_id] == {(PE, "NFO")}


def test_a_rejected_exit_leaves_the_leg_open_and_the_exit_retryable():
    # If a failed exit came back looking like one in flight, the engine's
    # duplicate-exit guard would refuse to try again and strand the position.
    sid = _strategy()
    run_id = _run(sid)
    _order(run_id, 1, "entry", action="SELL", status="complete", avg=100.0)
    _order(run_id, 1, "exit_sl", action="BUY", status="rejected")

    recovery.recover_all()

    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["status"] == "open"
    assert leg["exit_order_id"] is None
    assert leg["exit_kind"] is None


@pytest.mark.parametrize(
    ("exit_avg", "expected_realized"),
    [(80.0, 500.0), (0.0, 0.0)],
)
def test_recovery_reduces_single_owner_by_terminal_partial_exit_quantity(
    exit_avg, expected_realized
):
    sid = _strategy()
    run_id = _run(sid)
    _order(
        run_id,
        1,
        "entry",
        action="SELL",
        qty=75,
        status="complete",
        avg=100.0,
        filled_qty=75,
        position_ref="single-owner",
    )
    _order(
        run_id,
        1,
        "exit_close_all",
        action="BUY",
        qty=75,
        status="cancelled",
        avg=exit_avg,
        filled_qty=25,
        position_ref="single-owner",
    )
    assert store.request_run_stop(run_id, "manual") is True

    recovered = recovery.recover_run(run_id)

    assert recovered.ok is True
    assert recovered.finalised is False
    assert store.get_run(run_id).stopped_at is None
    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["status"] == "open"
    assert leg["entry_status"] == "complete"
    assert leg["qty"] == 50
    assert leg["position_ref"] == "single-owner"
    assert leg["exit_order_id"] is None
    assert leg["exit_kind"] is None
    assert leg["realized_pnl"] == pytest.approx(expected_realized)


def test_recovery_preserves_pending_stop_and_exact_rejected_exit_owner():
    sid = _strategy()
    run_id = _run(sid)
    _order(
        run_id,
        1,
        "entry",
        action="SELL",
        status="complete",
        avg=100.0,
        position_ref="recover-pending-position",
    )
    _order(
        run_id,
        1,
        "exit_close_all",
        action="BUY",
        status="rejected",
        position_ref="recover-pending-position",
    )
    assert store.request_run_stop(run_id, "manual") is True

    recovered = recovery.recover_run(run_id)

    assert recovered.ok is True
    persisted = store.get_run(run_id)
    assert persisted.stop_requested_reason == "manual"
    assert persisted.stop_requested_at is not None
    live = state.get_run_state(run_id)
    assert live["signal_entry_claims"] == {}
    leg = live["legs"]["1"]
    assert leg["position_ref"] == "recover-pending-position"
    assert leg["exit_order_id"] is None
    assert leg["exit_claim_token"] is None
    assert leg["exit_kind"] is None


def test_recovery_snapshots_run_facts_before_session_cleanup():
    sid = _strategy()
    run_id = _run(sid)
    _order(
        run_id,
        1,
        "entry",
        action="SELL",
        status="complete",
        avg=100.0,
        filled_qty=75,
        position_ref="detached-recovery-position",
    )
    assert store.request_run_stop(run_id, "manual") is True

    list_orders = store.list_orders

    def list_orders_then_remove_session(target_run_id):
        rows = list_orders(target_run_id)
        # Model a sibling store/event call that commits and clears the scoped
        # session while recovery still owns the plain run facts it read first.
        store.db_session.expire_all()
        store.db_session.remove()
        return rows

    with patch.object(store, "list_orders", side_effect=list_orders_then_remove_session):
        recovered = recovery.recover_run(run_id)

    assert recovered.ok is True
    assert recovered.finalised is False
    assert recovered.strategy_id == sid
    assert state.get_run_state(run_id)["stopping"] is True
    durable = store.get_run(run_id)
    assert durable.stopped_at is None
    assert durable.stop_requested_reason == "manual"


def test_an_exit_in_flight_comes_back_marked_so_it_is_not_sent_twice():
    sid = _strategy()
    run_id = _run(sid)
    _order(run_id, 1, "entry", action="SELL", status="complete", avg=100.0)
    exit_id = _order(run_id, 1, "exit_sl", action="BUY", status="trigger pending")

    recovery.recover_all()

    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["status"] == "open"
    assert leg["exit_order_id"] == exit_id
    assert leg["exit_kind"] == "exit_sl"


@pytest.mark.parametrize("outgoing_status", ["open", "rejected"])
def test_recovery_restores_live_and_superseded_flip_positions(outgoing_status):
    sid = _strategy()
    run_id = _run(sid)
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
    new_entry = _order(
        run_id,
        kind="entry",
        action="SELL",
        status="complete",
        avg=102.0,
        position_ref="new-position",
    )

    recovered = recovery.recover_run(run_id)

    assert recovered.ok is True
    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["position_ref"] == "new-position"
    assert leg["position"] == "S"
    assert leg["entry_order_id"] == new_entry
    assert leg["entry_avg"] == pytest.approx(102.0)
    assert leg["qty"] == 75
    outgoing = leg["superseded"]
    assert outgoing["position_ref"] == "old-position"
    assert outgoing["position"] == "B"
    assert outgoing["entry_order_id"] == old_entry
    assert outgoing["entry_avg"] == pytest.approx(100.0)
    assert outgoing["qty"] == 75
    assert outgoing["exit_order_id"] == (old_exit if outgoing_status == "open" else None)
    assert outgoing["exit_kind"] == ("exit_signal" if outgoing_status == "open" else None)


def test_recovery_folds_every_exit_attempt_before_arming_the_newest_retry():
    sid = _strategy()
    run_id = _run(sid)
    _order(
        run_id,
        kind="entry",
        action="BUY",
        qty=75,
        status="complete",
        avg=100.0,
        filled_qty=75,
        position_ref="old-position",
    )
    _order(
        run_id,
        kind="exit_signal",
        action="SELL",
        qty=75,
        status="cancelled",
        avg=120.0,
        filled_qty=25,
        position_ref="old-position",
    )
    new_entry = _order(
        run_id,
        kind="entry",
        action="SELL",
        qty=75,
        status="complete",
        avg=102.0,
        position_ref="new-position",
    )
    retry = _order(
        run_id,
        kind="exit_signal",
        action="SELL",
        qty=50,
        status="open",
        position_ref="old-position",
    )

    recovered = recovery.recover_run(run_id)

    assert recovered.ok is True
    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["position_ref"] == "new-position"
    assert leg["entry_order_id"] == new_entry
    assert leg["realized_pnl"] == pytest.approx(500.0)
    assert leg["superseded"]["qty"] == 50
    assert leg["superseded"]["exit_order_id"] == retry
    assert leg["superseded"]["exit_kind"] == "exit_signal"


def test_recovery_rejects_multiple_working_exits_before_any_cumulative_fill_fold():
    sid = _strategy()
    run_id = _run(sid)
    _order(
        run_id,
        kind="entry",
        action="BUY",
        qty=75,
        status="complete",
        avg=100.0,
        position_ref="one-owner",
    )
    _order(
        run_id,
        kind="exit_signal",
        action="SELL",
        qty=75,
        status="open",
        avg=110.0,
        filled_qty=25,
        position_ref="one-owner",
    )
    _order(
        run_id,
        kind="exit_signal",
        action="SELL",
        qty=50,
        status="open",
        avg=111.0,
        filled_qty=50,
        position_ref="one-owner",
    )

    recovered = recovery.recover_run(run_id)

    assert recovered.ok is False
    assert recovered.finalised is False
    assert "multiple working exits" in (recovered.error or "").lower()
    assert store.get_run(run_id).stopped_at is None
    assert store.get_strategy(sid, USER).current_run_id == run_id
    assert state.get_run_state(run_id) is None
    event = next(event for event in store.list_events(sid) if event["kind"] == "recovery_failed")
    assert event["severity"] == "critical"
    assert "manual" in event["message"].lower()


@pytest.mark.parametrize("with_replacement", [False, True])
def test_recovered_working_partial_is_applied_once_when_its_terminal_cumulative_arrives(
    with_replacement,
):
    sid = _strategy()
    run_id = _run(sid)
    _order(
        run_id,
        kind="entry",
        action="BUY",
        qty=75,
        status="complete",
        avg=100.0,
        position_ref="working-owner",
    )
    active_exit = _order(
        run_id,
        kind="exit_signal",
        action="SELL",
        qty=75,
        status="open",
        avg=110.0,
        filled_qty=25,
        position_ref="working-owner",
        broker_order_id="WORKING-EXIT",
    )
    replacement_entry = None
    if with_replacement:
        replacement_entry = _order(
            run_id,
            kind="entry",
            action="SELL",
            qty=75,
            status="complete",
            avg=102.0,
            position_ref="replacement-owner",
        )

    assert recovery.recover_run(run_id).ok is True
    before = state.get_run_state(run_id)["legs"]["1"]
    owner_before = before["superseded"] if with_replacement else before
    assert owner_before["qty"] == 50
    assert owner_before["exit_order_id"] == active_exit
    assert before["realized_pnl"] == pytest.approx(250.0)

    order_events._apply_update(
        "WORKING-EXIT",
        _event("WORKING-EXIT", status="cancelled", avg=110.0, filled=50),
    )

    assert store.get_run(run_id).stopped_at is None
    after = state.get_run_state(run_id)["legs"]["1"]
    owner_after = after["superseded"] if with_replacement else after
    assert owner_after is not None
    assert owner_after["position_ref"] == "working-owner"
    assert owner_after["qty"] == 25
    assert owner_after["exit_order_id"] is None
    assert owner_after["exit_kind"] is None
    assert after["realized_pnl"] == pytest.approx(500.0)
    if with_replacement:
        assert after["position_ref"] == "replacement-owner"
        assert after["entry_order_id"] == replacement_entry


def test_recovery_applies_checkpoint_fields_only_to_the_matching_position_reference():
    sid = _strategy()
    run_id = _run(sid)
    _order(
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
        status="open",
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
    _checkpoint(
        run_id,
        {
            "1": _cp_leg(
                position="S",
                position_ref="new-position",
                entry_avg=999.0,
                qty=1,
                ltp=91.0,
                effective_sl=122.0,
                realized_pnl=321.0,
                superseded={
                    "position_ref": "old-position",
                    "position": "B",
                    "entry_order_id": -1,
                    "entry_avg": 777.0,
                    "qty": 1,
                    "exit_order_id": old_exit,
                    "exit_claim_token": "stale-claim",
                    "exit_kind": "exit_signal",
                },
            )
        },
    )

    assert recovery.recover_run(run_id).ok is True

    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["entry_avg"] == pytest.approx(102.0)
    assert leg["qty"] == 75
    assert leg["ltp"] == pytest.approx(91.0)
    assert leg["effective_sl"] == pytest.approx(122.0)
    # Identity-matched checkpoint risk fields overlay, but a stale cumulative
    # P&L cannot override complete durable coverage. Neither owner has a
    # settled exit, so the exact realized result is break-even.
    assert leg["realized_pnl"] == pytest.approx(0.0)
    assert leg["superseded"]["entry_avg"] == pytest.approx(100.0)
    assert leg["superseded"]["qty"] == 75
    assert leg["superseded"]["exit_order_id"] == old_exit
    assert leg["superseded"]["exit_claim_token"] is None


def test_recovery_refuses_to_drop_a_third_held_position_reference():
    sid = _strategy()
    run_id = _run(sid)
    _order(
        run_id,
        kind="entry",
        action="BUY",
        status="complete",
        avg=100.0,
        position_ref="one",
    )
    _order(
        run_id,
        kind="entry",
        action="SELL",
        status="complete",
        avg=101.0,
        position_ref="two",
    )
    _order(
        run_id,
        kind="entry",
        action="BUY",
        status="complete",
        avg=102.0,
        position_ref="three",
    )

    recovered = recovery.recover_run(run_id)

    assert recovered.ok is False
    assert recovered.finalised is False
    assert "more than two" in (recovered.error or "").lower()
    assert store.get_run(run_id).stopped_at is None
    strategy = store.get_strategy(sid, USER)
    assert strategy.status == "running"
    assert strategy.current_run_id == run_id
    assert state.get_run_state(run_id) is None
    failures = [event for event in store.list_events(sid) if event["kind"] == "recovery_failed"]
    assert failures
    assert failures[0]["severity"] == "critical"
    assert "manual" in failures[0]["message"].lower()


def test_mixed_legacy_and_referenced_positions_recover_without_cross_pairing():
    sid = _strategy()
    run_id = _run(sid)
    old_entry = _order(
        run_id,
        kind="entry",
        action="BUY",
        status="complete",
        avg=100.0,
        position_ref=None,
    )
    new_entry = _order(
        run_id,
        kind="entry",
        action="SELL",
        status="complete",
        avg=102.0,
        position_ref="new-position",
    )
    _order(
        run_id,
        kind="exit_signal",
        action="SELL",
        status="rejected",
        position_ref=None,
    )

    assert recovery.recover_run(run_id).ok is True

    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["position_ref"] == "new-position"
    assert leg["entry_order_id"] == new_entry
    assert leg["superseded"]["position_ref"] is None
    assert leg["superseded"]["entry_order_id"] == old_entry
    assert leg["superseded"]["position"] == "B"


def test_mixed_referenced_history_refuses_multiple_legacy_entry_incarnations():
    sid = _strategy()
    run_id = _run(sid)
    _order(
        run_id,
        kind="entry",
        action="BUY",
        qty=75,
        status="complete",
        avg=100.0,
        position_ref=None,
    )
    _order(
        run_id,
        kind="exit_signal",
        action="SELL",
        qty=75,
        status="complete",
        avg=110.0,
        position_ref=None,
    )
    _order(
        run_id,
        kind="entry",
        action="SELL",
        qty=75,
        status="complete",
        avg=102.0,
        position_ref=None,
    )
    _order(
        run_id,
        kind="entry",
        action="BUY",
        qty=75,
        status="complete",
        avg=104.0,
        position_ref="referenced-owner",
    )

    recovered = recovery.recover_run(run_id)

    assert recovered.ok is False
    assert recovered.finalised is False
    assert "multiple legacy entry" in (recovered.error or "").lower()
    assert store.get_run(run_id).stopped_at is None
    assert store.get_strategy(sid, USER).current_run_id == run_id
    assert state.get_run_state(run_id) is None


def test_mixed_legacy_exit_without_a_legacy_entry_remains_managed_for_reconciliation():
    sid = _strategy()
    run_id = _run(sid)
    _order(
        run_id,
        kind="entry",
        action="BUY",
        status="complete",
        avg=100.0,
        position_ref="referenced-position",
    )
    _order(
        run_id,
        kind="exit_signal",
        action="SELL",
        status="rejected",
        position_ref=None,
    )

    recovered = recovery.recover_run(run_id)

    assert recovered.ok is False
    assert recovered.finalised is False
    assert "ambiguous" in (recovered.error or "").lower()
    assert store.get_run(run_id).stopped_at is None
    assert store.get_strategy(sid, USER).current_run_id == run_id
    assert state.get_run_state(run_id) is None


def test_overlapping_referenced_positions_on_different_instruments_are_not_cross_managed():
    sid = _strategy()
    run_id = _run(sid)
    _order(
        run_id,
        kind="entry",
        action="BUY",
        symbol=CE,
        status="complete",
        avg=100.0,
        position_ref="old-position",
    )
    _order(
        run_id,
        kind="entry",
        action="SELL",
        symbol=PE,
        status="complete",
        avg=102.0,
        position_ref="new-position",
    )

    recovered = recovery.recover_run(run_id)

    assert recovered.ok is False
    assert recovered.finalised is False
    assert "different instruments" in (recovered.error or "").lower()
    assert store.get_run(run_id).stopped_at is None
    assert state.get_run_state(run_id) is None


def test_rejected_replacement_entry_restores_the_outgoing_owner_as_live_with_risk_config():
    sid = _strategy()
    run_id = _run(sid)
    old_entry = _order(
        run_id,
        kind="entry",
        action="BUY",
        status="complete",
        avg=100.0,
        position_ref="old-position",
    )
    _order(
        run_id,
        kind="exit_signal",
        action="SELL",
        status="rejected",
        position_ref="old-position",
    )
    _order(
        run_id,
        kind="entry",
        action="SELL",
        status="rejected",
        filled_qty=0,
        position_ref="new-position",
    )
    _checkpoint(
        run_id,
        {
            "1": _cp_leg(
                position="S",
                position_ref="new-position",
                status="rejected",
                superseded={
                    "position_ref": "old-position",
                    "position": "B",
                    "entry_order_id": old_entry,
                    "entry_avg": 100.0,
                    "qty": 75,
                    "exit_order_id": None,
                    "exit_claim_token": None,
                },
            )
        },
    )

    assert recovery.recover_run(run_id).ok is True

    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["position_ref"] == "old-position"
    assert leg["entry_order_id"] == old_entry
    assert leg["position"] == "B"
    assert leg["status"] == "open"
    assert leg["superseded"] is None
    assert leg["sl_pts"] == pytest.approx(20.0)


def test_post_recovery_fill_settles_only_the_exact_superseded_owner():
    sid = _strategy()
    run_id = _run(sid)
    _order(
        run_id,
        kind="entry",
        action="BUY",
        qty=25,
        status="complete",
        avg=100.0,
        position_ref="old-position",
    )
    old_exit = _order(
        run_id,
        kind="exit_signal",
        action="SELL",
        qty=25,
        status="open",
        position_ref="old-position",
        broker_order_id="OLD-EXIT",
    )
    new_entry = _order(
        run_id,
        kind="entry",
        action="SELL",
        qty=25,
        status="complete",
        avg=102.0,
        position_ref="new-position",
    )
    assert recovery.recover_run(run_id).ok is True

    order_events._apply_update(
        "OLD-EXIT",
        _event("OLD-EXIT", status="complete", avg=110.0, filled=25),
    )

    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["position_ref"] == "new-position"
    assert leg["entry_order_id"] == new_entry
    assert leg["status"] == "open"
    assert leg["qty"] == 25
    assert leg["superseded"] is None
    assert leg["realized_pnl"] == pytest.approx(250.0)
    persisted_exit = next(row for row in store.list_orders(run_id) if row["id"] == old_exit)
    assert persisted_exit["status"] == "complete"


def test_post_recovery_rejection_releases_the_exact_superseded_owner_for_retry():
    sid = _strategy()
    run_id = _run(sid)
    _order(
        run_id,
        kind="entry",
        action="BUY",
        status="complete",
        avg=100.0,
        position_ref="old-position",
    )
    _order(
        run_id,
        kind="exit_signal",
        action="SELL",
        status="open",
        position_ref="old-position",
        broker_order_id="OLD-EXIT",
    )
    _order(
        run_id,
        kind="entry",
        action="SELL",
        status="complete",
        avg=102.0,
        position_ref="new-position",
    )
    assert recovery.recover_run(run_id).ok is True

    order_events._apply_update(
        "OLD-EXIT",
        _event("OLD-EXIT", status="rejected", avg=0.0, filled=0, rejection="no"),
    )

    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["position_ref"] == "new-position"
    assert leg["exit_order_id"] is None
    assert leg["superseded"]["exit_order_id"] is None
    assert leg["superseded"]["exit_kind"] is None
    retry = state.claim_superseded_exit(run_id, 1, "B")
    assert retry is not None
    assert retry["position_ref"] == "old-position"
    assert retry["quantity"] == 75


def test_authoritative_legacy_leg_pnl_overrides_zero_checkpoint_when_recovery_is_flat():
    """Legacy terminal prices are stronger than a checkpoint written before the exit."""
    sid = _strategy()
    run_id = _run(sid)
    _order(
        run_id,
        kind="entry",
        action="BUY",
        qty=75,
        status="complete",
        avg=100.0,
    )
    _order(
        run_id,
        kind="exit_signal",
        action="SELL",
        qty=75,
        status="complete",
        avg=110.0,
    )
    _checkpoint(
        run_id,
        {
            "1": _cp_leg(
                position="B",
                status="closed",
                exit_avg=110.0,
                realized_pnl=0.0,
            )
        },
        pnl_realized=0.0,
    )

    recovered = recovery.recover_run(run_id)

    assert recovered.finalised is True
    assert float(store.get_run(run_id).pnl_realized) == pytest.approx(750.0)


def test_reference_group_pnl_overrides_a_stale_nonzero_checkpoint_when_recovery_is_flat():
    sid = _strategy()
    run_id = _run(sid)
    _order(
        run_id,
        kind="entry",
        action="BUY",
        qty=75,
        status="complete",
        avg=100.0,
        position_ref="settled-position",
    )
    _order(
        run_id,
        kind="exit_signal",
        action="SELL",
        qty=75,
        status="complete",
        avg=110.0,
        position_ref="settled-position",
    )
    _checkpoint(
        run_id,
        {
            "1": _cp_leg(
                position="B",
                position_ref="settled-position",
                status="closed",
                exit_avg=110.0,
                realized_pnl=25.0,
            )
        },
        pnl_realized=25.0,
    )

    recovered = recovery.recover_run(run_id)

    assert recovered.finalised is True
    assert float(store.get_run(run_id).pnl_realized) == pytest.approx(750.0)


def test_mixed_priced_and_unpriced_reference_groups_use_matching_checkpoint_cumulative_pnl():
    sid = _strategy()
    run_id = _run(sid)
    _order(
        run_id,
        kind="entry",
        action="BUY",
        qty=10,
        status="complete",
        avg=100.0,
        position_ref="priced-owner",
    )
    _order(
        run_id,
        kind="exit_signal",
        action="SELL",
        qty=10,
        status="complete",
        avg=110.0,
        position_ref="priced-owner",
    )
    _order(
        run_id,
        kind="entry",
        action="BUY",
        qty=10,
        status="complete",
        avg=100.0,
        position_ref="unpriced-owner",
    )
    _order(
        run_id,
        kind="exit_signal",
        action="SELL",
        qty=10,
        status="complete",
        avg=0.0,
        filled_qty=10,
        position_ref="unpriced-owner",
    )
    _checkpoint(
        run_id,
        {
            "1": _cp_leg(
                position="B",
                position_ref="unpriced-owner",
                qty=10,
                status="closed",
                exit_avg=0.0,
                realized_pnl=150.0,
            )
        },
        pnl_realized=150.0,
    )

    recovered = recovery.recover_run(run_id)

    assert recovered.finalised is True
    assert float(store.get_run(run_id).pnl_realized) == pytest.approx(150.0)


def test_exact_durable_break_even_overrides_stale_nonzero_checkpoint():
    sid = _strategy()
    run_id = _run(sid)
    _order(
        run_id,
        kind="entry",
        action="BUY",
        qty=10,
        status="complete",
        avg=100.0,
        position_ref="break-even-owner",
    )
    _order(
        run_id,
        kind="exit_signal",
        action="SELL",
        qty=10,
        status="complete",
        avg=100.0,
        position_ref="break-even-owner",
    )
    _checkpoint(
        run_id,
        {
            "1": _cp_leg(
                position="B",
                position_ref="break-even-owner",
                qty=10,
                status="closed",
                exit_avg=100.0,
                realized_pnl=25.0,
            )
        },
        pnl_realized=25.0,
    )

    recovered = recovery.recover_run(run_id)

    assert recovered.finalised is True
    assert float(store.get_run(run_id).pnl_realized) == pytest.approx(0.0)


def test_mixed_legacy_closed_and_referenced_open_legs_have_authoritative_run_pnl():
    sid = _strategy(legs=[_leg(1, "S"), _leg(2, "B")])
    run_id = _run(sid)
    _order(
        run_id,
        leg_id=1,
        kind="entry",
        action="SELL",
        symbol=CE,
        qty=75,
        status="complete",
        avg=100.0,
        position_ref=None,
    )
    _order(
        run_id,
        leg_id=1,
        kind="exit_signal",
        action="BUY",
        symbol=CE,
        qty=75,
        status="complete",
        avg=80.0,
        position_ref=None,
    )
    _order(
        run_id,
        leg_id=2,
        kind="entry",
        action="BUY",
        symbol=PE,
        qty=75,
        status="complete",
        avg=50.0,
        position_ref="open-owner",
    )

    assert recovery.recover_run(run_id).ok is True

    live = state.get_run_state(run_id)
    assert live["legs"]["1"]["status"] == "closed"
    assert live["legs"]["2"]["status"] == "open"
    assert live["pnl_realized"] == pytest.approx(1500.0)
    assert live["pnl_realized_authoritative"] is True


def test_unpriced_reference_fill_without_checkpoint_surfaces_partial_pnl_authority():
    sid = _strategy()
    run_id = _run(sid)
    _order(
        run_id,
        kind="entry",
        action="BUY",
        qty=75,
        status="complete",
        avg=100.0,
        position_ref="unpriced-open-owner",
    )
    _order(
        run_id,
        kind="exit_signal",
        action="SELL",
        qty=75,
        status="cancelled",
        avg=0.0,
        filled_qty=25,
        position_ref="unpriced-open-owner",
    )

    assert recovery.recover_run(run_id).ok is True

    live = state.get_run_state(run_id)
    assert live["pnl_realized"] == pytest.approx(0.0)
    assert live["pnl_realized_authoritative"] is False
    assert live["legs"]["1"]["qty"] == 50
    events = [event for event in store.list_events(sid) if event["run_id"] == run_id]
    assert any(
        event["severity"] == "critical"
        and "p&l" in event["message"].lower()
        and "manual" in event["message"].lower()
        for event in events
    )


@pytest.mark.parametrize("filled_qty", [25, 75], ids=["partial", "full"])
@pytest.mark.parametrize("checkpoint_after_fill", [False, True], ids=["before", "after"])
def test_unpriced_live_fill_trusts_checkpoint_pnl_only_when_owner_shape_observed_the_fill(
    filled_qty,
    checkpoint_after_fill,
):
    sid = _strategy()
    run_id = _run(sid)
    _order(
        run_id,
        kind="entry",
        action="BUY",
        qty=75,
        status="complete",
        avg=100.0,
        position_ref="live-owner",
    )

    def write_checkpoint(*, observed):
        is_closed = observed and filled_qty == 75
        remaining = 75 - filled_qty if observed and not is_closed else 75
        _checkpoint(
            run_id,
            {
                "1": _cp_leg(
                    position="B",
                    position_ref="live-owner",
                    qty=remaining,
                    status="closed" if is_closed else "open",
                    realized_pnl=175.0,
                )
            },
            pnl_realized=175.0,
        )

    if not checkpoint_after_fill:
        write_checkpoint(observed=False)
    _order(
        run_id,
        kind="exit_signal",
        action="SELL",
        qty=75,
        status="cancelled",
        avg=0.0,
        filled_qty=filled_qty,
        position_ref="live-owner",
    )
    if checkpoint_after_fill:
        write_checkpoint(observed=True)

    recovered = recovery.recover_run(run_id)

    expected_pnl = 175.0 if checkpoint_after_fill else 0.0
    if filled_qty == 75:
        assert recovered.finalised is True
        assert float(store.get_run(run_id).pnl_realized) == pytest.approx(expected_pnl)
    else:
        assert recovered.ok is True
        live = state.get_run_state(run_id)
        assert live["legs"]["1"]["qty"] == 50
        assert live["pnl_realized"] == pytest.approx(expected_pnl)
        assert live["pnl_realized_authoritative"] is checkpoint_after_fill

    critical_pnl_events = [
        event
        for event in store.list_events(sid)
        if event["severity"] == "critical"
        and "p&l" in event["message"].lower()
        and "manual" in event["message"].lower()
    ]
    assert bool(critical_pnl_events) is (not checkpoint_after_fill)


@pytest.mark.parametrize("filled_qty", [25, 75], ids=["partial", "full"])
@pytest.mark.parametrize("checkpoint_after_fill", [False, True], ids=["before", "after"])
def test_unpriced_superseded_fill_trusts_checkpoint_pnl_only_when_owner_shape_observed_the_fill(
    filled_qty,
    checkpoint_after_fill,
):
    sid = _strategy()
    run_id = _run(sid)
    old_entry = _order(
        run_id,
        kind="entry",
        action="BUY",
        qty=75,
        status="complete",
        avg=100.0,
        position_ref="outgoing-owner",
    )
    old_exit = _order(
        run_id,
        kind="exit_signal",
        action="SELL",
        qty=75,
        status="open",
        avg=None,
        position_ref="outgoing-owner",
        broker_order_id="OUTGOING-EXIT",
    )
    new_entry = _order(
        run_id,
        kind="entry",
        action="SELL",
        qty=75,
        status="complete",
        avg=102.0,
        position_ref="replacement-owner",
    )

    def write_checkpoint(*, observed):
        superseded = None
        if not observed or filled_qty < 75:
            superseded = {
                "position_ref": "outgoing-owner",
                "position": "B",
                "qty": 75 - filled_qty if observed else 75,
                "entry_order_id": old_entry,
                "entry_avg": 100.0,
                "exit_order_id": None if observed else old_exit,
                "exit_kind": None if observed else "exit_signal",
            }
        _checkpoint(
            run_id,
            {
                "1": _cp_leg(
                    position="S",
                    position_ref="replacement-owner",
                    entry_order_id=new_entry,
                    entry_avg=102.0,
                    qty=75,
                    status="open",
                    superseded=superseded,
                    realized_pnl=275.0,
                )
            },
            pnl_realized=275.0,
        )

    if not checkpoint_after_fill:
        write_checkpoint(observed=False)
    assert store.update_order(
        old_exit,
        status="cancelled",
        avg_fill_price=0.0,
        filled_qty=filled_qty,
    )
    if checkpoint_after_fill:
        write_checkpoint(observed=True)

    assert recovery.recover_run(run_id).ok is True

    live = state.get_run_state(run_id)
    leg = live["legs"]["1"]
    assert leg["position_ref"] == "replacement-owner"
    if filled_qty == 75:
        assert leg["superseded"] is None
    else:
        assert leg["superseded"]["position_ref"] == "outgoing-owner"
        assert leg["superseded"]["qty"] == 50
    assert live["pnl_realized"] == pytest.approx(275.0 if checkpoint_after_fill else 0.0)
    assert live["pnl_realized_authoritative"] is checkpoint_after_fill

    critical_pnl_events = [
        event
        for event in store.list_events(sid)
        if event["severity"] == "critical"
        and "p&l" in event["message"].lower()
        and "manual" in event["message"].lower()
    ]
    assert bool(critical_pnl_events) is (not checkpoint_after_fill)


def test_unpriced_fill_never_trusts_a_different_owner_checkpoint_cumulative_pnl():
    sid = _strategy()
    run_id = _run(sid)
    _order(
        run_id,
        kind="entry",
        action="BUY",
        qty=75,
        status="complete",
        avg=100.0,
        position_ref="actual-owner",
    )
    _order(
        run_id,
        kind="exit_signal",
        action="SELL",
        qty=75,
        status="cancelled",
        avg=0.0,
        filled_qty=25,
        position_ref="actual-owner",
    )
    _checkpoint(
        run_id,
        {
            "1": _cp_leg(
                position="B",
                position_ref="different-owner",
                qty=50,
                status="open",
                realized_pnl=999.0,
            )
        },
        pnl_realized=999.0,
    )

    assert recovery.recover_run(run_id).ok is True

    live = state.get_run_state(run_id)
    assert live["pnl_realized"] == pytest.approx(0.0)
    assert live["pnl_realized_authoritative"] is False
    assert live["legs"]["1"]["qty"] == 50
    assert any(
        event["severity"] == "critical"
        and "p&l" in event["message"].lower()
        and "manual" in event["message"].lower()
        for event in store.list_events(sid)
    )


def test_a_run_whose_every_leg_has_closed_is_finished_rather_than_left_running():
    # The process died between the last exit fill and the finalise it would
    # have triggered. Resuming it would leave a strategy reading as running
    # while holding nothing, and no tick would ever arrive to close it.
    sid = _strategy()
    run_id = _run(sid)
    _order(run_id, 1, "entry", action="SELL", status="complete", avg=100.0)
    _order(run_id, 1, "exit_sl", action="BUY", status="complete", avg=80.0)

    resumed = recovery.recover_all()

    assert run_id not in resumed
    run = store.list_runs(sid)[0]
    assert run["stopped_at"] is not None
    assert run["pnl_realized"] == pytest.approx(1500.0)
    assert store.get_strategy(sid, USER).status == "stopped"
    assert state.get_run_state(run_id) is None


def test_recovery_atomic_finalise_loser_emits_nothing_and_keeps_live_ownership():
    sid = _strategy()
    run_id = _run(sid)
    state.hydrate_run_state(
        run_id,
        {
            "run_id": run_id,
            "strategy_id": sid,
            "stopping": True,
            "signal_entry_claims": {},
            "legs": {},
        },
    )

    with (
        patch.object(
            store,
            "finish_run_and_release_strategy",
            return_value=False,
            create=True,
        ),
        patch.object(recovery, "_record_event") as record_event,
    ):
        won = recovery._finalise(
            run_id,
            sid,
            reason="manual",
            kind="run_stopped",
            severity="info",
            message="Run stopped (manual)",
        )

    assert won is False
    assert store.get_run(run_id).stopped_at is None
    assert store.get_strategy(sid, USER).current_run_id == run_id
    assert state.get_run_state(run_id) is not None
    record_event.assert_not_called()


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------


def test_every_recovered_leg_carries_a_position():
    # A leg with no side is evaluated as a short by the risk core, which
    # silently inverts its P&L, its stop and its target. The checkpoint here
    # has lost the side entirely; the action that opened the leg supplies it.
    sid = _strategy(legs=[_leg(1, "S"), _leg(2, "B")])
    run_id = _run(sid)
    _order(run_id, 1, "entry", action="SELL", symbol=CE, status="complete", avg=100.0)
    _order(run_id, 2, "entry", action="BUY", symbol=PE, status="complete", avg=50.0)
    _checkpoint(
        run_id,
        {
            "1": _cp_leg(1, position=None, symbol=CE),
            "2": _cp_leg(2, position=None, symbol=PE, entry_avg=50.0),
        },
    )

    recovery.recover_all()

    legs = state.get_run_state(run_id)["legs"]
    assert all(leg["position"] in ("B", "S") for leg in legs.values())
    assert legs["1"]["position"] == "S"
    assert legs["2"]["position"] == "B"


@pytest.mark.parametrize("status", ["submitted", "trigger_pending", "TRIGGER PENDING", "modified"])
def test_a_working_broker_status_reads_the_same_way_everywhere(status):
    # PORTED DEFECT. The original normalises broker statuses in two separate
    # functions that disagree on exactly these three: one counts them as live
    # orders, the other writes them off as unknown and therefore dead. The same
    # row could then be read as holding a position or holding nothing.
    assert recovery.order_is_working(status) is True
    assert recovery.order_is_filled(status) is False
    assert recovery.order_is_dead(status) is False


def test_an_unrecognised_status_is_read_as_working_rather_than_dead():
    # Writing an unknown exit off as dead would let a second exit be placed
    # against a position already on its way out, and a second exit does not
    # close a position twice: it opens the opposite one.
    assert recovery.normalise_order_status("some-new-broker-word") == "open"
    assert recovery.order_is_dead("some-new-broker-word") is False


# ---------------------------------------------------------------------------
# Failure and idempotence
# ---------------------------------------------------------------------------


def test_recovery_releases_an_empty_claim_when_a_process_dies_before_run_linkage():
    """A crash after ``create_run`` but before linkage must not wedge a strategy.

    No entry can be dispatched before the linkage write, so this exact
    zero-order run is safe to finish.  The strategy claim has no
    ``current_run_id`` yet, which is deliberately different from a detached
    residual run belonging to an older activation.
    """
    sid = _strategy(name="Unlinked crash-window run")
    assert store.claim_strategy_for_run(sid) is True
    run = store.create_run(sid, "sandbox", "sandbox")
    assert run is not None
    run_id = int(run.id)

    recovered = recovery.recover_run(run_id)

    assert recovered.finalised is True
    assert store.get_run(run_id).stopped_at is not None
    strategy = store.get_strategy(sid, USER)
    assert strategy.status == "stopped"
    assert strategy.current_run_id is None


def test_a_run_that_cannot_be_recovered_is_finalised_rather_than_wedging_the_boot():
    # One unrecoverable run must not cost every other run its recovery, on this
    # boot or on any future one.
    bad_sid = _strategy(name="Recovery test bad")
    bad_run = _run(bad_sid)
    # An action that is neither BUY nor SELL leaves the leg with no side.
    _order(bad_run, 1, "entry", action="HOLD", status="complete", avg=100.0)

    good_sid = _strategy(name="Recovery test good")
    good_run = _run(good_sid)
    _order(good_run, 1, "entry", action="SELL", symbol=PE, status="complete", avg=100.0)

    resumed = recovery.recover_all()

    assert bad_run not in resumed
    assert resumed[good_run] == {(PE, "NFO")}

    closed = store.list_runs(bad_sid)[0]
    assert closed["stop_reason"] == "recovery_failed"
    assert closed["stopped_at"] is not None
    assert store.get_strategy(bad_sid, USER).status == "stopped"
    assert state.get_run_state(bad_run) is None
    assert "recovery_failed" in [event["kind"] for event in store.list_events(bad_sid)]


def test_recovering_twice_does_not_overwrite_live_state():
    # A second call, or a recovery racing a run that started normally, must not
    # replace live state with an older snapshot of it.
    sid = _strategy()
    run_id = _run(sid)
    _order(run_id, 1, "entry", action="SELL", status="complete", avg=100.0)
    recovery.recover_all()

    with state.run_state(run_id) as run:
        run["legs"]["1"]["ltp"] = 42.0

    resumed = recovery.recover_all()

    assert resumed[run_id] == {(CE, "NFO")}
    assert state.get_run_state(run_id)["legs"]["1"]["ltp"] == 42.0


# ---------------------------------------------------------------------------
# The checkpoint writer
# ---------------------------------------------------------------------------


def _live_run(name="Checkpoint test"):
    """A strategy, an open run and one live leg in state."""
    sid = _strategy(name=name)
    run_id = _run(sid)
    state.init_run_state(
        run_id,
        sid,
        [
            {
                "leg_id": 1,
                "position": "S",
                "symbol": CE,
                "exchange": "NFO",
                "quantity": 75,
                "sl_pts": 20,
            }
        ],
    )
    return sid, run_id


def test_the_checkpoint_writer_prunes_while_leaving_the_newest_row_intact(monkeypatch):
    # A row per run every few seconds for a session is thousands of rows per
    # run in a worker that never restarts. Recovery only ever reads the newest,
    # which is the one row a prune can never remove.
    _sid, run_id = _live_run()
    monkeypatch.setattr(checkpoint, "CHECKPOINT_KEEP", 3)

    for total in range(1, 7):
        with state.run_state(run_id) as run:
            run["pnl_total"] = float(total)
        assert checkpoint.write_once(prune=False) == 1
        # Only so the rows carry distinct timestamps; the writer itself is
        # never waited on.
        time.sleep(0.005)

    assert len(store.list_checkpoints(run_id)) == 6

    with state.run_state(run_id) as run:
        run["pnl_total"] = 99.0
    checkpoint.write_once(prune=True)

    assert len(store.list_checkpoints(run_id)) == 3
    newest = store.latest_checkpoint(run_id)
    assert newest["pnl_total"] == 99.0
    assert newest["leg_state"]["1"]["symbol"] == CE


def test_a_checkpoint_that_cannot_be_written_does_not_cost_the_other_runs_theirs(monkeypatch):
    _sid_a, run_a = _live_run(name="Checkpoint test A")
    _sid_b, run_b = _live_run(name="Checkpoint test B")
    real_write = store.write_checkpoint
    seen = []

    def flaky(run_id, snapshot):
        seen.append(run_id)
        if run_id == run_a:
            raise RuntimeError("disk went away")
        return real_write(run_id, snapshot)

    monkeypatch.setattr(store, "write_checkpoint", flaky)

    written = checkpoint.write_once(prune=False)

    assert set(seen) == {run_a, run_b}
    assert written == 1
    assert store.latest_checkpoint(run_a) is None
    assert store.latest_checkpoint(run_b) is not None


def test_a_pass_snapshots_every_live_run_in_the_shape_recovery_reads_back():
    _sid, run_id = _live_run()
    with state.run_state(run_id) as run:
        run["pnl_total"] = 375.0
        run["legs"]["1"]["entry_avg"] = 100.0
        run["legs"]["1"]["ltp"] = 95.0

    assert checkpoint.write_once(prune=False) == 1

    snapshot = store.latest_checkpoint(run_id)
    assert snapshot["pnl_total"] == 375.0
    assert snapshot["leg_state"]["1"]["entry_avg"] == 100.0
    assert snapshot["leg_state"]["1"]["ltp"] == 95.0
    assert snapshot["leg_state"]["1"]["position"] == "S"


def test_the_writer_starts_only_when_it_is_asked_to():
    # Two modules in this codebase start a scheduler as an import side effect,
    # which means any tool that imports the app spins up live background work.
    # Importing this one does nothing at all.
    assert checkpoint.is_running() is False

    assert checkpoint.start() is True
    try:
        assert checkpoint.is_running() is True
        # Idempotent, so a caller need not know whether it is already up.
        assert checkpoint.start() is False
    finally:
        checkpoint.stop()

    assert checkpoint.is_running() is False
    # Also idempotent on the way down.
    checkpoint.stop()


# ---------------------------------------------------------------------------
# A leg the checkpoint says exited, with no order row to read it from
#
# `exit_filled` has a clause for exactly that: no order rows at all, so the
# checkpoint is the only witness there is. Two reads then went through the
# missing row anyway and raised AttributeError inside recovery, which gave up
# on the whole run and finalised it as recovery_failed instead of rebuilding
# it. The first test asserts the crash itself, so this cannot pass vacuously.
# ---------------------------------------------------------------------------


def test_a_legacy_leg_with_no_exit_row_rebuilds_from_the_checkpoint():
    leg = recovery._rebuild_legacy_leg(
        "1",
        entries=[],
        exits=[],
        cp_leg={
            "position": "B",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "qty": 0,
            "status": "closed",
            "exit_filled": True,
            "exit_kind": "exit_signal",
            "exit_avg": 1313.1,
        },
        config_leg={},
    )

    assert leg["leg_id"] == "1"
    # Read from the checkpoint, because there is no row carrying it.
    assert leg.get("exit_kind") in (None, "exit_signal")


def test_a_legacy_leg_with_no_exit_row_but_a_priced_exit_rebuilds():
    """The other read through the missing row: the exit price.

    No order rows at all, so `identity` is None and the checkpoint is the only
    witness of the exit. That is the one path on which `exit_filled` is true
    with `exit_order` None, and a positive quantity is what makes
    `exit_applied` true and reaches the price read. An earlier version of this
    test supplied an entry row, which made `identity` non-None, left
    `exit_filled` false, and never reached the read at all: it passed against
    the unguarded code it was meant to pin.
    """
    leg = recovery._rebuild_legacy_leg(
        "1",
        entries=[],
        exits=[],
        cp_leg={
            "position": "B",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "qty": 5,
            "entry_avg": 1300.0,
            "exit_filled": True,
            "exit_avg": 1320.0,
            "exit_kind": "exit_sl",
        },
        config_leg={},
    )

    assert leg["symbol"] == "RELIANCE"
    assert leg["exit_avg"] == 1320.0, "the exit price was not read from the checkpoint"
    assert leg["exit_kind"] == "exit_sl", "the exit kind was not read from the checkpoint"
