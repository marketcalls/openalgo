"""RMoney's trade book lists each fill at its own size, price and time.

XTS answers ``GET /orders/trades`` with one row per fill. The fill's own size,
price and time are LastTradedQuantity, LastTradedPrice and ExchangeTransactTime;
the row also repeats its order's OrderQuantity and OrderAverageTradedPrice. The
mapping took the order's fields, so an order filled in twelve parts showed its
full size twelve times, and the trade value and any sum over the book counted
it twelve times over. The common trade book is one row per fill
(docs/api/account-services/tradebook.md).

The rows below are modelled on what a live RMoney account returned for a 3510
buy at 46 that filled in twelve parts at 45.95 and 46: the same fields, four of
the fills.
"""

from __future__ import annotations

import pytest

from broker.rmoney.mapping import order_data


def _fill(quantity, price, at, **fields):
    row = {
        "ExchangeSegment": "NSEFO",
        "ExchangeInstrumentID": 51342,
        "TradingSymbol": "NIFTY27OCT2622750CE",
        "ProductType": "MIS",
        "OrderSide": "BUY",
        "AppOrderID": 1110904858,
        "OrderQuantity": 3510,
        "OrderAverageTradedPrice": "45.99444444444445",
        "OrderGeneratedDateTime": "27-10-2026 13:04:22",
        "LastUpdateDateTime": at,
        "ExchangeTransactTime": at,
        "LastTradedQuantity": quantity,
        "LastTradedPrice": price,
    }
    row.update(fields)
    return row


FILLS = [
    _fill(195, 45.95, "27-10-2026 13:04:32"),
    _fill(195, 45.95, "27-10-2026 13:04:32"),
    _fill(260, 46, "27-10-2026 13:04:32"),
    _fill(2860, 46, "27-10-2026 13:04:33"),
]


def test_each_fill_shows_its_own_size_price_and_time():
    trades = order_data.transform_tradebook_data(FILLS)

    assert [t["quantity"] for t in trades] == [195, 195, 260, 2860]
    assert [t["average_price"] for t in trades] == [45.95, 45.95, 46.0, 46.0]
    assert [t["trade_value"] for t in trades] == pytest.approx(
        [8960.25, 8960.25, 11960.0, 131560.0]
    )
    assert [t["timestamp"] for t in trades] == ["27-10-2026 13:04:32"] * 3 + ["27-10-2026 13:04:33"]
    assert {t["orderid"] for t in trades} == {"1110904858"}


def test_the_fills_add_up_to_the_order_once():
    trades = order_data.transform_tradebook_data(FILLS)

    assert sum(t["quantity"] for t in trades) == 3510
    assert sum(t["trade_value"] for t in trades) == pytest.approx(161440.50)


def test_a_row_without_fill_fields_falls_back_to_the_order():
    row = _fill("", "", "", ExchangeTransactTime="")
    row["LastUpdateDateTime"] = "27-10-2026 13:04:40"

    (trade,) = order_data.transform_tradebook_data([row])

    assert (trade["quantity"], trade["average_price"]) == (3510, pytest.approx(45.99444444444445))
    assert trade["timestamp"] == "27-10-2026 13:04:40"
