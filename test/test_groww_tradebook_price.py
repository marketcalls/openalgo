"""Regression coverage for Groww tradebook prices.

Groww's trade API reports `price` in rupees. broker/groww/api/order_api.py used
to run every trade through a value-based "paise to rupees" conversion that
divided any price above 100 by 100, so a genuine Rs 433.00 fill was reported as
Rs 4.33 while Rs 99.00 came through untouched. A downstream strategy sized its
successor order off the mangled price and Groww rejected it on circuit limits.

The scale is now carried through unchanged, and these tests pin that at both the
broker transform and the tradebook payload the API returns.
"""

import pytest

from broker.groww.api.order_api import transform_groww_trade
from broker.groww.mapping.order_data import transform_tradebook_data

# Rupee prices straddling the old threshold: below it, exactly on it, a real
# equity fill, and a value large enough that the old rule shifted it by two
# orders of magnitude.
RUPEE_PRICES = [99.0, 100.0, 433.0, 2500.0]


def groww_trade(price):
    """A trade in the shape get_order_trades() normalises Groww's payload to."""
    return {
        "trade_id": "GT250901000001",
        "order_id": "GMK250901000001",
        "exchange_trade_id": "",
        "exchange_order_id": "",
        "symbol": "RELIANCE",
        "quantity": 10,
        "price": price,
        "trade_status": "EXECUTED",
        "exchange": "NSE",
        "segment": "CASH",
        "product": "CNC",
        "transaction_type": "BUY",
        "created_at": "2026-09-01T10:15:00",
        "trade_date_time": "2026-09-01T10:15:00",
        "settlement_number": "",
        "remarks": None,
    }


@pytest.mark.parametrize("price", RUPEE_PRICES)
def test_transform_preserves_rupee_price(price):
    """Groww's rupee price survives the broker-side transform unscaled."""
    transformed = transform_groww_trade(groww_trade(price))

    assert transformed["price"] == price
    assert transformed["tradedPrice"] == price


@pytest.mark.parametrize("price", RUPEE_PRICES)
def test_tradebook_reports_rupee_price(price):
    """The tradebook payload reports the same rupees, and values off them."""
    (trade,) = transform_tradebook_data([transform_groww_trade(groww_trade(price))])

    assert trade["average_price"] == price
    assert trade["trade_price"] == price
    assert trade["trade_value"] == 10 * price


def test_missing_price_defaults_to_zero():
    """A trade with no price still transforms, rather than raising."""
    trade = groww_trade(0)
    del trade["price"]

    assert transform_groww_trade(trade)["price"] == 0
