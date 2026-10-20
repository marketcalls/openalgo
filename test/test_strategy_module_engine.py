"""Strategy engine: run lifecycle and the tick decision path.

The rules are tested in test/risk/ and test_strategy_module_risk.py. What is
tested here is what the engine does about them: what it places, in what order,
what it refuses, and what it leaves behind when something fails partway.

Several cases pin defects from the module this was ported from, and say so.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

# restx_api first: see the note in test_strategy_module_order_dispatch.py.
import restx_api  # noqa: F401
from database import strategy_module_db as store
from services.strategy_module import engine, order_events, state
from services.strategy_module.order_dispatch import DispatchResult
from services.strategy_module.symbol_resolver import ResolvedLeg

USER = "engine_test_user"


def _config(name="Engine test", legs=None, **overrides):
    config = {
        "name": name,
        "underlying": "NIFTY",
        "underlying_exchange": "NSE_INDEX",
        "universe_tab": "weekly_monthly",
        "product": "NRML",
        "legs": legs
        if legs is not None
        else [
            {
                "id": 1,
                "segment": "options",
                "expiry": "weekly",
                "lots": 1,
                "position": "S",
                "option_type": "CE",
                "strike_mode": "atm",
                "atm_offset": "ATM",
                "sl_pts": 20,
                "trail": {"x": 0, "y": 0},
            }
        ],
    }
    config.update(overrides)
    return config


def _resolved(leg_id=1, symbol="NIFTY28MAY2624000CE", qty=75):
    return ResolvedLeg(
        ok=True,
        symbol=symbol,
        exchange="NFO",
        segment="options",
        lotsize=75,
        tick_size=0.05,
        strike=24000.0,
        expiry="28-MAY-26",
        expiry_symbol="28MAY26",
        quantity=qty,
        lots=1,
        option_type="CE",
        underlying="NIFTY",
        underlying_ltp=24010.0,
        atm_strike=24000.0,
    )


@pytest.fixture(autouse=True)
def clean_slate():
    # Start from a clean session. This scoped_session is shared with every
    # other suite in the run, and a sibling that left rows deleted underneath
    # it leaves stale objects in the identity map here, which surface as
    # ObjectDeletedError on rows this file never touched.
    store.db_session.remove()
    store.init_db()

    def purge():
        for row in store.list_strategies(USER):
            if row["current_run_id"]:
                state.clear_run_state(row["current_run_id"])
            store.set_strategy_status(row["id"], "stopped", None)
            store.delete_strategy(row["id"], USER)
        store.clear_strategy_module_cache()

    purge()
    yield
    purge()


@pytest.fixture
def api_key():
    """Every path needs a server-side API key; none of these tests need a real one."""
    with patch.object(engine, "_api_key_for", return_value="test-api-key"):
        yield "test-api-key"


def _make(config=None):
    created, error = store.create_strategy(USER, config or _config())
    assert error is None, error
    return created["id"]


def _mark_kind(sid, kind):
    """Set the stored kind directly.

    Not through update_strategy, which refuses a kind change by design: the two
    kinds do not share a leg shape. A test that needs a started run whose row
    says signal has to write it, because nothing in the product will.
    """
    from database.strategy_module_db import SmStrategy
    from database.strategy_module_db import db_session as store_session

    row = store_session.query(SmStrategy).filter_by(id=sid).first()
    row.strategy_kind = kind
    store_session.commit()
    store_session.remove()


def _start(sid, mode="sandbox", dispatch=None, resolved=None):
    """Start a run with resolution and placement mocked."""
    resolved = resolved if resolved is not None else [_resolved()]
    dispatch = dispatch or (
        lambda **kw: DispatchResult(ok=True, broker_order_id="SB-1", response={})
    )
    with (
        patch.object(engine, "resolve_leg", side_effect=list(resolved) * 5),
        patch.object(engine.order_dispatch, "dispatch_order", side_effect=dispatch),
        patch.object(engine, "_broker_for", return_value="sandbox"),
    ):
        return engine.start_run(sid, USER, mode)


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------


def test_a_leg_that_cannot_be_resolved_stops_the_start_before_anything_is_claimed(api_key):
    # Resolution is the step most likely to fail, and it must fail cleanly: no
    # run row, no claimed strategy, no orders.
    sid = _make()
    bad = ResolvedLeg(ok=False, error="No contract found", code="contract_not_found")

    with (
        patch.object(engine, "resolve_leg", return_value=bad),
        patch.object(engine.order_dispatch, "dispatch_order") as dispatch,
    ):
        result = engine.start_run(sid, USER, "sandbox")

    assert result.ok is False
    assert "No contract found" in result.error
    assert dispatch.call_count == 0
    assert store.get_strategy(sid, USER).status == "stopped"
    assert store.list_runs(sid) == []


def test_a_second_start_is_refused_by_the_atomic_claim(api_key):
    # Three triggers can fire at once - the UI, the scheduler and a webhook.
    # The original guards this with SELECT ... FOR UPDATE, which SQLite parses
    # and does not honour, so the guard would be silently absent here.
    sid = _make()
    first = _start(sid)
    assert first.ok is True

    second = _start(sid)

    assert second.ok is False
    assert "already running" in second.error
    assert len(store.list_runs(sid)) == 1


def test_a_run_is_not_dispatched_when_its_strategy_link_cannot_be_persisted(api_key):
    """An unlinked run cannot own orders and must be closed without dispatch."""
    sid = _make()

    with (
        patch.object(store, "set_strategy_status", return_value=False),
        patch.object(engine.order_dispatch, "dispatch_order") as dispatch,
        patch.object(engine, "_subscribe_run") as subscribe,
    ):
        result = _start(sid)

    assert result.ok is False
    assert "link" in str(result.error).lower()
    dispatch.assert_not_called()
    subscribe.assert_not_called()
    assert state.active_run_ids() == []
    runs = store.list_runs(sid)
    assert len(runs) == 1
    assert runs[0]["stopped_at"] is not None
    assert runs[0]["stop_reason"] == "error"
    strategy = store.get_strategy(sid, USER)
    assert strategy.status == "stopped"
    assert strategy.current_run_id is None


def test_live_is_refused_unless_the_strategy_opted_in(api_key):
    sid = _make()

    result = _start(sid, mode="live")

    assert result.ok is False
    assert "not enabled for live" in result.error
    assert store.get_strategy(sid, USER).status == "stopped"


def test_an_unknown_mode_is_refused(api_key):
    sid = _make()

    result = engine.start_run(sid, USER, "paper-ish")

    assert result.ok is False
    assert "Unknown run mode" in result.error


def test_entries_are_placed_longs_first(api_key):
    # A spread whose short leg is placed first can be refused for margin the
    # account would have had once the long existed.
    sid = _make(
        _config(
            legs=[
                {"id": 1, "segment": "options", "position": "S", "lots": 1, "option_type": "CE"},
                {"id": 2, "segment": "options", "position": "B", "lots": 1, "option_type": "CE"},
            ]
        )
    )
    seen = []

    def record(**kwargs):
        seen.append(kwargs["order"]["action"])
        return DispatchResult(ok=True, broker_order_id="SB", response={})

    _start(
        sid,
        dispatch=record,
        resolved=[_resolved(leg_id=1, symbol="LEG1"), _resolved(leg_id=2, symbol="LEG2")],
    )

    assert seen[0] == "BUY"
    assert seen[1] == "SELL"


def test_every_entry_rejected_finalises_the_run_rather_than_leaving_it_running(api_key):
    # A running strategy holding nothing is worse than a stopped one: it looks
    # managed and is not.
    sid = _make()

    result = _start(
        sid, dispatch=lambda **kw: DispatchResult(ok=False, error="Insufficient margin")
    )

    assert result.ok is False
    assert store.get_strategy(sid, USER).status == "stopped"
    runs = store.list_runs(sid)
    assert len(runs) == 1
    assert runs[0]["stopped_at"] is not None
    assert runs[0]["stop_reason"] == "error"


def test_every_unrecordable_entry_rejects_its_placeholder_and_cleans_up_the_run(api_key):
    sid = _make()

    with (
        patch.object(store, "record_order", return_value=None),
        patch.object(engine, "_subscribe_run") as subscribe,
        patch.object(engine, "_unsubscribe_run") as unsubscribe,
    ):
        result = _start(sid)

    assert result.ok is False
    assert "Every entry order was rejected" in result.error
    durable = store.list_runs(sid)[0]
    assert durable["stopped_at"] is not None
    assert durable["stop_reason"] == "error"
    strategy = store.get_strategy(sid, USER)
    assert strategy.status == "stopped"
    assert strategy.current_run_id is None
    assert state.get_run_state(durable["id"]) is None
    subscribe.assert_called_once()
    unsubscribe.assert_called_once_with(durable["id"])


def test_failed_ack_persistence_records_exact_structured_repair_metadata(api_key):
    sid = _make()

    with (
        patch.object(store, "update_order", return_value=False),
        patch.object(engine, "_subscribe_run"),
    ):
        result = _start(sid)

    assert result.ok is True
    assert result.legs[0]["acknowledged"] is False
    event = next(
        event for event in store.list_events(sid) if event["kind"] == "order_ack_unrecorded"
    )
    order = store.list_orders(result.run_id)[0]
    assert event["severity"] == "critical"
    assert event["payload"] == {
        "version": 1,
        "order_id": order["id"],
        "run_id": result.run_id,
        "leg_id": 1,
        "broker_order_id": "SB-1",
        "accepted": True,
        "status": "open",
        "reject_reason": None,
    }
    assert "automatic" in event["message"].lower()
    assert "by hand" not in event["message"].lower()


def test_failed_ack_is_repaired_before_a_later_fill_on_an_active_run(api_key):
    sid = _make()

    with (
        patch.object(store, "update_order", return_value=False),
        patch.object(engine, "_subscribe_run"),
    ):
        result = _start(sid)

    assert result.ok is True
    assert result.legs[0]["acknowledged"] is False
    order = store.list_orders(result.run_id)[0]
    assert order["broker_order_id"] == "SB-1"
    assert order["status"] == "open"

    order_events._apply_update(
        "SB-1",
        SimpleNamespace(
            orderid="SB-1",
            order_status="complete",
            average_price=101.5,
            filled_quantity=75,
            rejection_reason="",
        ),
    )

    durable = store.get_order(order["id"])
    assert durable.status == "complete"
    assert durable.filled_qty == 75
    live = state.get_run_state(result.run_id)["legs"]["1"]
    assert live["entry_status"] == "complete"
    assert live["entry_avg"] == pytest.approx(101.5)
    assert live["qty"] == 75
    assert store.get_run(result.run_id).stop_requested_reason is None


def test_start_exception_before_any_dispatch_rejects_every_placeholder_and_finishes_flat(api_key):
    """A pre-dispatch failure leaves no broker ambiguity and may finish safely."""
    sid = _make()
    cancel = Mock()
    poll = Mock()

    with (
        patch.object(store, "record_order", side_effect=RuntimeError("disk unavailable")),
        patch.object(engine.order_dispatch, "cancel_order", cancel, create=True),
        patch.object(engine.order_dispatch, "fetch_order_status", poll, create=True),
        patch.object(engine, "_subscribe_run"),
        patch.object(engine, "_unsubscribe_run"),
    ):
        result = _start(sid)

    run = store.list_runs(sid)[0]
    assert result.ok is False
    assert run["stopped_at"] is not None
    assert run["stop_reason"] == "error"
    assert store.get_strategy(sid, USER).status == "stopped"
    assert state.get_run_state(run["id"]) is None
    cancel.assert_not_called()
    poll.assert_not_called()


def test_start_exception_after_partial_dispatch_stops_accepted_entries_and_rejects_undispatched(
    api_key,
):
    """An accepted working entry survives as managed truth when the next dispatch raises."""
    legs = [
        {"id": leg_id, "segment": "options", "position": "B", "lots": 1, "option_type": "CE"}
        for leg_id in (1, 2, 3)
    ]
    sid = _make(_config(legs=legs))
    dispatch_count = 0

    def place_then_raise(**_kwargs):
        nonlocal dispatch_count
        dispatch_count += 1
        if dispatch_count == 1:
            return DispatchResult(ok=True, broker_order_id="WORKING-1", response={})
        raise RuntimeError("adapter failed after an uncertain send")

    lock_states = []

    def refuse_cancel(**kwargs):
        active_run_id = state.active_run_ids()[0]
        lock_states.append(state.get_state_lock(active_run_id).locked())
        return DispatchResult(ok=False, broker_order_id=kwargs["broker_order_id"], error="refused")

    def unavailable_status(**_kwargs):
        active_run_id = state.active_run_ids()[0]
        lock_states.append(state.get_state_lock(active_run_id).locked())
        return SimpleNamespace(ok=False, order=None, error="status unavailable")

    with (
        patch.object(engine, "resolve_leg", side_effect=[_resolved(1), _resolved(2), _resolved(3)]),
        patch.object(engine.order_dispatch, "dispatch_order", side_effect=place_then_raise),
        patch.object(engine.order_dispatch, "cancel_order", side_effect=refuse_cancel, create=True),
        patch.object(
            engine.order_dispatch,
            "fetch_order_status",
            side_effect=unavailable_status,
            create=True,
        ),
        patch.object(engine, "_broker_for", return_value="sandbox"),
    ):
        result = engine.start_run(sid, USER, "sandbox")

    assert result.ok is False
    assert result.run_id is not None
    assert "managed" in str(result.error).lower()
    run = store.get_run(result.run_id)
    assert run.stopped_at is None
    assert run.stop_requested_reason == "error"
    assert store.get_strategy(sid, USER).current_run_id == result.run_id
    orders = store.list_orders(result.run_id)
    assert [(row["leg_id"], row["status"], row["broker_order_id"]) for row in orders] == [
        (1, "open", "WORKING-1"),
        (2, "pending", None),
    ]
    live = state.get_run_state(result.run_id)
    assert live["stopping"] is True
    assert live["legs"]["1"]["entry_status"] == "open"
    assert live["legs"]["2"]["entry_status"] == "pending"
    assert live["legs"]["3"]["entry_status"] == "rejected"
    assert lock_states == [False, False]


def test_all_rejected_start_reports_atomic_cleanup_failure_and_later_stop_can_finish(api_key):
    sid = _make()
    real_finish = store.finish_run_and_release_strategy
    attempts = []

    def lose_once(*args, **kwargs):
        attempts.append(args[0])
        if len(attempts) == 1:
            return False
        return real_finish(*args, **kwargs)

    with (
        patch.object(store, "record_order", return_value=None),
        patch.object(store, "finish_run_and_release_strategy", side_effect=lose_once),
        patch.object(engine, "_subscribe_run"),
        patch.object(engine, "_unsubscribe_run") as unsubscribe,
    ):
        started = _start(sid)

        assert started.ok is False
        assert started.run_id is not None
        assert "final" in started.error.lower()
        pending = store.get_run(started.run_id)
        assert pending.stopped_at is None
        assert store.get_strategy(sid, USER).current_run_id == started.run_id
        live = state.get_run_state(started.run_id)
        assert live["legs"]["1"]["entry_status"] == "rejected"
        assert live["legs"]["1"]["status"] == "rejected"

        retried = engine.stop_run(started.run_id, USER, reason="manual")

    assert retried == {"ok": True, "stop_pending": False, "exits": []}
    assert attempts == [started.run_id, started.run_id]
    assert store.get_run(started.run_id).stopped_at is not None
    assert store.get_strategy(sid, USER).current_run_id is None
    assert state.get_run_state(started.run_id) is None
    unsubscribe.assert_called_once_with(started.run_id)


def test_a_started_run_records_its_orders_and_live_state(api_key):
    sid = _make()

    result = _start(sid)

    assert result.ok is True
    orders = store.list_orders(result.run_id)
    assert [o["kind"] for o in orders] == ["entry"]
    assert orders[0]["symbol"] == "NIFTY28MAY2624000CE"

    live = state.get_run_state(result.run_id)
    assert live["legs"]["1"]["status"] == "open"
    assert live["legs"]["1"]["position"] == "S"


# ---------------------------------------------------------------------------
# Fills
# ---------------------------------------------------------------------------


def test_an_entry_fill_sets_the_price_risk_is_measured_from(api_key):
    sid = _make()
    run_id = _start(sid).run_id

    engine.apply_fill(run_id, 1, 100.0, is_entry=True)

    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["entry_avg"] == 100.0
    assert leg["status"] == "open"


def test_an_exit_fill_locks_in_realized_pnl_with_the_right_sign(api_key):
    # Short leg: selling at 100 and buying back at 80 is a profit. Two legs, so
    # closing one does not take the run flat and clear the state under us.
    sid = _make(
        _config(
            legs=[
                {"id": 1, "segment": "options", "position": "S", "lots": 1, "sl_pts": 20},
                {"id": 2, "segment": "options", "position": "B", "lots": 1, "sl_pts": 20},
            ]
        )
    )
    run_id = _start(
        sid, resolved=[_resolved(leg_id=1, symbol="L1"), _resolved(leg_id=2, symbol="L2")]
    ).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    engine.apply_fill(run_id, 2, 50.0, is_entry=True)

    went_flat = engine.apply_fill(run_id, 1, 80.0, is_entry=False)

    assert went_flat is False  # leg 2 is still open
    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["status"] == "closed"
    assert leg["realized_pnl"] == pytest.approx((80.0 - 100.0) * 75 * -1)
    assert leg["realized_pnl"] > 0
    assert leg["mtm"] == 0.0


def test_a_long_exit_fill_carries_the_opposite_sign(api_key):
    # The same arithmetic on a long: buying at 100 and selling at 80 is a loss.
    sid = _make(
        _config(
            legs=[
                {"id": 1, "segment": "options", "position": "B", "lots": 1, "sl_pts": 20},
                {"id": 2, "segment": "options", "position": "B", "lots": 1, "sl_pts": 20},
            ]
        )
    )
    run_id = _start(
        sid, resolved=[_resolved(leg_id=1, symbol="L1"), _resolved(leg_id=2, symbol="L2")]
    ).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    engine.apply_fill(run_id, 2, 50.0, is_entry=True)

    engine.apply_fill(run_id, 1, 80.0, is_entry=False)

    leg = state.get_run_state(run_id)["legs"]["1"]
    assert leg["realized_pnl"] == pytest.approx((80.0 - 100.0) * 75)
    assert leg["realized_pnl"] < 0


@pytest.mark.parametrize("fill_order", [("superseded", "live"), ("live", "superseded")])
def test_every_position_incarnation_adds_realized_pnl_in_any_final_fill_order(api_key, fill_order):
    sid = _make(_config(strategy_kind="signal"))
    run = store.create_run(sid, "sandbox", "sandbox")
    assert store.set_strategy_status(sid, "running", run.id)
    state.init_run_state(
        run.id,
        sid,
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
    with state.run_state(run.id) as live:
        leg = live["legs"]["1"]
        leg.update(
            {
                "status": "open",
                "entry_status": "complete",
                "entry_avg": 120.0,
                "exit_order_id": 202,
                "exit_kind": "exit_signal",
                "realized_pnl": 50.0,
                "superseded": {
                    "position_ref": "old-long",
                    "position": "B",
                    "entry_avg": 100.0,
                    "qty": 10,
                    "exit_order_id": 101,
                },
            }
        )

    fills = {
        "superseded": lambda: engine.apply_fill(
            run.id,
            1,
            110.0,
            is_entry=False,
            order_row_id=101,
            position_ref="old-long",
        ),
        "live": lambda: engine.apply_fill(
            run.id,
            1,
            100.0,
            is_entry=False,
            order_row_id=202,
            position_ref="live-short",
        ),
    }
    for owner in fill_order:
        fills[owner]()

    leg = state.get_run_state(run.id)["legs"]["1"]
    assert leg["realized_pnl"] == pytest.approx(350.0)
    assert state.get_run_state(run.id)["pnl_realized"] == pytest.approx(350.0)
    assert store.get_run(run.id).stopped_at is None


def test_zero_entry_price_exit_does_not_erase_prior_signal_session_realized_pnl(api_key):
    sid = _make(_config(strategy_kind="signal"))
    run = store.create_run(sid, "sandbox", "sandbox")
    assert store.set_strategy_status(sid, "running", run.id)
    state.init_run_state(
        run.id,
        sid,
        [
            {
                "leg_id": 1,
                "position": "B",
                "position_ref": "price-missing",
                "symbol": "NIFTY28MAY2624000CE",
                "exchange": "NFO",
                "quantity": 10,
            }
        ],
    )
    with state.run_state(run.id) as live:
        leg = live["legs"]["1"]
        leg.update(
            {
                "status": "open",
                "entry_status": "complete",
                "entry_avg": 0.0,
                "exit_order_id": 9,
                "exit_kind": "exit_signal",
                "realized_pnl": 75.0,
            }
        )

    engine.apply_fill(
        run.id,
        1,
        90.0,
        is_entry=False,
        order_row_id=9,
        position_ref="price-missing",
    )

    assert state.get_run_state(run.id)["legs"]["1"]["realized_pnl"] == pytest.approx(75.0)


# ---------------------------------------------------------------------------
# Exit
# ---------------------------------------------------------------------------


def test_an_exit_uses_the_symbol_the_run_holds_not_a_re_resolved_one(api_key):
    # An ATM offset resolved again hours later names a different strike.
    # Exiting that would open a new position instead of closing one.
    sid = _make()
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    seen = []

    def record(**kwargs):
        seen.append(kwargs["order"]["symbol"])
        return DispatchResult(ok=True, broker_order_id="SB-X", response={})

    with (
        patch.object(engine.order_dispatch, "dispatch_order", side_effect=record),
        patch.object(engine, "resolve_leg", return_value=_resolved(symbol="A-DIFFERENT-STRIKE")),
    ):
        engine.stop_run(run_id, USER, reason="manual")

    assert seen == ["NIFTY28MAY2624000CE"]


def test_an_exit_covers_a_short_rather_than_adding_to_it(api_key):
    # PORTED DEFECT. The original derives the exit action from the configured
    # side, which defaults to "B", so a rule-driven exit on a short placed
    # another SELL and doubled the position.
    sid = _make()
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    seen = []

    def record(**kwargs):
        seen.append(kwargs["order"]["action"])
        return DispatchResult(ok=True, broker_order_id="SB-X", response={})

    with patch.object(engine.order_dispatch, "dispatch_order", side_effect=record):
        engine.stop_run(run_id, USER, reason="manual")

    assert seen == ["BUY"]  # covering the short, not adding to it


def test_a_leg_already_exiting_is_not_sent_a_second_exit(api_key):
    # Two rules can fire on the same tick. Without the guard the leg is exited
    # twice and the second order opens an opposite position.
    sid = _make()
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    calls = []

    def record(**kwargs):
        calls.append(kwargs["order"]["symbol"])
        return DispatchResult(ok=True, broker_order_id="SB-X", response={})

    strategy = store.strategy_to_dict(store.get_strategy(sid, USER))
    with patch.object(engine.order_dispatch, "dispatch_order", side_effect=record):
        engine._exit_legs(run_id, strategy, [1], "exit_sl", "sandbox", "k", USER)
        engine._exit_legs(run_id, strategy, [1], "exit_target", "sandbox", "k", USER)

    assert len(calls) == 1


def test_a_rejected_exit_can_be_retried_rather_than_looking_like_a_duplicate(api_key):
    # If a failed exit left the marker set, the leg could never be exited again
    # and the position would be stranded.
    sid = _make()
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    strategy = store.strategy_to_dict(store.get_strategy(sid, USER))
    calls = []

    def failing(**kwargs):
        calls.append(1)
        return DispatchResult(ok=False, error="Broker unreachable")

    with patch.object(engine.order_dispatch, "dispatch_order", side_effect=failing):
        engine._exit_legs(run_id, strategy, [1], "exit_sl", "sandbox", "k", USER)
        engine._exit_legs(run_id, strategy, [1], "exit_sl", "sandbox", "k", USER)

    assert len(calls) == 2


def test_a_manual_close_does_not_trail_the_other_legs_to_entry(api_key):
    # Trail-to-entry answers the market moving against the book. An operator
    # closing one leg by hand is an override, and treating it as a signal would
    # tighten every other stop without being asked.
    sid = _make(
        _config(
            trail_sl_to_entry=True,
            legs=[
                {"id": 1, "segment": "options", "position": "S", "lots": 1, "sl_pts": 20},
                {"id": 2, "segment": "options", "position": "S", "lots": 1, "sl_pts": 20},
            ],
        )
    )
    run_id = _start(
        sid, resolved=[_resolved(leg_id=1, symbol="L1"), _resolved(leg_id=2, symbol="L2")]
    ).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    engine.apply_fill(run_id, 2, 200.0, is_entry=True)

    with patch.object(
        engine.order_dispatch,
        "dispatch_order",
        return_value=DispatchResult(ok=True, broker_order_id="X", response={}),
    ):
        engine.close_leg(run_id, 1, USER)

    live = state.get_run_state(run_id)
    assert live["trail_to_entry_active"] is False
    assert live["legs"]["2"]["effective_sl"] is None


def test_the_run_finalises_when_the_last_exit_fills_not_when_it_is_placed(api_key):
    # A leg is closed by its fill arriving, not by its exit being sent. Between
    # the two the strategy still holds the position, so it must still read as
    # running; finalising early would show a flat strategy that is not.
    sid = _make()
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)

    with patch.object(
        engine.order_dispatch,
        "dispatch_order",
        return_value=DispatchResult(ok=True, broker_order_id="X", response={}),
    ):
        result = engine.close_leg(run_id, 1, USER)

    assert result["ok"] is True
    assert result["run_stopped"] is False
    assert store.get_strategy(sid, USER).status == "running"

    went_flat = engine.apply_fill(run_id, 1, 80.0, is_entry=False)

    assert went_flat is True
    assert store.get_strategy(sid, USER).status == "stopped"
    runs = store.list_runs(sid)
    assert runs[0]["stopped_at"] is not None
    # The realized figure the fill produced reaches the row, rather than a zero
    # written before the fill was applied.
    assert runs[0]["pnl_realized"] == pytest.approx((80.0 - 100.0) * 75 * -1)


def test_close_leg_event_is_request_only_for_browser_and_restx_until_fill(api_key):
    """Both HTTP surfaces delegate here, so this is their shared audit truth."""
    sid = _make()
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)

    with patch.object(
        engine.order_dispatch,
        "dispatch_order",
        return_value=DispatchResult(ok=True, broker_order_id="EXIT-1", response={}),
    ):
        result = engine.close_leg(run_id, 1, USER)

    assert result["ok"] is True
    assert result["run_stopped"] is False
    manual = [event for event in store.list_events(sid) if event["kind"] == "leg_close_manual"]
    assert [event["message"] for event in manual] == ["Operator requested closure of leg 1"]
    assert not any(event["kind"] == "run_stopped" for event in store.list_events(sid))


def test_stop_cancels_a_working_entry_through_run_mode_then_polls_terminal_fact(api_key):
    """A successful cancel acknowledgement alone is not a flatness fact."""
    sid = _make()
    run_id = _start(sid).run_id
    lock_states = []

    def cancel(**kwargs):
        lock_states.append(state.get_state_lock(run_id).locked())
        assert kwargs == {
            "mode": "sandbox",
            "api_key": "test-api-key",
            "broker_order_id": "SB-1",
        }
        return DispatchResult(ok=True, broker_order_id="SB-1", response={})

    def poll(**kwargs):
        lock_states.append(state.get_state_lock(run_id).locked())
        assert kwargs == {
            "mode": "sandbox",
            "api_key": "test-api-key",
            "broker_order_id": "SB-1",
        }
        return SimpleNamespace(
            ok=True,
            order={
                "orderid": "SB-1",
                "order_status": "cancelled",
                "filled_quantity": 0,
                "average_price": 0,
                "rejection_reason": "cancelled by user",
            },
            error=None,
        )

    with (
        patch.object(engine.order_dispatch, "cancel_order", side_effect=cancel, create=True),
        patch.object(engine.order_dispatch, "fetch_order_status", side_effect=poll, create=True),
        patch.object(engine.order_dispatch, "dispatch_order") as exit_dispatch,
        patch.object(engine, "_unsubscribe_run"),
    ):
        result = engine.stop_run(run_id, USER, reason="manual")

    assert result == {"ok": True, "stop_pending": False, "exits": []}
    assert exit_dispatch.call_count == 0
    assert lock_states == [False, False]
    durable_order = store.list_orders(run_id)[0]
    assert durable_order["status"] == "cancelled"
    assert int(durable_order["filled_qty"] or 0) == 0
    assert store.get_run(run_id).stopped_at is not None
    assert state.get_run_state(run_id) is None


def test_stop_cancel_success_polling_a_partial_fill_exits_only_authoritative_quantity(api_key):
    """A fill won the cancel race, so its broker quantity becomes managed exposure."""
    sid = _make()
    run_id = _start(sid).run_id
    exit_orders = []

    def place_exit(**kwargs):
        exit_orders.append(kwargs["order"])
        return DispatchResult(ok=True, broker_order_id="PARTIAL-EXIT", response={})

    with (
        patch.object(
            engine.order_dispatch,
            "cancel_order",
            return_value=DispatchResult(ok=True, broker_order_id="SB-1", response={}),
            create=True,
        ) as cancel,
        patch.object(
            engine.order_dispatch,
            "fetch_order_status",
            return_value=SimpleNamespace(
                ok=True,
                order={
                    "orderid": "SB-1",
                    "order_status": "complete",
                    "filled_quantity": 25,
                    "average_price": 101.25,
                    "rejection_reason": "",
                },
                error=None,
            ),
            create=True,
        ) as poll,
        patch.object(engine.order_dispatch, "dispatch_order", side_effect=place_exit),
    ):
        result = engine.stop_run(run_id, USER, reason="manual")

    assert result["ok"] is True
    assert result["stop_pending"] is True
    cancel.assert_called_once_with(mode="sandbox", api_key="test-api-key", broker_order_id="SB-1")
    poll.assert_called_once_with(mode="sandbox", api_key="test-api-key", broker_order_id="SB-1")
    assert exit_orders[0]["quantity"] == "25"
    entry = next(row for row in store.list_orders(run_id) if row["kind"] == "entry")
    assert entry["status"] == "complete"
    assert entry["filled_qty"] == 25
    live = state.get_run_state(run_id)["legs"]["1"]
    assert live["qty"] == 25
    assert live["entry_status"] == "complete"
    assert live["exit_kind"] == "exit_close_all"


def test_operator_stop_retry_repolls_after_cancel_refusal_and_self_heals(api_key):
    """A refused first attempt remains durable; a later operator retry can confirm flatness."""
    sid = _make()
    run_id = _start(sid).run_id
    cancel_results = [
        DispatchResult(ok=False, broker_order_id="SB-1", error="broker busy"),
        DispatchResult(ok=True, broker_order_id="SB-1", response={}),
    ]
    status_results = [
        SimpleNamespace(ok=False, order=None, error="orderbook unavailable"),
        SimpleNamespace(
            ok=True,
            order={
                "orderid": "SB-1",
                "order_status": "cancelled",
                "filled_quantity": 0,
                "average_price": 0,
                "rejection_reason": "",
            },
            error=None,
        ),
    ]

    with (
        patch.object(
            engine.order_dispatch,
            "cancel_order",
            side_effect=cancel_results,
            create=True,
        ) as cancel,
        patch.object(
            engine.order_dispatch,
            "fetch_order_status",
            side_effect=status_results,
            create=True,
        ) as poll,
        patch.object(engine, "_unsubscribe_run"),
    ):
        first = engine.stop_run(run_id, USER, reason="manual")
        first_stopped_at = store.get_run(run_id).stopped_at
        second = engine.stop_run(run_id, USER, reason="manual")

    assert first["ok"] is False
    assert first["stop_pending"] is True
    assert first_stopped_at is None
    assert second == {"ok": True, "stop_pending": False, "exits": []}
    assert store.get_run(run_id).stopped_at is not None
    assert cancel.call_count == 2
    assert poll.call_count == 2


# ---------------------------------------------------------------------------
# Tick path
# ---------------------------------------------------------------------------


def test_a_stop_loss_tick_exits_that_leg(api_key):
    sid = _make()
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    placed = []

    def record(**kwargs):
        placed.append((kwargs["order"]["symbol"], kwargs["order"]["action"]))
        return DispatchResult(ok=True, broker_order_id="X", response={})

    with patch.object(engine.order_dispatch, "dispatch_order", side_effect=record):
        # Short entered at 100 with a 20 point stop: 121 is through it.
        engine.process_tick("NIFTY28MAY2624000CE", "NFO", 121.0)

    assert placed == [("NIFTY28MAY2624000CE", "BUY")]
    kinds = [o["kind"] for o in store.list_orders(run_id)]
    assert "exit_sl" in kinds


def test_a_quiet_tick_places_nothing(api_key):
    sid = _make()
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)

    with patch.object(engine.order_dispatch, "dispatch_order") as dispatch:
        engine.process_tick("NIFTY28MAY2624000CE", "NFO", 101.0)

    assert dispatch.call_count == 0
    assert state.get_run_state(run_id)["legs"]["1"]["ltp"] == 101.0


def test_an_overall_stop_closes_the_whole_run(api_key):
    sid = _make(_config(overall_sl_mtm=500))
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)

    with patch.object(
        engine.order_dispatch,
        "dispatch_order",
        return_value=DispatchResult(ok=True, broker_order_id="X", response={}),
    ):
        # Short 75 at 100. At 110 the loss is 750, past the 500 combined stop.
        engine.process_tick("NIFTY28MAY2624000CE", "NFO", 110.0)

    pending = store.get_run(run_id)
    assert pending.stop_requested_reason == "overall_sl"
    assert pending.stopped_at is None
    assert state.get_run_state(run_id) is not None

    engine.apply_fill(run_id, 1, 110.0, is_entry=False)

    runs = store.list_runs(sid)
    assert runs[0]["stop_reason"] == "overall_sl"
    assert store.get_strategy(sid, USER).status == "stopped"


def test_a_tick_for_an_instrument_no_run_holds_is_ignored(api_key):
    sid = _make()
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)

    with patch.object(engine.order_dispatch, "dispatch_order") as dispatch:
        engine.process_tick("SOMETHING-ELSE", "NFO", 1.0)

    assert dispatch.call_count == 0


def test_peak_and_trough_reach_the_run_row_on_a_rule_driven_stop(api_key):
    # PORTED DEFECT. The original passes peak and trough on only one of its
    # stop paths, so a run closed by an overall stop, a target, a lock-profit
    # floor, the scheduler or the kill switch recorded both as zero.
    sid = _make(_config(overall_sl_mtm=500))
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)

    with patch.object(
        engine.order_dispatch,
        "dispatch_order",
        return_value=DispatchResult(ok=True, broker_order_id="X", response={}),
    ):
        engine.process_tick("NIFTY28MAY2624000CE", "NFO", 95.0)  # +375, sets the peak
        engine.process_tick("NIFTY28MAY2624000CE", "NFO", 110.0)  # -750, breaches

    pending = store.get_run(run_id)
    assert pending.stop_requested_reason == "overall_sl"
    assert pending.stopped_at is None
    engine.apply_fill(run_id, 1, 110.0, is_entry=False)

    run = store.list_runs(sid)[0]
    assert run["pnl_peak"] == pytest.approx(375.0)
    assert run["pnl_trough"] == pytest.approx(-750.0)


def test_a_finished_run_leaves_no_live_state_behind(api_key):
    sid = _make()
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)

    with patch.object(
        engine.order_dispatch,
        "dispatch_order",
        return_value=DispatchResult(ok=True, broker_order_id="X", response={}),
    ):
        result = engine.stop_run(run_id, USER, reason="manual")

    assert result["stop_pending"] is True
    assert state.get_run_state(run_id) is not None

    engine.apply_fill(run_id, 1, 100.0, is_entry=False)

    assert state.get_run_state(run_id) is None
    assert run_id not in state.active_run_ids()


def test_a_flat_run_can_finalize_without_a_broker_api_key(api_key):
    sid = _make()
    run = store.create_run(sid, "sandbox", "sandbox")
    assert store.set_strategy_status(sid, "running", run.id)
    state.init_run_state(run.id, sid, [])

    with (
        patch.object(engine, "_api_key_for", return_value=None),
        patch.object(engine.order_dispatch, "dispatch_order") as dispatch,
        patch.object(engine, "_unsubscribe_run"),
    ):
        result = engine.stop_run(run.id, USER, reason="manual")

    assert result == {"ok": True, "stop_pending": False, "exits": []}
    assert dispatch.call_count == 0
    assert store.get_run(run.id).stopped_at is not None
    assert store.get_strategy(sid, USER).status == "stopped"
    assert state.get_run_state(run.id) is None


def test_a_keyless_stop_with_possible_exposure_is_durable_pending_and_retryable(api_key):
    sid = _make()
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)

    with (
        patch.object(engine, "_api_key_for", return_value=None),
        patch.object(engine.order_dispatch, "dispatch_order") as dispatch,
    ):
        result = engine.stop_run(run_id, USER, reason="manual")

    assert result["ok"] is False
    assert result["stop_pending"] is True
    assert result["exits"] == []
    assert "API key" in result["error"]
    assert dispatch.call_count == 0
    durable = store.get_run(run_id)
    assert durable.stop_requested_reason == "manual"
    assert durable.stopped_at is None
    live = state.get_run_state(run_id)
    assert live["stopping"] is True
    assert live["legs"]["1"]["status"] == "open"


def test_atomic_finalise_loser_keeps_state_subscription_and_terminal_event_ownership(api_key):
    sid = _make()
    run = store.create_run(sid, "sandbox", "sandbox")
    assert store.set_strategy_status(sid, "running", run.id)
    state.init_run_state(run.id, sid, [])
    lock_was_free_at_cas = []

    def lose_terminal_cas(*_args, **_kwargs):
        lock = state.get_state_lock(run.id)
        acquired = lock.acquire(blocking=False)
        lock_was_free_at_cas.append(acquired)
        if acquired:
            lock.release()
        return False

    with (
        patch.object(
            store,
            "finish_run_and_release_strategy",
            side_effect=lose_terminal_cas,
            create=True,
        ),
        patch.object(engine, "_unsubscribe_run") as unsubscribe,
        patch.object(engine, "_emit") as emit,
    ):
        won = engine._finalise(run.id, sid, USER, "manual", "Run stopped (manual)")

    assert won is False
    assert state.get_run_state(run.id) is not None
    assert store.get_run(run.id).stopped_at is None
    assert store.get_strategy(sid, USER).current_run_id == run.id
    assert lock_was_free_at_cas == [True]
    unsubscribe.assert_not_called()
    assert not [call for call in emit.call_args_list if call.args[2] == "run_stopped"]


def test_late_exit_fill_reconciles_durable_pnl_only_after_detached_run_lock_releases(api_key):
    sid = _make()
    run = store.create_run(sid, "sandbox", "sandbox")
    assert run is not None
    state.init_run_state(run.id, sid, [])
    state_lock = state.get_state_lock(run.id)
    with state_lock:
        state._run_state.pop(run.id, None)
    lock_was_free = []

    def observe_reconcile(candidate_run_id):
        assert candidate_run_id == run.id
        acquired = state_lock.acquire(blocking=False)
        lock_was_free.append(acquired)
        if acquired:
            state_lock.release()
        return True

    with patch.object(store, "reconcile_run_pnl", side_effect=observe_reconcile) as reconcile:
        applied = engine.apply_fill(run.id, 1, 101.0, is_entry=False)

    state.clear_run_state(run.id)
    assert applied is False
    reconcile.assert_called_once_with(run.id)
    assert lock_was_free == [True]


def test_late_exit_fill_reconciles_each_durable_position_incarnation(api_key):
    sid = _make()
    run = store.create_run(sid, "sandbox", "sandbox")
    assert run is not None

    facts = [
        ("old-long", "entry", "BUY", 100.0),
        ("old-long", "exit_signal", "SELL", 105.0),
        ("new-short", "entry", "SELL", 120.0),
        ("new-short", "exit_signal", "BUY", 110.0),
    ]
    for position_ref, kind, action, price in facts:
        order = store.record_order(
            run.id,
            1,
            kind,
            {
                "symbol": "NIFTY28MAY2624000CE",
                "exchange": "NFO",
                "action": action,
                "qty": 1,
                "position_ref": position_ref,
                "status": "open",
            },
        )
        assert order is not None
        assert store.update_order(order.id, status="complete", avg_fill_price=price, filled_qty=1)

    # No live state remains, which takes the same detached-state repair path as
    # a late broker correction after finalisation/restart.
    assert engine.apply_fill(run.id, 1, 110.0, is_entry=False) is False
    assert float(store.get_run(run.id).pnl_realized) == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# The tokenless window
#
# OpenAlgo revokes broker tokens at the session reset (03:00 IST by default)
# because Indian broker tokens expire daily. Until the user logs in again there
# is nothing to place an order with, and a positional strategy is still
# holding.
# ---------------------------------------------------------------------------


def test_risk_that_cannot_be_acted_on_reaches_the_audit_trail(api_key):
    # Refusing is correct; pretending to exit would be worse. What matters is
    # that the operator can find out why a position sat past its stop.
    sid = _make(_config(overall_sl_mtm=100))
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    engine._unactionable_runs.discard(run_id)

    with (
        patch.object(engine, "_api_key_for", return_value=None),
        patch.object(engine.order_dispatch, "dispatch_order") as dispatch,
    ):
        engine.process_tick("NIFTY28MAY2624000CE", "NFO", 110.0)

    assert dispatch.call_count == 0
    events = store.list_events(sid)
    critical = [e for e in events if e["severity"] == "critical"]
    assert critical, "an unactionable stop must be recorded, not only logged"
    assert "no broker session" in critical[0]["message"]
    assert store.get_run(run_id).stop_requested_reason == "overall_sl"
    assert state.get_run_state(run_id)["stopping"] is True
    # And the position is still open, which is the correct outcome.
    assert state.get_run_state(run_id)["legs"]["1"]["status"] == "open"


def test_it_is_recorded_once_per_episode_not_once_per_tick(api_key):
    # The tick that fires a stop is followed by every tick after it. One row
    # per tick would make the trail unreadable exactly when it is needed.
    sid = _make(_config(overall_sl_mtm=100))
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    engine._unactionable_runs.discard(run_id)

    with patch.object(engine, "_api_key_for", return_value=None):
        for _ in range(5):
            engine.process_tick("NIFTY28MAY2624000CE", "NFO", 110.0)

    critical = [e for e in store.list_events(sid) if e["severity"] == "critical"]
    assert len(critical) == 1


def test_the_session_returning_is_recorded_too(api_key):
    sid = _make(_config(overall_sl_mtm=100))
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    engine._unactionable_runs.discard(run_id)

    with patch.object(engine, "_api_key_for", return_value=None):
        engine.process_tick("NIFTY28MAY2624000CE", "NFO", 110.0)

    # The user logs back in; the next tick can act.
    with patch.object(
        engine.order_dispatch,
        "dispatch_order",
        return_value=DispatchResult(ok=True, broker_order_id="X", response={}),
    ):
        engine.process_tick("NIFTY28MAY2624000CE", "NFO", 110.0)

    kinds = [e["kind"] for e in store.list_events(sid)]
    assert "recovery_succeeded" in kinds
    assert run_id not in engine._unactionable_runs


def test_a_quiet_tick_with_no_session_records_nothing(api_key):
    # Only risk that actually fired is worth a critical row. A tokenless window
    # on a strategy with nothing to do is not an incident.
    sid = _make()
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)
    engine._unactionable_runs.discard(run_id)

    with patch.object(engine, "_api_key_for", return_value=None):
        engine.process_tick("NIFTY28MAY2624000CE", "NFO", 101.0)

    assert not [e for e in store.list_events(sid) if e["severity"] == "critical"]


def test_synchronous_signal_risk_exit_fill_does_not_end_the_session_run(api_key):
    # Started as a batch strategy and then marked signal. A signal strategy has
    # no start: its run is opened by the first signal, and start_run refuses it
    # by name. What this test is about is the finalisation rule, which reads
    # the kind off the row, so the row is what has to say signal.
    sid = _make()
    run_id = _start(sid).run_id
    _mark_kind(sid, "signal")
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)

    def fill_inline(**_kwargs):
        engine.apply_fill(run_id, 1, 121.0, is_entry=False)
        return DispatchResult(ok=True, broker_order_id="SYNC-RISK-EXIT", response={})

    with patch.object(engine.order_dispatch, "dispatch_order", side_effect=fill_inline):
        engine.process_tick("NIFTY28MAY2624000CE", "NFO", 121.0)

    assert store.get_run(run_id).stopped_at is None
    assert store.get_strategy(sid, USER).current_run_id == run_id
    live = state.get_run_state(run_id)
    assert live is not None
    assert live["legs"]["1"]["status"] == "closed"
