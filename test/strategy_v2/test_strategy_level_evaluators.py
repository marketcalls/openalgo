"""Phase 4 — strategy-level evaluator tests (pure-function).

Covers overall SL / target / profit lock arm + floor / trail-to-entry. All
evaluators take aggregate MTM (computed by the engine elsewhere) and return
a typed decision.
"""

from __future__ import annotations

import pytest

from services.strategy.rms_evaluators import (
    evaluate_overall_sl,
    evaluate_overall_target,
    evaluate_profit_lock_arm,
    evaluate_profit_lock_floor,
    evaluate_trail_to_entry,
)


# ===========================================================================
# Overall SL
# ===========================================================================


def test_overall_sl_disabled():
    d = evaluate_overall_sl(enabled=False, overall_sl_abs=5000, aggregate_mtm=-9999)
    assert d.triggered is False


def test_overall_sl_not_yet_hit():
    d = evaluate_overall_sl(enabled=True, overall_sl_abs=5000, aggregate_mtm=-4999)
    assert d.triggered is False


def test_overall_sl_hit_exact():
    d = evaluate_overall_sl(enabled=True, overall_sl_abs=5000, aggregate_mtm=-5000)
    assert d.triggered is True
    assert d.rule == "OVERALL_SL"
    assert d.threshold == -5000


def test_overall_sl_overshoot():
    d = evaluate_overall_sl(enabled=True, overall_sl_abs=5000, aggregate_mtm=-7000)
    assert d.triggered is True


def test_overall_sl_accepts_positive_value_inverts_internally():
    """User stores 5000 (positive) meaning "lose at most ₹5000". Engine
    inverts to -5000 internally."""
    d = evaluate_overall_sl(enabled=True, overall_sl_abs=5000, aggregate_mtm=-5000)
    assert d.threshold == -5000


def test_overall_sl_disabled_when_value_none():
    d = evaluate_overall_sl(enabled=True, overall_sl_abs=None, aggregate_mtm=-9999)
    assert d.triggered is False


# ===========================================================================
# Overall Target
# ===========================================================================


def test_overall_target_disabled():
    d = evaluate_overall_target(enabled=False, overall_target_abs=10000, aggregate_mtm=20000)
    assert d.triggered is False


def test_overall_target_not_yet_hit():
    d = evaluate_overall_target(enabled=True, overall_target_abs=10000, aggregate_mtm=9999)
    assert d.triggered is False


def test_overall_target_hit():
    d = evaluate_overall_target(enabled=True, overall_target_abs=10000, aggregate_mtm=10000)
    assert d.triggered is True
    assert d.rule == "OVERALL_TARGET"
    assert d.threshold == 10000


def test_overall_target_overshoot():
    d = evaluate_overall_target(enabled=True, overall_target_abs=10000, aggregate_mtm=15000)
    assert d.triggered is True


# ===========================================================================
# Profit lock — arm
# ===========================================================================


def test_profit_lock_disabled_never_arms():
    assert evaluate_profit_lock_arm(
        enabled=False, lock_at_abs=5000, peak_mtm=10000, already_armed=False,
    ) is False


def test_profit_lock_arms_at_threshold():
    assert evaluate_profit_lock_arm(
        enabled=True, lock_at_abs=5000, peak_mtm=5000, already_armed=False,
    ) is True


def test_profit_lock_arms_above_threshold():
    assert evaluate_profit_lock_arm(
        enabled=True, lock_at_abs=5000, peak_mtm=8000, already_armed=False,
    ) is True


def test_profit_lock_does_not_re_arm():
    """Latch — once armed, never re-evaluates."""
    assert evaluate_profit_lock_arm(
        enabled=True, lock_at_abs=5000, peak_mtm=8000, already_armed=True,
    ) is False


def test_profit_lock_does_not_arm_below_threshold():
    assert evaluate_profit_lock_arm(
        enabled=True, lock_at_abs=5000, peak_mtm=4999, already_armed=False,
    ) is False


# ===========================================================================
# Profit lock — floor
# ===========================================================================


def test_profit_lock_floor_only_active_when_armed():
    """Not armed → never triggers, even at extreme drawdown."""
    d = evaluate_profit_lock_floor(armed=False, lock_min_abs=3000, aggregate_mtm=-9999)
    assert d.triggered is False


