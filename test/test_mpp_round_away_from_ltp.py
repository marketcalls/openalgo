"""The MPP buffer survives tick rounding (part of issue #2393).

calculate_protected_price rounded to the nearest tick, so a buffer smaller
than half a tick vanished: an option at 0.30 with a 0.05 tick got 5% (0.315),
which rounded back to 0.30, its own LTP.
"""

import pytest

from utils.mpp_slab import calculate_protected_price


@pytest.mark.parametrize(
    "ltp, action, expected",
    [
        (0.30, "BUY", 0.35),
        (0.30, "SELL", 0.25),
        (1.00, "BUY", 1.05),
        (1.00, "SELL", 0.95),
    ],
)
def test_cheap_option_keeps_at_least_one_tick_of_buffer(ltp, action, expected):
    assert calculate_protected_price(ltp, action, instrument_type="CE", tick_size=0.05) == expected


@pytest.mark.parametrize(
    "ltp, action, expected",
    [
        (102.01, "BUY", 103.05),  # 103.0301 rounds up, not down to 103.00
        (102.01, "SELL", 100.95),  # 100.9899 rounds down
        (1400, "BUY", 1407.0),  # already on the tick: unchanged
        (1400, "SELL", 1393.0),
    ],
)
def test_price_rounds_away_from_the_ltp(ltp, action, expected):
    assert calculate_protected_price(ltp, action, instrument_type="EQ", tick_size=0.05) == expected


def test_sell_one_tick_above_zero_stays_on_that_tick():
    assert calculate_protected_price(0.05, "SELL", instrument_type="PE", tick_size=0.05) == 0.05


def test_without_a_tick_size_it_still_rounds_to_two_decimals():
    assert calculate_protected_price(102.01, "BUY", instrument_type="EQ") == 103.03


def test_a_zero_custom_percentage_is_not_given_a_tick():
    assert calculate_protected_price(100, "BUY", tick_size=0.05, custom_percentage=0) == 100.0


@pytest.mark.parametrize("ltp", [0.3, 1.15, 7.35, 49.95, 312.4, 2410.55])
@pytest.mark.parametrize("action", ["BUY", "SELL"])
def test_result_is_on_the_tick_and_past_the_ltp(ltp, action):
    price = calculate_protected_price(ltp, action, instrument_type="CE", tick_size=0.05)
    assert round(price / 0.05, 6).is_integer()
    assert price > ltp if action == "BUY" else price < ltp
