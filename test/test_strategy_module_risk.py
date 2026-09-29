"""Strategy-module risk translation and run state.

The rules themselves live in services/risk/ and are tested by test/risk/. What
is tested here is the translation on either side of them, plus the run state
the translation reads and writes.

Several of these pin defects present in the module this was ported from. They
are marked, because a reader deciding to "simplify" the adapter back towards
the original needs to know what each guard is for.
"""

import pytest

from services.strategy_module import risk_adapter as ra
from services.strategy_module import state as st


def _leg(**overrides):
    leg = {
        "leg_id": 1,
        "position": "S",
        "symbol": "NIFTY28MAY2624000CE",
        "exchange": "NFO",
        "lots": 1,
        "qty": 75,
        "entry_avg": 100.0,
        "sl_pts": 20,
        "target_pts": 30,
        "trail_x": 0,
        "trail_y": 0,
        "effective_sl": None,
        "effective_target": None,
        "highest_price": None,
        "lowest_price": None,
        "trail_active": False,
        "status": "open",
        "ltp": None,
        "mtm": 0.0,
        "realized_pnl": 0.0,
    }
    leg.update(overrides)
    return leg


def _state(legs, **overrides):
    state = {
        "run_id": 1,
        "strategy_id": 1,
        "pnl_realized": 0.0,
        "pnl_unrealized": 0.0,
        "pnl_total": 0.0,
        "pnl_peak": 0.0,
        "pnl_trough": 0.0,
        "lock_armed": False,
        "lock_floor": None,
        "trail_to_entry_active": False,
        "legs": {str(leg["leg_id"]): leg for leg in legs},
    }
    state.update(overrides)
    return state


# ---------------------------------------------------------------------------
# Side handling
# ---------------------------------------------------------------------------


def test_a_leg_without_a_usable_side_is_refused_not_defaulted():
    # PORTED DEFECT. The original never writes `position` on signal-mode legs,
    # and its evaluator treats anything that is not "B" as a short. Those legs
    # were evaluated with an inverted sign: P&L, stop and target all pointed the
    # wrong way and the stop fired on a FAVOURABLE move. Defaulting is the bug;
    # raising is the fix.
    for bad in (None, "", "LONG", "buy", "x"):
        with pytest.raises(ValueError):
            ra.leg_to_position_risk(_leg(position=bad))


def test_a_short_leg_is_evaluated_as_a_short():
    leg = _leg(position="S", entry_avg=100.0, sl_pts=20, target_pts=30)

    risk = ra.leg_to_position_risk(leg)
    assert risk.stop_price == 120.0  # above entry for a short
    assert risk.target_price == 70.0  # below entry for a short

    # Price rising is against a short.
    decision = ra.evaluate_leg(dict(leg), 121.0)
    assert decision.breached and decision.reason == "sl"
    assert decision.pnl < 0


def test_a_long_leg_is_evaluated_as_a_long():
    leg = _leg(position="B", entry_avg=100.0, sl_pts=20, target_pts=30)

    risk = ra.leg_to_position_risk(leg)
    assert risk.stop_price == 80.0  # below entry for a long
    assert risk.target_price == 130.0

    decision = ra.evaluate_leg(dict(leg), 79.0)
    assert decision.breached and decision.reason == "sl"
    assert decision.pnl < 0

    decision = ra.evaluate_leg(dict(leg), 131.0)
    assert decision.breached and decision.reason == "target"
    assert decision.pnl > 0


# ---------------------------------------------------------------------------
# Trailing
# ---------------------------------------------------------------------------


def test_a_continuous_trail_follows_the_favourable_extreme_at_a_fixed_gap():
    # X alone: the stop keeps a constant X-point distance behind the best price
    # the leg has seen.
    leg = _leg(position="B", entry_avg=100.0, sl_pts=10, trail_x=10, trail_y=0)

    ra.evaluate_leg(leg, 115.0)
    first = leg["effective_sl"]
    assert first == pytest.approx(105.0)

    ra.evaluate_leg(leg, 120.0)
    assert leg["effective_sl"] == pytest.approx(110.0)
    assert leg["highest_price"] == 120.0


