"""
Unit tests for the P&L Tracker's M2M curve.

The scenario is a NIFTY weekly put: a position carried overnight in NRML and sold
at 15:15, while the same contract was also traded intraday in MIS. The tracker used
to mix the two products, and valued the carried exit as a new short. This curve
keeps them apart and ends on the same figure the Positions page shows.

Run with: uv run pytest test/test_pnl_tracker_m2m.py -v
"""

from datetime import datetime

import pandas as pd
import pytz

from services.pnl_tracker_m2m import build_m2m_frame, build_m2m_tracker_response, summarize

IST = pytz.timezone("Asia/Kolkata")
SYMBOL = "NIFTY06OCT2622350PE"


def _at(hour, minute, second=0):
    return pd.Timestamp(IST.localize(datetime(2026, 10, 6, hour, minute, second)))


def _index(end_hour=15, end_minute=30):
    return pd.date_range(_at(9, 15), _at(end_hour, end_minute), freq="1min")


def _row(key, overnight, prev_close, trades, prices=None, fallback=0.05):
    return {
        "key": key,
        "overnight": overnight,
        "prev_close": prev_close,
        "prices": prices if prices is not None else pd.Series(dtype=float),
        "fallback_price": fallback,
        "trades": trades,
    }


def test_carried_long_closed_today_starts_at_zero_and_ends_on_todays_m2m():
    index = _index()
    prices = pd.Series(22.7, index=index)
    frame = build_m2m_frame(
        index,
        [_row("NRML", 195, 22.7, [(_at(15, 15), "SELL", 195, 0.25)], prices)],
    )
    series = frame["NRML"]
    assert series.iloc[0] == 0.0  # marked at yesterday's close, nothing has moved
    assert series.loc[_at(15, 14)] == 0.0
    assert series.loc[_at(15, 15)] == -4377.75
    assert series.iloc[-1] == -4377.75


def test_the_curve_follows_the_price_while_the_position_is_open():
    index = _index()
    prices = pd.Series(22.7, index=index)
    prices.loc[_at(10, 0) :] = 30.0
    frame = build_m2m_frame(index, [_row("NRML", 195, 22.7, [], prices)])
    assert frame["NRML"].loc[_at(9, 30)] == 0.0
    assert round(frame["NRML"].loc[_at(10, 0)], 2) == round(195 * (30.0 - 22.7), 2)


def test_intraday_round_trip_ends_on_its_fills():
    index = _index()
    prices = pd.Series(7.0, index=index)
    frame = build_m2m_frame(
        index,
        [
            _row(
                "MIS",
                0,
                None,
                [(_at(9, 30), "BUY", 65, 7.1), (_at(15, 12), "SELL", 65, 0.2)],
                prices,
            )
        ],
    )
    assert frame["MIS"].iloc[-1] == -448.5


def test_two_products_on_one_contract_are_not_mixed():
    index = _index()
    prices = pd.Series(10.0, index=index)
    frame = build_m2m_frame(
        index,
        [
            _row(
                f"{SYMBOL}|MIS",
                0,
                22.7,
                [(_at(9, 30), "BUY", 65, 7.1), (_at(15, 12), "SELL", 65, 0.2)],
                prices,
            ),
            _row(f"{SYMBOL}|NRML", 195, 22.7, [(_at(15, 15), "SELL", 195, 0.25)], prices),
        ],
    )
    assert frame[f"{SYMBOL}|MIS"].iloc[-1] == -448.5
    assert frame[f"{SYMBOL}|NRML"].iloc[-1] == -4377.75
    assert frame.sum(axis=1).iloc[-1] == -4826.25


def test_a_minute_without_a_candle_uses_the_last_known_price():
    index = _index()
    prices = pd.Series({_at(9, 15): 22.7, _at(11, 0): 25.0})
    frame = build_m2m_frame(index, [_row("NRML", 10, 22.7, [], prices)])
    assert round(frame["NRML"].loc[_at(10, 0)], 2) == 0.0
    assert round(frame["NRML"].loc[_at(12, 0)], 2) == 23.0


def test_no_candles_at_all_uses_the_fallback_price():
    index = _index()
    frame = build_m2m_frame(index, [_row("NRML", 10, 22.7, [], fallback=24.0)])
    assert round(frame["NRML"].iloc[-1], 2) == 13.0


def test_summary_reports_peak_trough_and_drawdown():
    index = pd.date_range(_at(9, 15), periods=4, freq="1min")
    frame = pd.DataFrame({"A": [0.0, 100.0, 40.0, 70.0]}, index=index)
    summary = summarize(frame)
    assert summary["current_mtm"] == 70.0
    assert summary["max_mtm"] == 100.0
    assert summary["max_mtm_time"] == "09:16"
    assert summary["min_mtm"] == 0.0
    assert summary["max_drawdown"] == -60.0
    assert [point["value"] for point in summary["pnl_series"]] == [0.0, 100.0, 40.0, 70.0]
    assert [point["value"] for point in summary["drawdown_series"]] == [0.0, 0.0, -60.0, -30.0]


def test_summary_of_nothing_is_the_empty_response():
    summary = summarize(pd.DataFrame())
    assert summary["current_mtm"] == 0
    assert summary["pnl_series"] == []


# --- the wrapper: previous closes, candles, and when it steps aside ---------------------------


def _position(product, quantity=0, ltp=0.05, exchange="NFO"):
    return {
        "symbol": SYMBOL,
        "exchange": exchange,
        "product": product,
        "quantity": quantity,
        "ltp": ltp,
        "average_price": 0,
    }


