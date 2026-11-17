"""Fyers HSM prices are scaled by the per-instrument precision, not a fixed /100.

The official SDK (fyers-apiv3 FyersWebsocket/data_ws.py) decodes every scrip,
depth and index price as raw / (10 ** precision * multiplier). The mapper used
to divide by 100 regardless of precision, which is right only for precision 2.
Currency carries precision 4, so CDS/BCD ticks came out 100x too large: the
socket read USDINR 9574.25 while REST returned 95.74.

The wire values below are what the HSM decoder produces: signed 32-bit integers
plus the multiplier and precision fields of the snapshot.
"""

import pytest

from broker.fyers.streaming.fyers_mapping import FyersDataMapper


@pytest.fixture()
def mapper():
    return FyersDataMapper()


# --- unchanged: precision 2 instruments -------------------------------------


def test_ltp_equity_precision_two(mapper):
    data = {"symbol": "NSE:RELIANCE-EQ", "ltp": 250000, "multiplier": 1, "precision": 2}
    assert mapper.map_to_openalgo_ltp(data)["ltp"] == 2500.0


def test_quote_equity_precision_two(mapper):
    data = {
        "type": "sf",
        "symbol": "NSE:RELIANCE-EQ",
        "ltp": 250000,
        "open_price": 249500,
        "high_price": 250500,
        "low_price": 249000,
        "prev_close_price": 249800,
        "multiplier": 1,
        "precision": 2,
    }
    quote = mapper.map_to_openalgo_quote(data)
    assert quote["ltp"] == 2500.0
    assert quote["open"] == 2495.0
    assert quote["close"] == 2498.0


def test_ltp_commodity_precision_two(mapper):
    data = {"symbol": "MCX:CRUDEOIL26DECFUT", "ltp": 650000, "multiplier": 1, "precision": 2}
    assert mapper.map_to_openalgo_ltp(data)["ltp"] == 6500.0


def test_index_feed_without_scale_fields_stays_at_hundred(mapper):
    # The index feed carries no multiplier or precision; it was /100 before.
    data = {"type": "if", "symbol": "NSE:NIFTY50-INDEX", "ltp": 2512345, "open_price": 2500000}
    quote = mapper.map_to_openalgo_quote(data)
    assert quote["ltp"] == 25123.45
    assert quote["open"] == 25000.0
    assert mapper.map_index_to_depth(data)["ltp"] == 25123.45


# --- the bug: precision 4 currency ------------------------------------------


def test_ltp_currency_precision_four(mapper):
    # Fyers prefixes NSE currency futures with NSE:, so the old exchange list
    # applied /100 and returned 9574.25.
    data = {"symbol": "NSE:USDINR26OCTFUT", "ltp": 957425, "multiplier": 1, "precision": 4}
    assert mapper.map_to_openalgo_ltp(data)["ltp"] == 95.7425


def test_ltp_bse_currency_precision_four(mapper):
    data = {"symbol": "BSE:EURINR26OCTFUT", "ltp": 1102500, "multiplier": 1, "precision": 4}
    assert mapper.map_to_openalgo_ltp(data)["ltp"] == 110.25


def test_quote_currency_precision_four(mapper):
    data = {
        "type": "sf",
        "symbol": "NSE:USDINR26OCTFUT",
        "ltp": 957425,
        "open_price": 957000,
        "high_price": 958000,
        "low_price": 956000,
        "prev_close_price": 957500,
        "bid_price": 957400,
        "ask_price": 957450,
        "avg_trade_price": 957125,
        "multiplier": 1,
        "precision": 4,
    }
    quote = mapper.map_to_openalgo_quote(data)
    assert quote["ltp"] == 95.7425
    assert quote["open"] == 95.70
    assert quote["high"] == 95.80
    assert quote["low"] == 95.60
    assert quote["close"] == 95.75
    assert quote["bid_price"] == 95.74
    assert quote["ask_price"] == 95.745
    assert quote["avg_trade_price"] == 95.7125


def test_depth_currency_precision_four(mapper):
    data = {
        "type": "dp",
        "symbol": "NSE:USDINR26OCTFUT",
        "bid_price1": 957400,
        "ask_price1": 957450,
        "bid_size1": 10,
        "ask_size1": 12,
        "multiplier": 1,
        "precision": 4,
    }
    depth = mapper.map_to_openalgo_depth(data)
    assert depth["depth"]["buy"][0]["price"] == 95.74
    assert depth["depth"]["sell"][0]["price"] == 95.745


# --- multiplier ---------------------------------------------------------------


def test_multiplier_divides_as_in_sdk(mapper):
    data = {"symbol": "NSE:ABC-EQ", "ltp": 250000, "multiplier": 10, "precision": 2}
    assert mapper.map_to_openalgo_ltp(data)["ltp"] == 250.0


@pytest.mark.parametrize("multiplier", [0, -1])
def test_non_positive_multiplier_never_zeroes_or_skips(mapper, multiplier):
    data = {
        "type": "dp",
        "symbol": "NSE:USDINR26OCTFUT",
        "ltp": 957425,
        "bid_price1": 957400,
        "multiplier": multiplier,
        "precision": 4,
    }
    assert mapper.map_to_openalgo_ltp(data)["ltp"] == 95.7425
    assert mapper.map_to_openalgo_quote(data)["ltp"] == 95.7425
    assert mapper.map_to_openalgo_depth(data)["depth"]["buy"][0]["price"] == 95.74