def test_a_stepped_trail_advances_in_whole_steps():
    # X and Y: arms once the leg is X in front, then advances Y at a time.
    leg = _leg(position="B", entry_avg=100.0, sl_pts=10, trail_x=10, trail_y=5)

    ra.evaluate_leg(leg, 105.0)
    assert leg["effective_sl"] == pytest.approx(90.0)  # not armed yet

    ra.evaluate_leg(leg, 110.0)
    armed = leg["effective_sl"]
    assert armed > 90.0
    assert leg["trail_active"] is True


def test_a_trailed_stop_never_retreats():
    # The whole value of a trail is that protection already earned is kept. A
    # stop that slid back on a pullback would hand it straight back.
    leg = _leg(position="B", entry_avg=100.0, sl_pts=10, trail_x=10, trail_y=0)

    ra.evaluate_leg(leg, 130.0)
    high_water = leg["effective_sl"]

    ra.evaluate_leg(leg, 118.0)
    assert leg["effective_sl"] == high_water


def test_a_stepped_trail_anchors_to_the_configured_stop_not_the_trailed_one():
    # Handing the core the already-trailed stop as the anchor would compound
    # the advance on every tick, so the stop would run away from the price.
    leg = _leg(position="B", entry_avg=100.0, sl_pts=10, trail_x=10, trail_y=5, effective_sl=95.0)

    risk = ra.leg_to_position_risk(leg)
    assert risk.stop_price == 95.0  # live level, used for the breach test
    assert risk.initial_stop_price == 90.0  # configured level, the step anchor


def test_a_tick_with_no_usable_price_changes_nothing():
    leg = _leg(position="B", entry_avg=100.0, sl_pts=10)
    ra.evaluate_leg(leg, 120.0)
    before = dict(leg)

    decision = ra.evaluate_leg(leg, None)

    assert decision.evaluated is False
    assert decision.breached is False
    assert leg["effective_sl"] == before["effective_sl"]
    assert leg["highest_price"] == before["highest_price"]


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def test_run_pnl_marks_from_entry_rather_than_a_stale_leg_field():
    # PORTED DEFECT. The original sums a per-leg `mtm` written on an earlier
    # pass, so a leg whose mtm was never refreshed silently poisons the total
    # that every strategy-level rule is judged against. Here the total is marked
    # from entry, quantity and last price, so a stale field cannot reach it.
    leg = _leg(position="B", entry_avg=100.0, qty=10, ltp=110.0, mtm=-99999.0)

    realized, unrealized = ra.run_pnl(_state([leg]))

    assert realized == 0.0
    assert unrealized == pytest.approx(100.0)  # (110 - 100) * 10, not the -99999


def test_a_closed_leg_contributes_its_realized_figure():
    open_leg = _leg(leg_id=1, position="B", entry_avg=100.0, qty=10, ltp=105.0)
    closed_leg = _leg(leg_id=2, status="closed", realized_pnl=250.0, ltp=None)

    realized, unrealized = ra.run_pnl(_state([open_leg, closed_leg]))

    assert realized == pytest.approx(250.0)
    assert unrealized == pytest.approx(50.0)


def test_peak_and_trough_are_written_on_every_pass_not_only_on_a_breach():
    # PORTED DEFECT. The original persists peak and trough on only one of its
    # several stop paths, so a run closed by an overall stop, a target, a
    # lock-profit floor, the scheduler or the kill switch recorded both as zero
    # despite having had real numbers all session.
    leg = _leg(position="B", entry_avg=100.0, qty=10, ltp=120.0)
    state = _state([leg])
    strategy = {"overall_sl_mtm": None, "overall_target_mtm": None}

    ra.evaluate_run(state, strategy)
    assert state["pnl_peak"] == pytest.approx(200.0)

    leg["ltp"] = 90.0
    ra.evaluate_run(state, strategy)

    assert state["pnl_peak"] == pytest.approx(200.0)  # ratchets, does not reset
    assert state["pnl_trough"] == pytest.approx(-100.0)
    assert state["pnl_total"] == pytest.approx(-100.0)


