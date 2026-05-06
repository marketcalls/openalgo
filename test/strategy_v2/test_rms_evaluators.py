"""Phase 3 — RMS rule evaluator tests.

Pure-function tests for the per-leg target / SL / trail X-Y rules. No DB,
no event bus, no broker. Validates the math on synthetic LTP scenarios.

Cover:
  - Long vs short direction handling
  - pts vs pct unit interchange
  - Tick-size snapping at every price write
  - Trail X/Y floor-division ratchet (5pt move with X=1,Y=2 → 5 advances)
  - One-way ratchet (price retracement does not lower SL)
  - Sub-tick movements ignored
  - Initial SL computation vs trail-advanced current_sl_price
"""

from __future__ import annotations

import pytest

from services.strategy.rms_evaluators import (
    evaluate_sl,
    evaluate_target,
    evaluate_trail,
    direction_of,
    dir_sign,
    to_price_delta,
)


# ===========================================================================
# Direction helpers
# ===========================================================================


def test_direction_of_long():
    assert direction_of(50) == "long"
    assert dir_sign("long") == 1


def test_direction_of_short():
    assert direction_of(-50) == "short"
    assert dir_sign("short") == -1


def test_to_price_delta_pts_passes_through():
    assert to_price_delta(5.0, "pts", 100.0) == 5.0


def test_to_price_delta_pct_uses_reference():
    # 2% of 1000 = 20
    assert to_price_delta(2.0, "pct", 1000.0) == 20.0


def test_to_price_delta_unknown_unit():
    with pytest.raises(ValueError):
        to_price_delta(1.0, "lots", 100.0)  # type: ignore[arg-type]


# ===========================================================================
# Target evaluator — long
# ===========================================================================


def test_target_long_pts_not_yet_hit():
    d = evaluate_target(
        enabled=True, target_value=10.0, target_unit="pts",
        avg_entry=1500.0, ltp=1505.0, direction="long", tick_size=0.05,
    )
    assert d.triggered is False
    assert d.target_price == 1510.0


def test_target_long_pts_hit_exact():
    d = evaluate_target(
        enabled=True, target_value=10.0, target_unit="pts",
        avg_entry=1500.0, ltp=1510.0, direction="long", tick_size=0.05,
    )
    assert d.triggered is True


def test_target_long_pts_overshoot():
    d = evaluate_target(
        enabled=True, target_value=10.0, target_unit="pts",
        avg_entry=1500.0, ltp=1520.0, direction="long", tick_size=0.05,
    )
    assert d.triggered is True


def test_target_long_pct():
    # 2% of 1500 = 30 → target = 1530
    d = evaluate_target(
        enabled=True, target_value=2.0, target_unit="pct",
        avg_entry=1500.0, ltp=1530.0, direction="long", tick_size=0.05,
    )
    assert d.triggered is True
    assert d.target_price == 1530.0


def test_target_long_disabled():
    d = evaluate_target(
        enabled=False, target_value=10.0, target_unit="pts",
        avg_entry=1500.0, ltp=2000.0, direction="long", tick_size=0.05,
    )
    assert d.triggered is False


# ===========================================================================
# Target evaluator — short
# ===========================================================================


def test_target_short_pts_not_yet_hit():
    d = evaluate_target(
        enabled=True, target_value=10.0, target_unit="pts",
        avg_entry=1500.0, ltp=1495.0, direction="short", tick_size=0.05,
    )
    assert d.triggered is False
    assert d.target_price == 1490.0


def test_target_short_pts_hit():
    d = evaluate_target(
        enabled=True, target_value=10.0, target_unit="pts",
        avg_entry=1500.0, ltp=1490.0, direction="short", tick_size=0.05,
    )
    assert d.triggered is True


def test_target_short_pct():
    # 2% of 1500 = 30 → short target = 1470
    d = evaluate_target(
        enabled=True, target_value=2.0, target_unit="pct",
        avg_entry=1500.0, ltp=1470.0, direction="short", tick_size=0.05,
    )
    assert d.triggered is True


# ===========================================================================
# Target — tick-size snapping
# ===========================================================================


