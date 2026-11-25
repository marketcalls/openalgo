"""Regression contracts for GitHub issue #2464 (Flattrade trade book counts a
part-filled order once per fill).

PiConnect's TradeBook returns one row per fill. Every row repeats the order's
quantity in "qty" and its running average in "avgprc"; the fill's own quantity
and price are "flqty" and "flprc". transform_tradebook_data read "qty", so an
order filled in two parts was reported as two trades of the full quantity.

The reporter's SELL 120 of SENSEX19NOV2682300PE (order 26111700329676) filled
in two parts and appeared as two SELL rows of 120 each, so the Scalping
Terminal showed 260 sold against 140 bought on a flat position, and the wrong
realized P&L with it.
"""

from __future__ import annotations

import pytest

from broker.flattrade.mapping.order_data import transform_tradebook_data

ORDER = "26111700329676"
SYMBOL = "SENSEX19NOV2682300PE"


def fill(norenordno, trantype, qty, flqty, flprc, avgprc, **extra):
    """A PiConnect TradeBook row as the API sends it: every number a string."""
    row = {
        "stat": "Ok",
        "norenordno": norenordno,
        "exch": "BFO",
        "tsym": SYMBOL,
        "prd": "NRML",
        "trantype": trantype,
        "qty": str(qty),
        "fillshares": str(qty),
        "avgprc": str(avgprc),
        "norentm": "13:09:10 17-11-2026",
    }
    if flqty is not None:
        row["flqty"] = str(flqty)
    if flprc is not None:
        row["flprc"] = str(flprc)
    row.update(extra)
    return row


# The SELL 120 order, filled 60 + 60. Each row carries qty 120 and the order's
# running average at that fill (316.05, then 316.02), as the reporter's trade
# book showed.
SPLIT_SELL = [
    fill(ORDER, "SELL", 120, 60, "316.05", "316.05"),
    fill(ORDER, "SELL", 120, 60, "315.99", "316.02"),
]


def test_a_part_filled_order_is_counted_once():
    trades = transform_tradebook_data(SPLIT_SELL)

    assert [t["quantity"] for t in trades] == [60, 60]
    assert sum(t["quantity"] for t in trades) == 120
    assert [t["average_price"] for t in trades] == [316.05, 315.99]
    # Value of the whole order: 120 at the order's average of 316.02.
    assert sum(t["trade_value"] for t in trades) == pytest.approx(120 * 316.02)
    assert {t["orderid"] for t in trades} == {ORDER}


def test_the_reporters_strike_balances_on_a_flat_position():
    """Every SENSEX19NOV2682300PE fill of the reporter's day: 140 bought, 140 sold."""
    day = [
        fill("26111700089790", "BUY", 20, 20, "365.00", "365.00"),
        fill("26111700096590", "SELL", 20, 20, "375.15", "375.15"),
        fill("26111700105305", "BUY", 20, 20, "376.40", "376.40"),
        fill("26111700122313", "BUY", 20, 20, "317.90", "317.90"),
        fill("26111700157141", "BUY", 20, 20, "322.45", "322.45"),
        fill("26111700167056", "BUY", 40, 40, "290.90", "290.90"),
        fill("26111700183899", "BUY", 20, 20, "278.75", "278.75"),
        *SPLIT_SELL,
    ]
    trades = transform_tradebook_data(day)

    bought = sum(t["quantity"] for t in trades if t["action"] == "BUY")
    sold = sum(t["quantity"] for t in trades if t["action"] == "SELL")
    assert (bought, sold) == (140, 140)

    buy_value = sum(t["trade_value"] for t in trades if t["action"] == "BUY")
    sell_value = sum(t["trade_value"] for t in trades if t["action"] == "SELL")
    assert sell_value - buy_value == pytest.approx(579.40)


def test_a_single_fill_order_is_unchanged():
    trades = transform_tradebook_data([fill("1", "BUY", 20, 20, "562.30", "562.30")])

    assert trades == [
        {
            "symbol": SYMBOL,
            "exchange": "BFO",
            "product": "NRML",
            "action": "BUY",
            "quantity": 20,
            "average_price": 562.3,
            "trade_value": 11246.0,
            "orderid": "1",
            "timestamp": "13:09:10 17-11-2026",
        }
    ]


def test_a_row_without_fill_fields_falls_back_to_the_order_fields():
    trades = transform_tradebook_data([fill("1", "BUY", 20, None, None, "562.30")])

    assert trades[0]["quantity"] == 20
    assert trades[0]["average_price"] == 562.3


def test_an_unreadable_number_maps_to_zero_instead_of_failing_the_book():
    trades = transform_tradebook_data([fill("1", "BUY", 20, "", "", "562.30")])

    assert trades[0]["quantity"] == 0
    assert trades[0]["average_price"] == 0.0
    assert trades[0]["trade_value"] == 0.0