def test_the_overall_stop_is_entered_positive_and_applied_negative():
    leg = _leg(position="B", entry_avg=100.0, qty=10, ltp=60.0)  # -400
    state = _state([leg])

    decision = ra.evaluate_run(state, {"overall_sl_mtm": 300, "overall_target_mtm": None})

    assert decision.breached and decision.reason == "combined_sl"


def test_the_overall_target_fires_on_the_total():
    leg = _leg(position="B", entry_avg=100.0, qty=10, ltp=160.0)  # +600
    state = _state([leg])

    decision = ra.evaluate_run(state, {"overall_sl_mtm": None, "overall_target_mtm": 500})

    assert decision.breached and decision.reason == "combined_target"


# ---------------------------------------------------------------------------
# Lock profit
# ---------------------------------------------------------------------------


def test_lock_mode_holds_a_static_floor():
    leg = _leg(position="B", entry_avg=100.0, qty=10, ltp=250.0)  # +1500
    state = _state([leg])
    strategy = {
        "lock_profit": {"mode": "lock", "if_profit_reaches": 1500, "lock_profit": 800},
    }

    armed = ra.evaluate_run(state, strategy)
    assert armed.lock_armed is True
    assert state["lock_floor"] == pytest.approx(800.0)

    # Rising further must NOT raise a static floor.
    leg["ltp"] = 400.0  # +3000
    ra.evaluate_run(state, strategy)
    assert state["lock_floor"] == pytest.approx(800.0)

    # Falling back through it exits.
    leg["ltp"] = 170.0  # +700
    breach = ra.evaluate_run(state, strategy)
    assert breach.breached and breach.reason == "lock_profit"


def test_lock_and_trail_raises_the_floor_as_the_peak_rises():
    leg = _leg(position="B", entry_avg=100.0, qty=10, ltp=250.0)  # +1500
    state = _state([leg])
    strategy = {
        "lock_profit": {
            "mode": "lock_and_trail",
            "if_profit_reaches": 1500,
            "lock_profit": 800,
            "trail_step": 100,
        },
    }

    ra.evaluate_run(state, strategy)
    first_floor = state["lock_floor"]

    leg["ltp"] = 400.0  # +3000
    ra.evaluate_run(state, strategy)

    assert state["lock_floor"] > first_floor
    assert state["lock_floor"] == pytest.approx(2900.0)  # peak 3000 less the 100 step


def test_a_trail_step_is_ignored_in_plain_lock_mode():
    # A static floor that quietly started rising is a different product from
    # the one the user configured.
    state = _state([_leg(position="B", entry_avg=100.0, qty=10, ltp=250.0)])
    strategy = {
        "lock_profit": {
            "mode": "lock",
            "if_profit_reaches": 1500,
            "lock_profit": 800,
            "trail_step": 100,
        },
    }

    risk = ra.run_to_aggregate_risk(state, strategy)

    assert risk.lock_trail_step is None


# ---------------------------------------------------------------------------
# Trail to entry
# ---------------------------------------------------------------------------


def test_trail_to_entry_moves_the_other_open_legs_and_leaves_the_trigger_alone():
    a = _leg(leg_id=1, position="B", entry_avg=100.0, qty=10, ltp=95.0)
    b = _leg(leg_id=2, position="B", entry_avg=200.0, qty=10, ltp=210.0)
    c = _leg(leg_id=3, position="S", entry_avg=300.0, qty=10, ltp=290.0)
    state = _state([a, b, c])

    moved = ra.trail_open_legs_to_entry(state, triggering_leg_id=1)

    assert "1" not in moved
    assert b["effective_sl"] == pytest.approx(200.0)
    assert c["effective_sl"] == pytest.approx(300.0)
    assert state["trail_to_entry_active"] is True