def test_target_long_snaps_down_to_tick():
    """Favorable direction for long target = round DOWN (easier to hit)."""
    d = evaluate_target(
        enabled=True, target_value=10.07, target_unit="pts",
        avg_entry=1500.0, ltp=0, direction="long", tick_size=0.05,
    )
    # Raw 1510.07 → snap DOWN to 1510.05
    assert d.target_price == 1510.05


def test_target_short_snaps_up_to_tick():
    """Favorable direction for short target = round UP (easier to hit)."""
    d = evaluate_target(
        enabled=True, target_value=10.07, target_unit="pts",
        avg_entry=1500.0, ltp=10000.0, direction="short", tick_size=0.05,
    )
    # Raw 1500 - 10.07 = 1489.93 → snap UP (away from entry) to 1489.95
    assert d.target_price == 1489.95


# ===========================================================================
# SL evaluator — long
# ===========================================================================


def test_sl_long_pts_not_yet_hit():
    d = evaluate_sl(
        enabled=True, sl_value=10.0, sl_unit="pts",
        avg_entry=1500.0, ltp=1495.0, direction="long", tick_size=0.05,
    )
    assert d.triggered is False
    assert d.sl_price == 1490.0


def test_sl_long_pts_hit():
    d = evaluate_sl(
        enabled=True, sl_value=10.0, sl_unit="pts",
        avg_entry=1500.0, ltp=1490.0, direction="long", tick_size=0.05,
    )
    assert d.triggered is True


def test_sl_long_uses_current_sl_price_override():
    """When current_sl_price is set (e.g. after a trail advance), use it
    directly — ignore sl_value-derived initial SL."""
    d = evaluate_sl(
        enabled=True, sl_value=10.0, sl_unit="pts",
        avg_entry=1500.0, ltp=1503.0, direction="long", tick_size=0.05,
        current_sl_price=1505.0,  # advanced via trail
    )
    # Initial SL would be 1490 (not yet hit at ltp=1503).
    # But current_sl_price is 1505 — ltp 1503 IS below 1505 → triggered.
    assert d.triggered is True
    assert d.sl_price == 1505.0


def test_sl_long_disabled():
    d = evaluate_sl(
        enabled=False, sl_value=10.0, sl_unit="pts",
        avg_entry=1500.0, ltp=0, direction="long", tick_size=0.05,
    )
    assert d.triggered is False


# ===========================================================================
# SL evaluator — short
# ===========================================================================


def test_sl_short_pts_not_yet_hit():
    d = evaluate_sl(
        enabled=True, sl_value=10.0, sl_unit="pts",
        avg_entry=1500.0, ltp=1505.0, direction="short", tick_size=0.05,
    )
    assert d.triggered is False
    assert d.sl_price == 1510.0


def test_sl_short_hit():
    d = evaluate_sl(
        enabled=True, sl_value=10.0, sl_unit="pts",
        avg_entry=1500.0, ltp=1510.0, direction="short", tick_size=0.05,
    )
    assert d.triggered is True


def test_sl_short_pct():
    # 2% of 1500 = 30 → SL above for short = 1530
    d = evaluate_sl(
        enabled=True, sl_value=2.0, sl_unit="pct",
        avg_entry=1500.0, ltp=1530.0, direction="short", tick_size=0.05,
    )
    assert d.triggered is True


# ===========================================================================
# SL — tick-size snapping (FAVORABLE = looser stop)
# ===========================================================================


def test_sl_long_snaps_down_to_tick_for_looser_stop():
    """Long SL is below entry; favorable = round DOWN (looser stop, more room)."""
    d = evaluate_sl(
        enabled=True, sl_value=10.07, sl_unit="pts",
        avg_entry=1500.0, ltp=0, direction="long", tick_size=0.05,
    )
    # Raw 1500 - 10.07 = 1489.93 → snap DOWN to 1489.90 (looser)
    assert d.sl_price == 1489.90


def test_sl_short_snaps_up_to_tick_for_looser_stop():
    """Short SL is above entry; favorable = round UP (looser stop, more room)."""
    d = evaluate_sl(
        enabled=True, sl_value=10.07, sl_unit="pts",
        avg_entry=1500.0, ltp=0, direction="short", tick_size=0.05,
    )
    # Raw 1500 + 10.07 = 1510.07 → snap UP to 1510.10
    assert d.sl_price == 1510.10


