"""OI Profile sums OI per strike across the selected expiries."""

from datetime import datetime

import pytest

import services.oi_profile_service as svc


@pytest.fixture(autouse=True)
def _clear_profile_cache():
    """Answers are shared for a TTL, so each test starts from an empty cache."""
    svc._profile_cache.clear()
    yield
    svc._profile_cache.clear()


def _chain(expiry, ce_oi, pe_oi):
    return (
        True,
        {
            "status": "success",
            "underlying": "NIFTY",
            "underlying_ltp": 25000,
            "atm_strike": 25000,
            "chain": [
                {
                    "strike": 25000,
                    "ce": {"symbol": f"NIFTY{expiry}25000CE", "oi": ce_oi, "lotsize": 75},
                    "pe": {"symbol": f"NIFTY{expiry}25000PE", "oi": pe_oi, "lotsize": 75},
                }
            ],
        },
        200,
    )


def test_two_expiries_sum_oi_and_change(monkeypatch):
    chains = {"09OCT25": _chain("09OCT25", 100, 40), "30OCT25": _chain("30OCT25", 250, 60)}
    monkeypatch.setattr(
        svc,
        "get_option_chain",
        lambda underlying, exchange, expiry_date, strike_count, api_key: chains[expiry_date],
    )
    monkeypatch.setattr(svc, "_find_futures_symbol", lambda *a, **k: None)
    # Previous day's OI: half of current, for every leg.
    monkeypatch.setattr(
        svc,
        "_fetch_session_open_oi",
        lambda symbols, ex, key, interval=None: {s["symbol"]: s["oi"] / 2 for s in symbols},
    )

    ok, resp, code = svc.get_oi_profile_data(
        underlying="NIFTY",
        exchange="NFO",
        expiry_date="09OCT25",
        interval="5m",
        days=1,
        api_key="k",
        expiry_dates=["09OCT25", "30OCT25"],
    )

    assert ok and code == 200
    row = resp["oi_chain"][0]
    assert row["ce_oi"] == 350 and row["pe_oi"] == 100
    assert row["ce_oi_change"] == 175 and row["pe_oi_change"] == 50
    assert resp["expiry_dates"] == ["09OCT25", "30OCT25"]
    assert "ce_legs" not in row


def test_single_expiry_still_works(monkeypatch):
    monkeypatch.setattr(svc, "get_option_chain", lambda **k: _chain("09OCT25", 100, 40))
    monkeypatch.setattr(svc, "_find_futures_symbol", lambda *a, **k: None)
    monkeypatch.setattr(svc, "_fetch_session_open_oi", lambda symbols, ex, key, interval=None: {})

    ok, resp, _ = svc.get_oi_profile_data(
        underlying="NIFTY",
        exchange="NFO",
        expiry_date="09OCT25",
        interval="5m",
        days=1,
        api_key="k",
    )
    assert ok
    assert resp["oi_chain"][0]["ce_oi"] == 100
    assert resp["expiry_dates"] == ["09OCT25"]


def test_include_change_false_skips_the_history_pass(monkeypatch):
    monkeypatch.setattr(svc, "get_option_chain", lambda **k: _chain("09OCT25", 100, 40))
    monkeypatch.setattr(svc, "_find_futures_symbol", lambda *a, **k: None)

    def _boom(*a, **k):
        raise AssertionError("OI change history must not be fetched")

    monkeypatch.setattr(svc, "_fetch_session_open_oi", _boom)

    ok, resp, _ = svc.get_oi_profile_data(
        underlying="NIFTY",
        exchange="NFO",
        expiry_date="09OCT25",
        interval="5m",
        days=1,
        api_key="k",
        include_change=False,
    )
    assert ok
    assert resp["oi_chain"][0]["ce_oi_change"] == 0