def _trade(product, action, quantity, price, stamp, exchange="NFO"):
    return {
        "symbol": SYMBOL,
        "exchange": exchange,
        "product": product,
        "action": action,
        "quantity": quantity,
        "average_price": price,
        "timestamp": stamp,
    }


TRADES = [
    _trade("MIS", "BUY", 65, 7.1, "2026-10-06 09:30:21"),
    _trade("MIS", "SELL", 65, 0.2, "2026-10-06 15:12:00"),
    _trade("NRML", "SELL", 195, 0.25, "2026-10-06 15:15:02"),
]
POSITIONS = [_position("MIS"), _position("NRML")]


class _NoWait:
    def wait(self):
        pass


def _parse_time(stamp):
    return IST.localize(datetime.fromisoformat(stamp))


def _to_ist(df, symbol=""):
    df = df.copy()
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.tz_convert(IST)
    return df.set_index("datetime").sort_index()


def _history(**kw):
    candles = [{"timestamp": int(ts.timestamp()), "close": 22.7} for ts in _index().to_pydatetime()]
    return True, {"data": candles}, 200


def _quotes(symbols, **kw):
    return (
        True,
        {
            "results": [
                {"symbol": s["symbol"], "exchange": s["exchange"], "data": {"prev_close": 22.7}}
                for s in symbols
            ]
        },
        200,
    )


def _run(**overrides):
    args = {
        "api_key": "k",
        "positions": POSITIONS,
        "trades": TRADES,
        "parse_time": _parse_time,
        "to_ist": _to_ist,
        "rate_limiter": _NoWait(),
        "get_history_fn": _history,
        "get_multiquotes_fn": _quotes,
        "now": IST.localize(datetime(2026, 10, 6, 21, 0)),
    }
    args.update(overrides)
    return build_m2m_tracker_response(**args)


def test_wrapper_ends_on_the_positions_page_total():
    response = _run()
    assert response["current_mtm"] == -4826.25
    assert response["pnl_series"][-1]["value"] == -4826.25
    assert len(response["pnl_series"]) == 376  # 09:15 to 15:30 inclusive


def test_wrapper_steps_aside_for_an_exchange_it_cannot_value():
    mcx = _position("NRML", exchange="MCX")
    assert _run(positions=[mcx], trades=[]) is None


def test_wrapper_steps_aside_when_a_fill_time_cannot_be_read():
    bad = TRADES + [_trade("MIS", "BUY", 1, 1.0, "not a time")]
    assert (
        _run(trades=bad, parse_time=lambda s: None if s == "not a time" else _parse_time(s)) is None
    )


def test_wrapper_steps_aside_when_a_carried_position_has_no_previous_close():
    def no_close(symbols, **kw):
        ok, body, code = _quotes(symbols)
        for item in body["results"]:
            item["data"]["prev_close"] = None
        return ok, body, code

    assert _run(get_multiquotes_fn=no_close) is None


def test_wrapper_steps_aside_when_candles_cannot_be_fetched():
    assert _run(get_history_fn=lambda **kw: (False, {}, 500)) is None


def test_wrapper_steps_aside_when_quotes_fail():
    assert _run(get_multiquotes_fn=lambda symbols, **kw: (False, {}, 500)) is None


def test_wrapper_before_the_open_returns_the_empty_response():
    early = IST.localize(datetime(2026, 10, 6, 8, 0))
    response = _run(now=early)
    assert response["pnl_series"] == []


def test_wrapper_with_nothing_traded_returns_the_empty_response():
    response = _run(positions=[], trades=[])
    assert response["pnl_series"] == []


# --- the P&L basis (the broker's own figure, per symbol and product) --------------------------


def _with_pnl(positions, pnls):
    return [dict(p, pnl=pnl) for p, pnl in zip(positions, pnls, strict=True)]


def test_frame_uses_a_given_carried_cost_instead_of_the_previous_close():
    index = _index()
    prices = pd.Series(22.7, index=index)
    row = _row("NRML", 195, 22.7, [(_at(15, 15), "SELL", 195, 0.25)], prices)
    row["overnight_cost"] = 11592.75  # Kite's carried cost: 195 x 59.45
    frame = build_m2m_frame(index, [row])
    assert frame["NRML"].loc[_at(15, 14)] == 195 * 22.7 - 11592.75
    assert round(frame["NRML"].iloc[-1], 2) == -11544.0


def test_pnl_basis_ends_on_the_brokers_pnl_total_with_products_kept_apart():
    positions = _with_pnl(POSITIONS, [-448.5, -11544.0])
    response = _run(positions=positions, basis="pnl")
    assert response["current_mtm"] == -11992.5
    assert response["pnl_series"][-1]["value"] == -11992.5


def test_the_two_bases_differ_for_a_carried_position_and_agree_for_an_intraday_one():
    positions = _with_pnl(POSITIONS, [-448.5, -11544.0])
    pnl = _run(positions=positions, basis="pnl")
    m2m = _run(positions=positions, basis="m2m")
    assert pnl["current_mtm"] == -11992.5
    assert m2m["current_mtm"] == -4826.25
    assert pnl["pnl_series"][0]["value"] != m2m["pnl_series"][0]["value"]


def test_pnl_basis_steps_aside_when_the_brokers_pnl_is_missing():
    assert _run(positions=POSITIONS, basis="pnl") is None  # fixtures carry no pnl


def test_an_unknown_basis_steps_aside():
    assert _run(basis="weekly") is None