# ===========================================================================
# Trail X/Y — long, basic ratchet
# ===========================================================================


def test_trail_long_no_movement_yet():
    d = evaluate_trail(
        enabled=True, trail_x=1.0, trail_y=2.0, trail_unit="pts",
        avg_entry=1500.0, ltp=1500.0, direction="long", tick_size=0.05,
        last_anchor=1500.0, current_sl_price=1490.0,
    )
    assert d.advanced is False


def test_trail_long_sub_x_movement_ignored():
    d = evaluate_trail(
        enabled=True, trail_x=1.0, trail_y=2.0, trail_unit="pts",
        avg_entry=1500.0, ltp=1500.5, direction="long", tick_size=0.05,
        last_anchor=1500.0, current_sl_price=1490.0,
    )
    assert d.advanced is False


def test_trail_long_one_x_advances_one_y():
    """1pt favorable move → 1 advance × 2pt = SL moves up by 2."""
    d = evaluate_trail(
        enabled=True, trail_x=1.0, trail_y=2.0, trail_unit="pts",
        avg_entry=1500.0, ltp=1501.0, direction="long", tick_size=0.05,
        last_anchor=1500.0, current_sl_price=1490.0,
    )
    assert d.advanced is True
    assert d.advances == 1
    assert d.new_sl_price == 1492.0
    assert d.new_anchor == 1501.0


def test_trail_long_floor_division_multiple_advances():
    """5pt favorable move with X=1,Y=2 → 5 advances × 2 = SL moves up 10pt."""
    d = evaluate_trail(
        enabled=True, trail_x=1.0, trail_y=2.0, trail_unit="pts",
        avg_entry=1500.0, ltp=1505.0, direction="long", tick_size=0.05,
        last_anchor=1500.0, current_sl_price=1490.0,
    )
    assert d.advanced is True
    assert d.advances == 5
    assert d.new_sl_price == 1500.0  # 1490 + 5*2 = 1500
    assert d.new_anchor == 1505.0


def test_trail_long_partial_move_floors():
    """3.7pt favorable with X=1 → 3 advances (floor), not 4."""
    d = evaluate_trail(
        enabled=True, trail_x=1.0, trail_y=2.0, trail_unit="pts",
        avg_entry=1500.0, ltp=1503.7, direction="long", tick_size=0.05,
        last_anchor=1500.0, current_sl_price=1490.0,
    )
    assert d.advances == 3
    assert d.new_sl_price == 1496.0  # 1490 + 3*2
    assert d.new_anchor == 1503.0  # 1500 + 3*1


# ===========================================================================
# Trail X/Y — one-way ratchet (the safety property)
# ===========================================================================


def test_trail_long_no_relax_on_retracement():
    """If price moves favorably then retraces, the SL must NOT move down.

    This is the simulation: long leg started at 1500, advanced to 1505,
    SL is now at 1500. Price retraces to 1502. Trail evaluator must not
    advance the SL backwards.
    """
    d = evaluate_trail(
        enabled=True, trail_x=1.0, trail_y=2.0, trail_unit="pts",
        avg_entry=1500.0, ltp=1502.0, direction="long", tick_size=0.05,
        last_anchor=1505.0,  # already advanced 5 times
        current_sl_price=1500.0,
    )
    # ltp=1502, anchor=1505 → favorable = (1502-1505)*+1 = -3 (negative!)
    # → no advance.
    assert d.advanced is False


def test_trail_continues_from_advanced_anchor():
    """After a 5-advance move, anchor sits at 1505. Another 1pt favorable
    move (to 1506) should produce exactly 1 more advance."""
    d = evaluate_trail(
        enabled=True, trail_x=1.0, trail_y=2.0, trail_unit="pts",
        avg_entry=1500.0, ltp=1506.0, direction="long", tick_size=0.05,
        last_anchor=1505.0, current_sl_price=1500.0,
    )
    assert d.advances == 1
    assert d.new_sl_price == 1502.0  # 1500 + 2
    assert d.new_anchor == 1506.0