def test_a_repeat_request_is_served_from_the_cache(monkeypatch):
    calls = []

    def _chain_once(**kwargs):
        calls.append(kwargs["expiry_date"])
        return _chain("09OCT25", 100, 40)

    monkeypatch.setattr(svc, "get_option_chain", _chain_once)
    monkeypatch.setattr(svc, "_find_futures_symbol", lambda *a, **k: None)
    monkeypatch.setattr(svc, "_fetch_session_open_oi", lambda symbols, ex, key, interval=None: {})

    args = {
        "underlying": "NIFTY",
        "exchange": "NFO",
        "expiry_date": "09OCT25",
        "interval": "5m",
        "days": 1,
        "api_key": "k",
    }
    first_ok, first, _ = svc.get_oi_profile_data(**args)
    second_ok, second, _ = svc.get_oi_profile_data(**args)

    assert first_ok and second_ok
    assert calls == ["09OCT25"], "the second request must not reach the broker"
    assert second is first
    assert "market_open" in first


def test_include_candles_false_skips_the_futures_lookup(monkeypatch):
    monkeypatch.setattr(svc, "get_option_chain", lambda **k: _chain("09OCT25", 100, 40))
    monkeypatch.setattr(svc, "_fetch_session_open_oi", lambda symbols, ex, key, interval=None: {})

    def _boom(*a, **k):
        raise AssertionError("futures must not be looked up")

    monkeypatch.setattr(svc, "_find_futures_symbol", _boom)

    ok, resp, _ = svc.get_oi_profile_data(
        underlying="NIFTY",
        exchange="NFO",
        expiry_date="09OCT25",
        interval="5m",
        days=1,
        api_key="k",
        include_candles=False,
    )
    assert ok
    assert resp["candles"] == []
    assert resp["futures_symbol"] is None


def _bar(ts, oi):
    """One-minute bar at a given IST time string, e.g. "2026-09-16 09:15"."""
    import pytz

    ist = pytz.timezone("Asia/Kolkata")
    t = int(ist.localize(datetime.strptime(ts, "%Y-%m-%d %H:%M")).timestamp())
    return {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "oi": oi, "timestamp": t}


def test_session_open_oi_is_the_first_bar_of_the_latest_day():
    bars = [
        _bar("2026-09-15 09:15", 2_895_490),
        _bar("2026-09-15 15:29", 4_784_065),
        _bar("2026-09-16 09:15", 6_614_400),
        _bar("2026-09-16 09:16", 7_569_120),
    ]
    assert svc._session_open_oi(bars) == 6_614_400


def test_session_open_oi_does_not_anchor_on_the_prior_session():
    # PORTED DEFECT: the anchor used to be the previous *daily* candle's OI,
    # which is the last value seen during that session and not the settled
    # figure the next session opens on. Measured live on 16-Sep-2026,
    # NIFTY22SEP2623200PE: daily 15-Sep closed 4,552,925 while 16-Sep opened
    # 6,614,400, so every strike showed a two-million phantom build before a
    # single contract had traded.
    bars = [_bar("2026-09-15 15:29", 4_552_925), _bar("2026-09-16 09:15", 6_614_400)]
    assert svc._session_open_oi(bars) == 6_614_400


def test_session_open_oi_ignores_bar_order():
    bars = [_bar("2026-09-16 09:20", 7_000_000), _bar("2026-09-16 09:15", 6_614_400)]
    assert svc._session_open_oi(bars) == 6_614_400


def test_session_open_oi_is_zero_without_usable_bars():
    assert svc._session_open_oi([]) == 0.0
    assert svc._session_open_oi([{"oi": 5}]) == 0.0


