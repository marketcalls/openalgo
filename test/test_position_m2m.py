"""
Unit tests for today's M2M per position.

The numbers are taken from real rows: Zerodha rows matched the broker's own
`m2m` and Kotak rows matched its `pnl`, all to the paisa.

Run with: uv run pytest test/test_position_m2m.py -v
"""

from services.position_m2m import compute_m2m


def _pos(symbol, quantity, ltp, product="MIS", exchange="NFO"):
    return {
        "symbol": symbol,
        "exchange": exchange,
        "product": product,
        "quantity": quantity,
        "ltp": ltp,
    }


def _trade(symbol, action, quantity, price, product="MIS", exchange="NFO"):
    return {
        "symbol": symbol,
        "exchange": exchange,
        "product": product,
        "action": action,
        "quantity": quantity,
        "average_price": price,
    }


def _one(positions, trades, prev):
    results = compute_m2m(positions, trades, prev)
    return results[(positions[0]["symbol"], positions[0]["exchange"], positions[0]["product"])]


def test_carried_long_closed_today_is_measured_from_yesterdays_close():
    # NRML long carried from the previous day, sold 195 @ 0.25 today.
    result = _one(
        [_pos("P", 0, 0.05, "NRML")],
        [_trade("P", "SELL", 195, 0.25, "NRML")],
        {("P", "NFO"): 22.7},
    )
    assert result["available"]
    assert result["overnight_quantity"] == 195
    assert result["m2m"] == -4377.75


def test_carried_short_closed_today():
    # NRML short carried from the previous day, bought back 195 @ 0.7 today.
    result = _one(
        [_pos("P", 0, 0.05, "NRML")],
        [_trade("P", "BUY", 195, 0.7, "NRML")],
        {("P", "NFO"): 79.35},
    )
    assert result["overnight_quantity"] == -195
    assert result["m2m"] == 15336.75


def test_intraday_round_trip_needs_no_previous_close():
    # MIS round trip: sold 65 @ 17.15, bought back 65 @ 0.4.
    result = _one(
        [_pos("P", 0, 0.05)],
        [_trade("P", "SELL", 65, 17.15), _trade("P", "BUY", 65, 0.4)],
        {},
    )
    assert result["available"]
    assert result["overnight_quantity"] == 0
    assert result["m2m"] == 1088.75


def test_open_position_opened_today_is_marked_to_the_live_price():
    result = _one([_pos("P", 10, 105.0)], [_trade("P", "BUY", 10, 100.0)], {})
    assert result["m2m"] == 50.0
    assert result["m2m_fixed"] == -1000.0


def test_open_carried_position_marks_from_the_previous_close():
    # Long 10 carried, nothing traded today, LTP 112 against a close of 110.
    result = _one([_pos("P", 10, 112.0, "NRML")], [], {("P", "NFO"): 110.0})
    assert result["overnight_quantity"] == 10
    assert result["m2m"] == 20.0


def test_live_price_moves_only_the_marked_part():
    result = _one([_pos("P", 10, 105.0)], [_trade("P", "BUY", 10, 100.0)], {})
    # A page keeping it live: m2m = m2m_fixed + quantity * newer LTP.
    assert result["m2m_fixed"] + 10 * 110.0 == 100.0


def test_carried_position_without_a_previous_close_is_unavailable_not_wrong():
    result = _one([_pos("P", 0, 0.05, "NRML")], [_trade("P", "SELL", 195, 0.25, "NRML")], {})
    assert not result["available"]
    assert "previous close" in result["reason"]
    assert result["m2m"] is None


def test_open_position_with_no_live_price_is_unavailable():
    result = _one([_pos("P", 10, 0.0)], [_trade("P", "BUY", 10, 100.0)], {})
    assert not result["available"]


def test_unsupported_exchange_is_unavailable():
    result = _one(
        [_pos("CRUDEOIL", 1, 6000.0, "NRML", "MCX")],
        [_trade("CRUDEOIL", "BUY", 1, 5990.0, "NRML", "MCX")],
        {},
    )
    assert not result["available"]
    assert "not supported" in result["reason"]


def test_same_contract_in_two_products_is_kept_apart():
    # One contract with an MIS round trip and an NRML exit on the same day.
    positions = [_pos("P", 0, 0.05, "MIS"), _pos("P", 0, 0.05, "NRML")]
    trades = [
        _trade("P", "BUY", 65, 7.1, "MIS"),
        _trade("P", "SELL", 65, 0.2, "MIS"),
        _trade("P", "SELL", 195, 0.25, "NRML"),
    ]
    results = compute_m2m(positions, trades, {("P", "NFO"): 22.7})
    assert results[("P", "NFO", "MIS")]["m2m"] == -448.5
    assert results[("P", "NFO", "NRML")]["m2m"] == -4377.75


def test_string_numbers_from_a_broker_are_accepted():
    # Kotak's tradebook sends prices as strings; Zerodha's position quantity can too.
    result = _one(
        [_pos("P", "0", 0.05)],
        [_trade("P", "SELL", "65", "13.95"), _trade("P", "BUY", "65", "7.90")],
        {},
    )
    assert result["m2m"] == 393.25
