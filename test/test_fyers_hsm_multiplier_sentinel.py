"""Fyers HSM wire multiplier=0 sentinel must not skip the segment divisor.

The Fyers HSM WebSocket sends ``multiplier=0`` for instruments with no
lot-multiplier scaling — currency futures (CDS) among them. The mapping
guard treated 0 as "skip the whole conversion": LTP and depth passed
through raw paisa (100x too large) and the quote path zeroed every price
field. Caught live on 2026-08 (OA_Yuv receipt: USDINR tick 9574.25 vs
REST truth ~96.1); the REST-quote path masked the LTP case because REST
returns rupees.

Observed HSM wire shapes (OA_Yuv live receipts, 2026-08): equity ticks
carry multiplier=1 and paisa prices; CDS ticks carry multiplier=0.
Fix semantics: a non-positive multiplier is a sentinel for "no multiplier
scaling" (normalize to 1) — the paisa segment divisor is always applied.
"""

import pytest

from broker.fyers.streaming.fyers_mapping import FyersDataMapper


@pytest.fixture()
def mapper():
    return FyersDataMapper()


# --- controls: documented arithmetic on real wire shapes -------------------


def test_ltp_equity_paisa_multiplier_one(mapper):
    # Observed equity shape: paisa price, multiplier=1.
    data = {"symbol": "NSE:RELIANCE-EQ", "ltp": 250000, "multiplier": 1, "precision": 2}
    assert mapper.map_to_openalgo_ltp(data)["ltp"] == 2500.0


def test_quote_equity_paisa_multiplier_one(mapper):
    data = {
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


# --- the bug: currency sentinel (multiplier=0) ------------------------------


def test_ltp_currency_sentinel_still_gets_segment_divisor(mapper):
    # 9574.25 paisa with multiplier=0: pre-fix this returned 9574.25 raw.
    data = {"symbol": "CDS:USDINR26OCTFUT", "ltp": 9574.25, "multiplier": 0, "precision": 4}
    assert mapper.map_to_openalgo_ltp(data)["ltp"] == 95.7425


def test_bcd_currency_sentinel_still_gets_segment_divisor(mapper):
    data = {"symbol": "BCD:EURINR26OCTFUT", "ltp": 1102500, "multiplier": 0, "precision": 4}
    assert mapper.map_to_openalgo_ltp(data)["ltp"] == 11025.0


def test_quote_currency_sentinel_never_zeroes_prices(mapper):
    # Pre-fix every price field came back 0.0 under the sentinel.
    data = {
        "symbol": "CDS:USDINR26OCTFUT",
        "ltp": 9574.25,
        "open_price": 9570,
        "high_price": 9580,
        "low_price": 9560,
        "prev_close_price": 9575,
        "multiplier": 0,
        "precision": 4,
    }
    quote = mapper.map_to_openalgo_quote(data)
    assert quote["ltp"] == 95.7425
    assert quote["open"] == 95.70
    assert quote["high"] == 95.80
    assert quote["low"] == 95.60
    assert quote["close"] == 95.75


def test_depth_currency_sentinel_never_zeroes_prices(mapper):
    data = {
        "type": "dp",
        "symbol": "CDS:USDINR26OCTFUT",
        "bid_price1": 9570,
        "ask_price1": 9575,
        "multiplier": 0,
        "precision": 4,
    }
    depth = mapper.map_to_openalgo_depth(data)
    assert depth["depth"]["buy"][0]["price"] == 95.70
    assert depth["depth"]["sell"][0]["price"] == 95.75


def test_negative_multiplier_treated_as_sentinel(mapper):
    data = {"symbol": "CDS:USDINR26OCTFUT", "ltp": 9574.25, "multiplier": -1, "precision": 4}
    assert mapper.map_to_openalgo_ltp(data)["ltp"] == 95.7425


# --- the wire omitting multiplier keeps the documented default --------------


def test_ltp_missing_multiplier_keeps_default_100(mapper):
    # Unchanged branch: absent field -> default 100 applies with the divisor.
    data = {"symbol": "MCX:CRUDEOIL26DECFUT", "ltp": 650000, "precision": 2}
    assert mapper.map_to_openalgo_ltp(data)["ltp"] == 65.0
