"""Unit tests for utils/price_utils.py."""

import pytest

from utils.price_utils import is_aligned_to_tick, round_to_tick, ticks_between


def test_round_to_tick_nearest_005():
    assert round_to_tick(100.07, 0.05) == 100.05
    assert round_to_tick(100.08, 0.05) == 100.10
    assert round_to_tick(100.025, 0.05) == 100.05  # half-up


def test_round_to_tick_nearest_010():
    assert round_to_tick(100.04, 0.10) == 100.00
    assert round_to_tick(100.06, 0.10) == 100.10


def test_round_to_tick_nearest_025():
    assert round_to_tick(100.10, 0.25) == 100.00
    assert round_to_tick(100.15, 0.25) == 100.25


def test_round_to_tick_down_floor():
    assert round_to_tick(100.07, 0.05, mode="down") == 100.05
    assert round_to_tick(100.04, 0.10, mode="down") == 100.00


def test_round_to_tick_up_ceiling():
    assert round_to_tick(100.07, 0.05, mode="up") == 100.10
    assert round_to_tick(100.01, 0.05, mode="up") == 100.05


def test_round_to_tick_favorable_buy_rounds_down():
    # BUY-side favorable: looser SL on a long → round DOWN
    assert round_to_tick(100.07, 0.05, mode="favorable", side="BUY") == 100.05
    assert round_to_tick(100.04, 0.10, mode="favorable", side="BUY") == 100.00


def test_round_to_tick_favorable_sell_rounds_up():
    # SELL-side favorable: looser SL on a short → round UP
    assert round_to_tick(100.07, 0.05, mode="favorable", side="SELL") == 100.10
    assert round_to_tick(100.04, 0.10, mode="favorable", side="SELL") == 100.10


def test_round_to_tick_no_drift_on_subtick():
    # Critical: 100.05 stays 100.05, not 100.04999999
    snapped = round_to_tick(100.05, 0.05)
    assert snapped == 100.05


def test_round_to_tick_invalid_tick_raises():
    with pytest.raises(ValueError):
        round_to_tick(100, 0)
    with pytest.raises(ValueError):
        round_to_tick(100, -0.05)


def test_round_to_tick_unknown_mode_raises():
    with pytest.raises(ValueError):
        round_to_tick(100, 0.05, mode="bogus")


def test_round_to_tick_favorable_requires_valid_side():
    with pytest.raises(ValueError):
        round_to_tick(100, 0.05, mode="favorable", side="HOLD")


def test_is_aligned_to_tick_true_cases():
    assert is_aligned_to_tick(100.00, 0.05) is True
    assert is_aligned_to_tick(100.05, 0.05) is True
    assert is_aligned_to_tick(100.10, 0.05) is True


def test_is_aligned_to_tick_false_cases():
    assert is_aligned_to_tick(100.07, 0.05) is False
    assert is_aligned_to_tick(100.025, 0.05) is False


def test_ticks_between():
    assert ticks_between(100.00, 100.50, 0.05) == 10
    assert ticks_between(100.00, 100.05, 0.05) == 1
    assert ticks_between(100.00, 100.04, 0.05) == 0  # less than one tick