def test_profit_lock_floor_holds_above_floor():
    d = evaluate_profit_lock_floor(armed=True, lock_min_abs=3000, aggregate_mtm=4000)
    assert d.triggered is False


def test_profit_lock_floor_triggers_at_floor():
    d = evaluate_profit_lock_floor(armed=True, lock_min_abs=3000, aggregate_mtm=3000)
    assert d.triggered is True
    assert d.rule == "PROFIT_LOCK"
    assert d.threshold == 3000


def test_profit_lock_floor_triggers_below_floor():
    d = evaluate_profit_lock_floor(armed=True, lock_min_abs=3000, aggregate_mtm=2000)
    assert d.triggered is True


# ===========================================================================
# Trail-to-entry
# ===========================================================================


def test_trail_to_entry_disabled():
    d = evaluate_trail_to_entry(
        enabled=False, threshold=2.0, threshold_unit="pct",
        avg_entry=1500, ltp=1600, direction="long", tick_size=0.05,
        current_sl_price=1490, already_armed=False,
    )
    assert d.arm_now is False


def test_trail_to_entry_long_arms_after_threshold_pct():
    """1% of 1500 = 15. Move from 1500 to 1515 → arm."""
    d = evaluate_trail_to_entry(
        enabled=True, threshold=1.0, threshold_unit="pct",
        avg_entry=1500, ltp=1515, direction="long", tick_size=0.05,
        current_sl_price=1490, already_armed=False,
    )
    assert d.arm_now is True
    assert d.new_sl_price == 1500.0  # snapped to entry


def test_trail_to_entry_long_below_threshold_no_arm():
    d = evaluate_trail_to_entry(
        enabled=True, threshold=1.0, threshold_unit="pct",
        avg_entry=1500, ltp=1510, direction="long", tick_size=0.05,
        current_sl_price=1490, already_armed=False,
    )
    assert d.arm_now is False


def test_trail_to_entry_short_inverts():
    """Short: favorable = price DROPS. 1% of 1500 = 15.
    Move from 1500 to 1485 → arm."""
    d = evaluate_trail_to_entry(
        enabled=True, threshold=1.0, threshold_unit="pct",
        avg_entry=1500, ltp=1485, direction="short", tick_size=0.05,
        current_sl_price=1510, already_armed=False,
    )
    assert d.arm_now is True
    assert d.new_sl_price == 1500.0


def test_trail_to_entry_pts_unit():
    d = evaluate_trail_to_entry(
        enabled=True, threshold=20.0, threshold_unit="pts",
        avg_entry=1500, ltp=1520, direction="long", tick_size=0.05,
        current_sl_price=1490, already_armed=False,
    )
    assert d.arm_now is True


def test_trail_to_entry_already_armed_skipped():
    """Once armed, evaluator must return arm_now=False — caller persists
    the latch and skips this branch on subsequent ticks."""
    d = evaluate_trail_to_entry(
        enabled=True, threshold=1.0, threshold_unit="pct",
        avg_entry=1500, ltp=1600, direction="long", tick_size=0.05,
        current_sl_price=1500, already_armed=True,
    )
    assert d.arm_now is False


def test_trail_to_entry_keeps_better_sl_one_way_ratchet():
    """If current_sl is already AT or ABOVE entry (e.g. trail X/Y advanced
    past entry already), trail-to-entry arms but does NOT lower the SL
    back to entry."""
    d = evaluate_trail_to_entry(
        enabled=True, threshold=1.0, threshold_unit="pct",
        avg_entry=1500, ltp=1520, direction="long", tick_size=0.05,
        current_sl_price=1510,  # already better than entry
        already_armed=False,
    )
    assert d.arm_now is True
    # new_sl_price preserves the better existing SL
    assert d.new_sl_price == 1510


def test_trail_to_entry_zero_threshold_disabled():
    d = evaluate_trail_to_entry(
        enabled=True, threshold=0, threshold_unit="pct",
        avg_entry=1500, ltp=1510, direction="long", tick_size=0.05,
        current_sl_price=1490, already_armed=False,
    )
    assert d.arm_now is False
