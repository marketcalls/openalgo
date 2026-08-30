"""Strategy engine: run lifecycle and the tick decision path.

The rules are tested in test/risk/ and test_strategy_module_risk.py. What is
tested here is what the engine does about them: what it places, in what order,
what it refuses, and what it leaves behind when something fails partway.

Several cases pin defects from the module this was ported from, and say so.
"""

from unittest.mock import patch

import pytest

# restx_api first: see the note in test_strategy_module_order_dispatch.py.
import restx_api  # noqa: F401
from database import strategy_module_db as store
from services.strategy_module import engine, state
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
        engine.stop_run(run_id, USER, reason="manual")

    assert state.get_run_state(run_id) is None
    assert run_id not in state.active_run_ids()


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