# ===========================================================================
# Trail X/Y — short
# ===========================================================================


def test_trail_short_favorable_is_downward():
    """For shorts, favorable = price DROPS. 5pt drop with X=1,Y=2 →
    SL moves DOWN by 10."""
    d = evaluate_trail(
        enabled=True, trail_x=1.0, trail_y=2.0, trail_unit="pts",
        avg_entry=1500.0, ltp=1495.0, direction="short", tick_size=0.05,
        last_anchor=1500.0, current_sl_price=1510.0,
    )
    assert d.advanced is True
    assert d.advances == 5
    assert d.new_sl_price == 1500.0  # 1510 - 5*2
    assert d.new_anchor == 1495.0


def test_trail_short_no_advance_on_upward_move():
    """Short with price RISING — adverse, no trail advance."""
    d = evaluate_trail(
        enabled=True, trail_x=1.0, trail_y=2.0, trail_unit="pts",
        avg_entry=1500.0, ltp=1503.0, direction="short", tick_size=0.05,
        last_anchor=1500.0, current_sl_price=1510.0,
    )
    assert d.advanced is False


# ===========================================================================
# Trail X/Y — tick-size snapping interacts with one-way ratchet
# ===========================================================================


def test_trail_sub_tick_advance_collapsed_to_no_op():
    """If the computed advance, after tick-snap, doesn't actually improve
    the SL, no advance is recorded. This protects against flapping events
    when X*Y < tick_size."""
    # X=0.01, Y=0.01 — sub-tick on a 0.05-tick instrument.
    # Computed new SL = 1490.01 → snaps to 1490.00 (or 1490.05 favorable);
    # depending on rounding this may or may not advance vs current.
    d = evaluate_trail(
        enabled=True, trail_x=0.01, trail_y=0.01, trail_unit="pts",
        avg_entry=1500.0, ltp=1500.01, direction="long", tick_size=0.05,
        last_anchor=1500.0, current_sl_price=1490.0,
    )
    # 0.01 favorable / 0.01 X = 1 advance; new raw SL = 1490.01
    # round_to_tick favorable BUY (long sl) = round DOWN → 1490.00
    # That doesn't IMPROVE on current 1490.0 → advanced=False
    assert d.advanced is False


def test_trail_pct_unit():
    """1% trail X on entry=1500 → x_delta=15. 30pt move = 2 advances."""
    d = evaluate_trail(
        enabled=True, trail_x=1.0, trail_y=0.5, trail_unit="pct",
        avg_entry=1500.0, ltp=1530.0, direction="long", tick_size=0.05,
        last_anchor=1500.0, current_sl_price=1480.0,
    )
    # x_delta = 15 (1% of 1500), y_delta = 7.5 (0.5% of 1500)
    # favorable = 30, advances = floor(30/15) = 2
    # new_sl = 1480 + 2*7.5 = 1495
    assert d.advances == 2
    assert d.new_sl_price == 1495.0
    assert d.new_anchor == 1530.0  # 1500 + 2*15


# ===========================================================================
# Trail edge cases
# ===========================================================================


def test_trail_disabled_returns_no_advance():
    d = evaluate_trail(
        enabled=False, trail_x=1.0, trail_y=2.0, trail_unit="pts",
        avg_entry=1500.0, ltp=1505.0, direction="long", tick_size=0.05,
        last_anchor=1500.0, current_sl_price=1490.0,
    )
    assert d.advanced is False


def test_trail_zero_x_returns_no_advance():
    d = evaluate_trail(
        enabled=True, trail_x=0.0, trail_y=2.0, trail_unit="pts",
        avg_entry=1500.0, ltp=1505.0, direction="long", tick_size=0.05,
        last_anchor=1500.0, current_sl_price=1490.0,
    )
    assert d.advanced is False


def test_trail_zero_y_returns_no_advance():
    d = evaluate_trail(
        enabled=True, trail_x=1.0, trail_y=0.0, trail_unit="pts",
        avg_entry=1500.0, ltp=1505.0, direction="long", tick_size=0.05,
        last_anchor=1500.0, current_sl_price=1490.0,
    )
    assert d.advanced is False