def test_strike_count_reaches_the_chain_and_keys_the_cache(monkeypatch):
    asked = []

    def _chain_spy(**kwargs):
        asked.append(kwargs["strike_count"])
        return _chain("09OCT25", 100, 40)

    monkeypatch.setattr(svc, "get_option_chain", _chain_spy)
    monkeypatch.setattr(svc, "_find_futures_symbol", lambda *a, **k: None)
    monkeypatch.setattr(svc, "_fetch_session_open_oi", lambda symbols, ex, key, interval=None: {})

    base = {
        "underlying": "NIFTY",
        "exchange": "NFO",
        "expiry_date": "09OCT25",
        "interval": "5m",
        "days": 1,
        "api_key": "k",
    }
    ok_a, resp_a, _ = svc.get_oi_profile_data(**base, strike_count=5)
    ok_b, _, _ = svc.get_oi_profile_data(**base, strike_count=25)

    assert ok_a and ok_b
    assert asked == [5, 25], "a different window must not be served yesterday's cache entry"
    assert resp_a["strike_count"] == 5


def test_window_anchor_is_the_oi_entering_the_first_selected_bar():
    # PORTED DEFECT: the anchor was the bar starting at window_start, but a
    # bar's OI is its closing value, so the window's own first bar was not
    # counted. Measured live on 16-Sep-2026: a 09:15-09:25 window on
    # NIFTY22SEP2623200PE read 450,125 where the build was 1,892,020.
    bars = [
        _bar("2026-09-16 09:15", 6_614_400),
        _bar("2026-09-16 09:16", 7_569_120),
        _bar("2026-09-16 09:17", 8_046_675),
    ]
    start = bars[1]["timestamp"]
    assert svc._oi_entering(bars, start) == 6_614_400
    assert svc._oi_at_or_before(bars, bars[2]["timestamp"]) == 8_046_675


def test_window_anchor_does_not_reach_back_across_a_session():
    # Reaching into yesterday for the anchor is the settlement gap again.
    bars = [_bar("2026-09-15 15:29", 4_552_925), _bar("2026-09-16 09:15", 6_614_400)]
    assert svc._oi_entering(bars, bars[1]["timestamp"]) == 6_614_400


def test_anchor_prefers_one_minute_bars():
    # The anchor's granularity is its error, so 1m leads and the chart's own
    # interval is only the fallback for a broker that does not serve it.
    assert svc._anchor_intervals("5m") == ["1m", "5m"]
    assert svc._anchor_intervals("1m") == ["1m"]


def test_an_unreadable_leg_is_unknown_not_a_zero_anchor(monkeypatch):
    # A zero anchor subtracted from a live number reports the leg's whole open
    # interest as today's build, so one broker hiccup paints a strike as a huge
    # fresh write. Absent means unknown, and unknown draws nothing.
    monkeypatch.setattr(svc, "_history_rows", lambda *a, **k: None)
    legs = [{"symbol": "NIFTY22SEP2623200PE", "oi": 8_506_420}]
    assert svc._fetch_session_open_oi(legs, "NFO", "k") == {}


def test_a_leg_whose_history_has_no_oi_is_also_unknown(monkeypatch):
    monkeypatch.setattr(svc, "_history_rows", lambda *a, **k: [_bar("2026-09-16 09:15", 0)])
    legs = [{"symbol": "NIFTY22SEP2623200PE", "oi": 8_506_420}]
    assert svc._fetch_session_open_oi(legs, "NFO", "k") == {}


def test_an_unknown_anchor_leaves_the_change_at_zero(monkeypatch):
    monkeypatch.setattr(
        svc,
        "get_option_chain",
        lambda underlying, exchange, expiry_date, strike_count, api_key: _chain("09OCT25", 100, 40),
    )
    monkeypatch.setattr(svc, "_find_futures_symbol", lambda *a, **k: None)
    monkeypatch.setattr(svc, "_history_rows", lambda *a, **k: None)

    ok, resp, _ = svc.get_oi_profile_data(
        underlying="NIFTY",
        exchange="NFO",
        expiry_date="09OCT25",
        interval="5m",
        days=1,
        api_key="k",
    )
    assert ok
    row = resp["oi_chain"][0]
    assert row["ce_oi"] == 100 and row["ce_oi_change"] == 0
    assert row["pe_oi"] == 40 and row["pe_oi_change"] == 0
