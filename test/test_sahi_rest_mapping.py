"""Sahi REST mapping: order payloads, books and history, with no network.

Symbol lookups and HTTP are patched; the samples are the shapes in
broker-api-docs/sahi-api-docs (Orders, Portfolio, Market data).
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from broker.sahi.api import data as sahi_data
from broker.sahi.mapping import order_data, transform_data

IST = timezone(timedelta(hours=5, minutes=30))

BR_SYMBOLS = {
    ("BAJAJ-AUTO", "NSE"): "BAJAJ-AUTO",
    ("M&M", "NSE"): "M&M",
    ("NIFTY27OCT2625000CE", "NFO"): "NIFTY27OCT26C25000",
    ("3IINFOLTD", "NSE"): "3IINFOLTD-BE",
}
OA_SYMBOLS = {(br, ex): oa for (oa, ex), br in BR_SYMBOLS.items()}


@pytest.fixture(autouse=True)
def _symbols(monkeypatch):
    monkeypatch.setattr(transform_data, "get_br_symbol", lambda s, e: BR_SYMBOLS.get((s, e)))
    monkeypatch.setattr(
        order_data, "get_oa_symbol", lambda brsymbol, exchange: OA_SYMBOLS.get((brsymbol, exchange))
    )


def test_paise_round_trip():
    assert transform_data.to_paise("2499.55") == 249955
    assert transform_data.to_paise(0.05) == 5
    assert transform_data.to_paise("187.125") == 18713  # half up
    assert transform_data.to_paise(None) == 0
    assert transform_data.from_paise(249955) == 2499.55
    assert transform_data.from_paise(None) == 0.0


@pytest.mark.parametrize("symbol", ["BAJAJ-AUTO", "M&M"])
def test_limit_order_for_special_symbols(symbol):
    payload = transform_data.transform_data(
        {
            "symbol": symbol,
            "exchange": "NSE",
            "action": "BUY",
            "quantity": "1",
            "pricetype": "LIMIT",
            "product": "CNC",
            "price": "9000.5",
        }
    )
    assert payload == {
        "exchange_segment": "NSE",
        "symbol": symbol,
        "txn_type": "B",
        "qty": 1,
        "order_type": "LMT",
        "product": "C",
        "validity": "DAY",
        "price": 900050,
    }


def test_market_and_stop_orders():
    market = transform_data.transform_data(
        {
            "symbol": "NIFTY27OCT2625000CE",
            "exchange": "NFO",
            "action": "SELL",
            "quantity": "65",
            "pricetype": "MARKET",
            "product": "NRML",
            "price": "120",
        }
    )
    assert market["symbol"] == "NIFTY27OCT26C25000"
    assert (market["order_type"], market["price"], market["product"]) == ("MKT", 0, "M")
    assert "trigger_price" not in market

    slm = transform_data.transform_data(
        {
            "symbol": "M&M",
            "exchange": "NSE",
            "action": "SELL",
            "quantity": "2",
            "pricetype": "SL-M",
            "product": "MIS",
            "trigger_price": "3000",
        }
    )
    assert (slm["order_type"], slm["price"], slm["trigger_price"], slm["product"]) == (
        "SL-MKT",
        0,
        300000,
        "I",
    )


def test_unknown_symbol_and_index_are_refused():
    with pytest.raises(transform_data.OrderMappingError):
        transform_data.transform_data(
            {
                "symbol": "NOPE",
                "exchange": "NSE",
                "action": "BUY",
                "quantity": "1",
                "pricetype": "MARKET",
                "product": "MIS",
            }
        )
    with pytest.raises(transform_data.OrderMappingError):
        transform_data.transform_data(
            {
                "symbol": "NIFTY",
                "exchange": "NSE_INDEX",
                "action": "BUY",
                "quantity": "1",
                "pricetype": "MARKET",
                "product": "MIS",
            }
        )


def test_modify_payload():
    payload = transform_data.transform_modify_order_data(
        {
            "orderid": "1",
            "pricetype": "SL",
            "quantity": "10",
            "price": "101.5",
            "trigger_price": "101",
        }
    )
    assert payload == {
        "qty": 10,
        "order_type": "SL-LMT",
        "validity": "DAY",
        "price": 10150,
        "trigger_price": 10100,
    }


ORDER = {
    "order_id": "26101900133912345678",
    "exchange_order_id": "1300000123456789",
    "exchange_segment": "NSE",
    "symbol": "M&M",
    "txn_type": "B",
    "order_type": "LMT",
    "product": "I",
    "validity": "DAY",
    "qty": 10,
    "disclosed_qty": 0,
    "filled_qty": 4,
    "price": 250000,
    "trigger_price": 0,
    "avg_price": 249975,
    "status": "OpenPartial",
    "rejection_reason": None,
    "created_at": 1747798201123,
}


def test_order_book_mapping():
    rows = order_data.map_order_data(
        {"orders": [ORDER, dict(ORDER, status="Rejected", txn_type="S")]}
    )
    stats = order_data.calculate_order_statistics(rows)
    out = order_data.transform_order_data(rows)
    assert out[0] == {
        "symbol": "M&M",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 10,
        "price": 2500.0,
        "trigger_price": 0.0,
        "pricetype": "LIMIT",
        "product": "MIS",
        "orderid": "26101900133912345678",
        "order_status": "open",
        "timestamp": "2025-05-21 09:00:01",
    }
    assert out[1]["order_status"] == "rejected"
    assert stats == {
        "total_buy_orders": 1,
        "total_sell_orders": 1,
        "total_completed_orders": 0,
        "total_open_orders": 1,
        "total_rejected_orders": 1,
    }


def test_status_map():
    assert order_data.map_order_status("Completed") == "complete"
    assert order_data.map_order_status("PartialFilled") == "cancelled"
    assert order_data.map_order_status("Open") == "open"


def test_trade_book_mapping():
    trades = order_data.transform_tradebook_data(
        order_data.map_trade_data(
            {
                "trades": [
                    {
                        "exchange_trade_id": "80123456",
                        "order_id": "1",
                        "exchange_segment": "NSE",
                        "symbol": "BAJAJ-AUTO",
                        "txn_type": "B",
                        "product": "C",
                        "qty": 2,
                        "price": 249950,
                        "traded_at": 1747798201789,
                    }
                ]
            }
        )
    )
    assert trades[0]["symbol"] == "BAJAJ-AUTO"
    assert trades[0]["product"] == "CNC"
    assert trades[0]["average_price"] == 2499.5
    assert trades[0]["trade_value"] == 4999.0
    assert trades[0]["tradeid"] == "80123456"


def test_positions_pnl_is_realised_plus_marked_open():
    rows = order_data.map_position_data(
        {
            "positions": [
                {
                    "exchange_segment": "NSE",
                    "symbol": "3IINFOLTD-BE",
                    "instrument_id": 10914,
                    "product": "I",
                    "net_qty": -10,
                    "net_avg_price": 5000,
                    "realised_pnl": 2500,
                    "total_buy_qty": 5,
                    "total_sell_qty": 15,
                    "ltp": 49.0,
                }
            ]
        }
    )
    out = order_data.transform_positions_data(rows)[0]
    # realised 25.00 + (49 - 50) * -10 = 35.00
    assert out == {
        "symbol": "3IINFOLTD",
        "exchange": "NSE",
        "product": "MIS",
        "quantity": -10,
        "pnl": 35.0,
        "average_price": "50.00",
        "ltp": 49.0,
    }


def test_holdings_mapping(monkeypatch):
    monkeypatch.setattr(
        order_data,
        "get_symbol",
        lambda token, exchange: "RELIANCE" if (token, exchange) == ("12027", "NSE") else None,
    )
    rows = order_data.map_portfolio_data(
        {
            "holdings": [
                {
                    "isin": "INE002A01018",
                    "instrument_ids": [12027, 725069],
                    "holding_qty": 10,
                    "holding_avg_price": 245050,
                    "ltp_by_id": {12027: 2510.0},
                },
                {"isin": "X", "instrument_ids": [1], "holding_qty": 0, "holding_avg_price": 0},
            ]
        }
    )
    assert rows == [
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "quantity": 10,
            "product": "CNC",
            "average_price": 2450.5,
            "ltp": 2510.0,
            "pnl": 595.0,
            "pnlpercent": 2.43,
        }
    ]
    stats = order_data.calculate_portfolio_statistics(rows)
    assert stats["totalprofitandloss"] == 595.0


def _ms(y, m, d, hh=0, mm=0):
    return int(datetime(y, m, d, hh, mm, tzinfo=IST).timestamp() * 1000)


def test_history_pages_backward_and_stamps(monkeypatch):
    monkeypatch.setattr(sahi_data, "get_token", lambda s, e: "12027")
    monkeypatch.setattr(sahi_data, "get_symbol_info", lambda s, e: None)
    calls = []
    first = [[_ms(2026, 10, 1, 9, 16), 100, 200, 50, 150, 7]]
    second = [[_ms(2026, 10, 1, 9, 15), 100, 100, 100, 100, 0]]

    def fake_get(path, auth, category, params):
        calls.append(dict(params))
        if len(calls) == 1:
            return {"candles": first, "has_more": True}
        return {"candles": second, "has_more": False}

    monkeypatch.setattr(sahi_data, "_get", fake_get)
    df = sahi_data.BrokerData("t").get_history("RELIANCE", "NSE", "1m", "2026-10-01", "2026-10-01")
    assert calls[1]["to"] == first[0][0] - 1
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume", "oi"]
    assert df["timestamp"].tolist() == [
        _ms(2026, 10, 1, 9, 15) // 1000,
        _ms(2026, 10, 1, 9, 16) // 1000,
    ]
    assert df.iloc[1][["open", "high", "low", "close"]].tolist() == [1.0, 2.0, 0.5, 1.5]


def test_daily_history_stamped_at_utc_midnight_of_ist_date(monkeypatch):
    monkeypatch.setattr(sahi_data, "get_token", lambda s, e: "12027")
    monkeypatch.setattr(sahi_data, "get_symbol_info", lambda s, e: None)
    candle = [_ms(2026, 10, 1), 100, 200, 50, 150, 7]
    monkeypatch.setattr(sahi_data, "_get", lambda *a: {"candles": [candle], "has_more": False})
    df = sahi_data.BrokerData("t").get_history("RELIANCE", "NSE", "D", "2026-10-01", "2026-10-01")
    assert df["timestamp"].tolist() == [int(pd.Timestamp("2026-10-01", tz="UTC").timestamp())]