def test_trail_to_entry_bypasses_the_overall_stop_for_the_rest_of_the_run():
    # Once the book has been made risk free, the combined stop is deliberately
    # out of the picture; leaving it live would close the remaining legs on a
    # loss the run can no longer take.
    leg = _leg(position="B", entry_avg=100.0, qty=10, ltp=50.0)  # -500
    state = _state([leg], trail_to_entry_active=True)

    decision = ra.evaluate_run(state, {"overall_sl_mtm": 100, "overall_target_mtm": None})

    assert decision.breached is False


# ---------------------------------------------------------------------------
# Run state
# ---------------------------------------------------------------------------


def test_init_writes_a_side_for_every_leg_and_refuses_one_without():
    legs = [
        {"leg_id": 1, "position": "S", "symbol": "A", "exchange": "NFO", "quantity": 75},
        {"leg_id": 2, "position": "B", "symbol": "B", "exchange": "NFO", "quantity": 50},
    ]
    state = st.init_run_state(101, 1, legs)
    try:
        assert state["legs"]["1"]["position"] == "S"
        assert state["legs"]["2"]["position"] == "B"
    finally:
        st.clear_run_state(101)

    with pytest.raises(ValueError):
        st.init_run_state(102, 1, [{"leg_id": 1, "symbol": "A", "exchange": "NFO", "quantity": 1}])
    st.clear_run_state(102)


def test_get_run_state_hands_back_a_copy_so_a_reader_cannot_mutate_the_run():
    st.init_run_state(
        103, 1, [{"leg_id": 1, "position": "B", "symbol": "A", "exchange": "NFO", "quantity": 1}]
    )
    try:
        copy = st.get_run_state(103)
        copy["legs"]["1"]["entry_avg"] = 999.0

        assert st.get_run_state(103)["legs"]["1"]["entry_avg"] == 0.0
    finally:
        st.clear_run_state(103)


def test_clearing_a_run_drops_its_lock_as_well_as_its_state():
    # A lock left behind is a small leak per run, in a worker that never
    # restarts.
    st.init_run_state(
        104, 1, [{"leg_id": 1, "position": "B", "symbol": "A", "exchange": "NFO", "quantity": 1}]
    )
    st.get_state_lock(104)

    st.clear_run_state(104)

    assert st.get_run_state(104) is None
    assert 104 not in st.active_run_ids()
    assert 104 not in st._state_locks


def test_favorable_peak_points_is_derived_for_both_sides():
    long_leg = _leg(position="B", entry_avg=100.0, highest_price=130.0)
    short_leg = _leg(position="S", entry_avg=100.0, lowest_price=70.0)

    assert st.favorable_peak_points(long_leg) == pytest.approx(30.0)
    assert st.favorable_peak_points(short_leg) == pytest.approx(30.0)
    # Never negative: a leg that has only moved against itself has earned no
    # trail, and a negative peak would arm one.
    assert st.favorable_peak_points(_leg(position="B", entry_avg=100.0, highest_price=90.0)) == 0.0


def test_subscribed_symbols_covers_configured_and_open_legs_only():
    legs = {
        "1": _leg(leg_id=1, symbol="A", status="open"),
        "2": _leg(leg_id=2, symbol="B", status="configured"),
        "3": _leg(leg_id=3, symbol="C", status="closed"),
    }
    state = _state([])
    state["legs"] = legs

    symbols = st.subscribed_symbols(state)

    assert ("A", "NFO") in symbols
    assert ("B", "NFO") in symbols
    assert ("C", "NFO") not in symbols


