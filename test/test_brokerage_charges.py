"""Tests for services.brokerage_charges (brokerage estimator backed by
data/broker_charges_comparison.csv).

The expected values below are locked vectors hand-derived from the tariff
sheet. They guard three parser defects that produced silent wrong output:

- equities whose symbol ends in "CE"/"PE" (RELIANCE, BAJFINANCE) were resolved
  to Options via the symbol suffix instead of staying Equity;
- STT rows recording "0.1% on buy and sell" mis-parsed as sell-only because the
  "on sell" test matched inside "…and sell";
- GST / SEBI / IPFT rows under "All Equity Segments" and DP rows under
  "DP Charges" / "Demat Account" were dropped because lookup only read the
  resolved segment.
"""

import pytest

from services.brokerage_charges import (
    SUPPORTED_BROKERS,
    estimate_brokerage,
    resolve_segment,
)


def test_supported_brokers():
    assert SUPPORTED_BROKERS == ("fyers", "zerodha", "dhan", "groww")


def test_unsupported_broker_rejected():
    with pytest.raises(ValueError):
        estimate_brokerage(
            broker="flattrade",
            exchange="NSE",
            product="MIS",
            symbol="SBIN",
            side="BUY",
            quantity=1,
            price=500,
        )


def test_zerodha_intraday_buy():
    r = estimate_brokerage(
        broker="zerodha",
        exchange="NSE",
        product="MIS",
        symbol="SBIN",
        side="BUY",
        quantity=100,
        price=500,
    )
    assert r["segment"] == "Equity Intraday"
    assert r["components"] == {
        "brokerage": 15.00,
        "stt": 0.00,
        "exchange_txn": 1.53,
        "sebi": 0.05,
        "ipft": 0.00,
        "clearing_charges": 0.00,
        "stamp_duty": 1.50,
        "dp_charges": 0.00,
        "gst": 2.99,
    }
    assert r["total"] == 21.07


def test_zerodha_delivery_sell_includes_stt_and_dp():
    r = estimate_brokerage(
        broker="zerodha",
        exchange="NSE",
        product="CNC",
        symbol="SBIN",
        side="SELL",
        quantity=100,
        price=500,
    )
    assert r["segment"] == "Equity Delivery"
    assert r["total"] == 67.21
    assert r["components"]["stt"] == 50.00
    assert r["components"]["dp_charges"] == 15.34


def test_fyers_options_sell_includes_clearing():
    r = estimate_brokerage(
        broker="fyers",
        exchange="NFO",
        product="NRML",
        symbol="NIFTY26AUG2024200CE",
        side="SELL",
        quantity=1,
        price=200,
        lot_size=75,
    )
    assert r["segment"] == "Options"
    assert r["total"] == 54.00
    assert r["components"]["stt"] == 22.50
    assert r["components"]["clearing_charges"] == 1.35
    assert r["components"]["gst"] == 4.81


def test_groww_delivery_sell_dp_not_overwritten_by_buy_row():
    r = estimate_brokerage(
        broker="groww",
        exchange="NSE",
        product="CNC",
        symbol="SBIN",
        side="SELL",
        quantity=100,
        price=500,
    )
    assert r["segment"] == "Equity Delivery"
    assert r["components"]["dp_charges"] == 15.00
    assert r["total"] == 66.87


def test_dhan_intraday_buy():
    r = estimate_brokerage(
        broker="dhan",
        exchange="NSE",
        product="MIS",
        symbol="RELIANCE",
        side="BUY",
        quantity=500,
        price=2600,
    )
    assert r["segment"] == "Equity Intraday"
    assert r["total"] == 111.23
    assert r["components"]["stamp_duty"] == 39.00


def test_tariff_rows_preserve_all_four_columns():
    import csv

    from services.brokerage_charges import CHARGES_CSV

    with CHARGES_CSV.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    assert all(len(row) == 4 for row in rows if row)
    assert any(row[-1] == "500/month Connect, Free Personal" for row in rows)


def test_orderbook_units_equal_equivalent_lots():
    common = {
        "broker": "zerodha",
        "exchange": "NFO",
        "product": "MIS",
        "symbol": "BANKNIFTY26AUG2449000FUT",
        "side": "BUY",
        "price": 48000,
    }
    assert (
        estimate_brokerage(**common, quantity=35)["total"]
        == estimate_brokerage(**common, quantity=1, lot_size=35)["total"]
    )


def test_zerodha_futures_buy_scales_by_lot_size():
    r = estimate_brokerage(
        broker="zerodha",
        exchange="NFO",
        product="MIS",
        symbol="BANKNIFTY26AUG2449000FUT",
        side="BUY",
        quantity=1,
        price=48000,
        lot_size=35,
    )
    assert r["segment"] == "Futures"
    assert r["total"] == 95.46
    assert r["components"]["exchange_txn"] == 30.74
    assert r["components"]["stamp_duty"] == 33.60


def test_equity_symbol_ending_in_ce_is_not_options():
    for symbol in ("RELIANCE", "BAJFINANCE", "NIFTY"):
        r = estimate_brokerage(
            broker="zerodha",
            exchange="NSE",
            product="MIS",
            symbol=symbol,
            side="BUY",
            quantity=1,
            price=500,
        )
        assert r["segment"] == "Equity Intraday", symbol


@pytest.mark.parametrize(
    "exchange, product, symbol, instrumenttype, expected",
    [
        ("NSE", "MIS", "SBIN", None, "Equity Intraday"),
        ("NSE", "CNC", "RELIANCE", None, "Equity Delivery"),
        ("NSE", "NRML", "BAJFINANCE", None, "Equity Delivery"),
        # Suffix alone is never enough for an equity exchange.
        ("NSE", "MIS", "RELIANCE", None, "Equity Intraday"),
        ("BSE", "MIS", "BAJFINANCE", None, "Equity Intraday"),
        # Opt chain suffix decides on a derivative exchange.
        ("NFO", "NRML", "NIFTY28MAR2420800CE", None, "Options"),
        ("BFO", "NRML", "BANKNIFTY28AUG2449000PE", "CE", "Options"),
        ("NFO", "MIS", "CRUDEOILM20MAY24FUT", None, "Futures"),
        ("MCX", "MIS", "GOLD24AUGFUT", "FUT", "Futures"),
        # Explicit instrumenttype overrides a bare index symbol.
        ("NSE_INDEX", "MIS", "NIFTY 50", "INDEX", "Equity Intraday"),
    ],
)
def test_resolve_segment(exchange, product, symbol, instrumenttype, expected):
    assert resolve_segment(exchange, product, symbol, instrumenttype) == expected
