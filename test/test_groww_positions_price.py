"""Groww position prices are the rupees Groww reported.

get_positions() converted the price fields from "paise" to rupees, but Groww
documents every price on a position in rupees: net_price as "Net average price
in rupees of instruments", credit_price and debit_price as the average price in
rupees of credited and debited instruments.

The conversions also disagreed with each other on the same payload. credit_price
and debit_price were divided by 100 unconditionally, so a Rs 433.00 entry was
reported as Rs 4.33 on every position; net_price was divided only above 1000, so
Rs 1,000 came back as Rs 1,000 and Rs 1,001 as Rs 10.01 (issue #2172).

The same value-based conversion was removed from the tradebook in #1995, and
holdings in this file never had one.
"""

import pytest

from broker.groww.api.order_api import groww_position_prices

# Straddling the old 1000 threshold: below it, exactly on it, one rupee past it
# (where the old scale jumped two orders of magnitude), a real equity average,
# and a value large enough that the error was unmissable.
RUPEE_PRICES = [99.0, 100.0, 433.0, 1000.0, 1001.0, 1500.0, 2500.0]


def position(**overrides):
    """A position in the shape Groww's payload carries."""
    base = {
        "trading_symbol": "RELIANCE",
        "quantity": 10,
        "net_price": 433.0,
        "credit_price": 433.0,
        "debit_price": 0.0,
        "symbol_isin": "INE002A01018",
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize("price", RUPEE_PRICES)
def test_average_price_is_the_rupees_groww_sent(price):
    assert groww_position_prices(position(net_price=price))["average_price"] == price


@pytest.mark.parametrize("price", RUPEE_PRICES)
def test_buy_price_is_the_rupees_groww_sent(price):
    """This one was wrong at every value, not only above the threshold."""
    assert groww_position_prices(position(credit_price=price))["buy_price"] == price


@pytest.mark.parametrize("price", RUPEE_PRICES)
def test_sell_price_is_the_rupees_groww_sent(price):
    assert groww_position_prices(position(debit_price=price))["sell_price"] == price


def test_the_scale_has_no_step_in_it():
    """A rupee more must not move the reported price by two orders of magnitude."""
    below = groww_position_prices(position(net_price=1000.0))["average_price"]
    above = groww_position_prices(position(net_price=1001.0))["average_price"]

    assert above - below == pytest.approx(1.0)


def test_nothing_sold_reports_no_sell_price():
    assert groww_position_prices(position(debit_price=0.0))["sell_price"] == 0


def test_missing_prices_report_zero():
    assert groww_position_prices({}) == {
        "average_price": 0,
        "buy_price": 0,
        "sell_price": 0,
    }


def test_a_null_price_is_not_an_error():
    """Groww omits or nulls a side that has no trades."""
    prices = groww_position_prices(position(credit_price=None, debit_price=None))

    assert prices["buy_price"] == 0
    assert prices["sell_price"] == 0


def test_a_price_sent_as_text_is_still_rupees():
    assert groww_position_prices(position(net_price="433.0"))["average_price"] == 433.0


def test_the_value_based_conversions_do_not_come_back():
    """Guards the source itself: both heuristics lived in get_positions."""
    from pathlib import Path

    source = Path("broker/groww/api/order_api.py").read_text(encoding="utf-8")
    assert "Likely in paise" not in source
    assert 'position.get("credit_price", 0) / 100' not in source
    assert 'position.get("debit_price", 0) / 100' not in source