def test_a_leg_that_exited_and_can_re_enter_still_contributes_its_realized_profit():
    # Signal mode: a leg exits back to "configured" so the same symbol can be
    # signalled again the same day. Keying realized P&L on status == "closed"
    # dropped that leg's profit out of the run total entirely, and every
    # strategy-level rule was then judged against a number the run never made.
    reentrant = _leg(leg_id=1, status="configured", realized_pnl=500.0, ltp=None)
    open_leg = _leg(leg_id=2, position="B", entry_avg=100.0, qty=10, ltp=110.0)

    realized, unrealized = ra.run_pnl(_state([reentrant, open_leg]))

    assert realized == pytest.approx(500.0)
    assert unrealized == pytest.approx(100.0)


def test_a_leg_that_never_traded_contributes_nothing():
    never = _leg(leg_id=1, status="configured", realized_pnl=0.0, entry_avg=0.0, ltp=None)

    realized, unrealized = ra.run_pnl(_state([never]))

    assert realized == 0.0
    assert unrealized == 0.0


# ---------------------------------------------------------------------------
# Points or percent
#
# The unit is a property of the leg, and risk_adapter is the only place that
# knows about it: services/risk/ speaks points from entry and nothing else, so
# a percent leg is translated on the way in rather than the core learning a
# second language.
# ---------------------------------------------------------------------------


def _unit_leg(**over):
    leg = {
        "leg_id": 1,
        "position": "S",
        "entry_avg": 2500.0,
        "qty": 75,
        "sl_pts": 2,
        "target_pts": 4,
    }
    leg.update(over)
    return leg


def test_a_percent_leg_is_measured_against_its_own_entry():
    """2 percent of a 2500 entry is 50 points, not 2."""
    risk = ra.leg_to_position_risk(_unit_leg(risk_unit="percent"))

    # Short: the stop sits above entry, the target below.
    assert risk.stop_price == pytest.approx(2550.0)
    assert risk.target_price == pytest.approx(2400.0)


def test_a_points_leg_is_unchanged_by_the_unit_existing():
    risk = ra.leg_to_position_risk(_unit_leg(risk_unit="points"))

    assert risk.stop_price == pytest.approx(2502.0)
    assert risk.target_price == pytest.approx(2496.0)


def test_a_leg_written_before_the_unit_existed_is_read_as_points():
    """Every stored strategy predates this field. None of them may move."""
    without = ra.leg_to_position_risk(_unit_leg())
    explicit = ra.leg_to_position_risk(_unit_leg(risk_unit="points"))

    assert without.stop_price == explicit.stop_price
    assert without.target_price == explicit.target_price


def test_a_long_percent_leg_stops_below_and_targets_above():
    risk = ra.leg_to_position_risk(
        _unit_leg(position="B", entry_avg=1000.0, sl_pts=10, target_pts=25, risk_unit="percent")
    )

    assert risk.stop_price == pytest.approx(900.0)
    assert risk.target_price == pytest.approx(1250.0)


def test_a_percent_trail_advances_in_percent_of_entry():
    risk = ra.leg_to_position_risk(
        _unit_leg(entry_avg=1000.0, trail_x=5, trail_y=2, risk_unit="percent")
    )

    assert risk.trail_trigger == pytest.approx(50.0)
    assert risk.trail_step == pytest.approx(20.0)
    assert risk.trailing_enabled is True


def test_a_percent_leg_with_no_confirmed_entry_gets_no_levels():
    """A percent of nothing is not a stop at the entry price.

    The leg has no fill yet, so there is no price to measure a percentage
    against. Deriving one from zero would put the stop on top of the entry and
    fire it on the first tick.
    """
    risk = ra.leg_to_position_risk(_unit_leg(entry_avg=0.0, risk_unit="percent"))

    assert risk.stop_price is None
    assert risk.target_price is None
    assert risk.trailing_enabled is False
