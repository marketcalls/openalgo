"""OI Profile sums OI per strike across the selected expiries."""

from datetime import datetime

import pytest

import services.oi_profile_service as svc


@pytest.fixture(autouse=True)
def _clear_profile_cache(monkeypatch):
    """Answers are shared for a TTL, so each test starts from an empty cache.

    NSE's bhavcopy is switched off by default too: it is a real download, and
    these tests are about the per-leg fallback. The tests that are about the
    file switch it back on with one built in the test.
    """
    monkeypatch.setattr(svc, "_nse_previous_session_oi", lambda exchange: None)
    monkeypatch.setattr(svc, "_nse_cached_book", lambda exchange: None)
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


def _anchored(legs, exchange="NFO"):
    """What the anchor pass ends up knowing for `legs`, warm pass included.

    The pass itself no longer fetches inline - it hands the legs to a worker -
    so a test about what it *learns* has to let that worker finish.
    """
    svc._prev_oi_cache.clear()
    svc._fetch_prev_session_oi(legs, exchange, "k")
    svc._anchor_executor.submit(lambda: None).result(timeout=30)
    known, pending = svc._fetch_prev_session_oi(legs, exchange, "k")
    assert pending is False, "every leg should have a final answer by now"
    return known


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
        "_fetch_prev_session_oi",
        lambda symbols, ex, key, interval=None: (
            {s["symbol"]: s["oi"] / 2 for s in symbols},
            False,
        ),
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
    monkeypatch.setattr(
        svc, "_fetch_prev_session_oi", lambda symbols, ex, key, interval=None: ({}, False)
    )

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

    monkeypatch.setattr(svc, "_fetch_prev_session_oi", _boom)

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
    monkeypatch.setattr(
        svc, "_fetch_prev_session_oi", lambda symbols, ex, key, interval=None: ({}, False)
    )

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
    monkeypatch.setattr(
        svc, "_fetch_prev_session_oi", lambda symbols, ex, key, interval=None: ({}, False)
    )

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


def test_anchor_is_the_previous_session_close(monkeypatch):
    # PORTED DEFECT: the anchor was briefly the *current* session's opening
    # bar, on the theory that the overnight step from the previous daily
    # candle was a settlement artefact. Measured against NSE on 16-Sep-2026 it
    # is not: NIFTY22SEP2623200PE closed 15-Sep at 4,552,925, which is exactly
    # NSE's 70,045 contracts at a lot size of 65, and NSE reported the day's
    # change from there. Anchoring on the 6,614,400 opening bar showed 85%
    # where NSE and Sensibull both showed 170%.
    bars = [_bar("2026-09-15 15:29", 4_552_925), _bar("2026-09-16 09:15", 6_614_400)]
    assert svc._previous_session_oi(bars) == 4_552_925


def test_anchor_skips_a_repeated_trailing_session():
    # Outside market hours the broker appends a row for the new calendar date
    # carrying the last quote, so the newest two rows are the same session
    # twice. Taking rows[-2] blindly compares a session against itself and
    # reports every strike as unchanged.
    bars = [
        _bar("2026-09-14 15:29", 3_000_000),
        _bar("2026-09-15 15:29", 4_552_925),
        _bar("2026-09-16 09:15", 4_552_925),
    ]
    assert svc._previous_session_oi(bars) == 3_000_000


def test_anchor_is_zero_without_a_previous_session():
    assert svc._previous_session_oi([]) == 0.0
    assert svc._previous_session_oi([_bar("2026-09-16 09:15", 6_614_400)]) == 0.0


def test_strike_count_reaches_the_chain_and_keys_the_cache(monkeypatch):
    asked = []

    def _chain_spy(**kwargs):
        asked.append(kwargs["strike_count"])
        return _chain("09OCT25", 100, 40)

    monkeypatch.setattr(svc, "get_option_chain", _chain_spy)
    monkeypatch.setattr(svc, "_find_futures_symbol", lambda *a, **k: None)
    monkeypatch.setattr(
        svc, "_fetch_prev_session_oi", lambda symbols, ex, key, interval=None: ({}, False)
    )

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


def test_the_window_anchor_prefers_one_minute_bars():
    # A drag-selected window's anchor granularity is its error, so 1m leads
    # and the chart's own interval is only the fallback for a broker that does
    # not serve it. The daily anchor above is a different path: its bar size
    # is always 'D', because that row is the exchange's settled figure.
    assert svc._anchor_intervals("5m") == ["1m", "5m"]
    assert svc._anchor_intervals("1m") == ["1m"]


def test_an_unreadable_leg_is_unknown_not_a_zero_anchor(monkeypatch):
    # A zero anchor subtracted from a live number reports the leg's whole open
    # interest as today's build, so one broker hiccup paints a strike as a huge
    # fresh write. Absent means unknown, and unknown draws nothing.
    monkeypatch.setattr(svc, "_history_rows", lambda *a, **k: None)
    legs = [{"symbol": "NIFTY22SEP2623200PE", "oi": 8_506_420}]
    assert _anchored(legs) == {}


def test_a_leg_whose_history_has_no_oi_is_also_unknown(monkeypatch):
    monkeypatch.setattr(
        svc,
        "_history_rows",
        lambda *a, **k: [_bar("2026-09-15 15:29", 0), _bar("2026-09-16 09:15", 0)],
    )
    legs = [{"symbol": "NIFTY22SEP2623200PE", "oi": 8_506_420}]
    assert _anchored(legs) == {}


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


def test_a_cold_underlying_answers_at_once_and_reports_the_change_as_pending(monkeypatch):
    # The symptom this exists for: switching the chart to a stock nobody has
    # looked at today has no anchor for any of its legs, and fetching them
    # inline made the request take a broker history call per leg. It held the
    # connection for 30-90s, the chart's own history call for the new symbol
    # timed out at 15s behind it, and switching twice put two chains' worth of
    # calls in flight. The request must not wait for the anchor pass at all.
    import threading
    import time

    released = threading.Event()

    def slow_history(*a, **k):
        released.wait(timeout=30)
        return [_bar("2026-09-15 15:29", 50), _bar("2026-09-16 09:15", 60)]

    monkeypatch.setattr(svc, "_history_rows", slow_history)
    monkeypatch.setattr(
        svc,
        "get_option_chain",
        lambda underlying, exchange, expiry_date, strike_count, api_key: _chain("09OCT25", 100, 40),
    )
    monkeypatch.setattr(svc, "_find_futures_symbol", lambda *a, **k: None)
    svc._prev_oi_cache.clear()

    started = time.monotonic()
    ok, resp, _ = svc.get_oi_profile_data(
        underlying="NIFTY",
        exchange="NFO",
        expiry_date="09OCT25",
        interval="5m",
        days=1,
        api_key="k",
        include_candles=False,
    )
    elapsed = time.monotonic() - started
    released.set()

    assert ok
    assert elapsed < 1.0, f"the request waited {elapsed:.1f}s on the anchor pass"
    assert resp["oi_change_pending"] is True
    # Open interest is complete even so - only the change columns are waiting.
    assert resp["oi_chain"][0]["ce_oi"] == 100

    # And a pending answer is not pinned in the shared cache, or the client
    # polling for the rest would keep getting the same gaps back.
    assert not svc._profile_cache


def test_a_newer_selection_abandons_the_chain_being_warmed(monkeypatch):
    # Switching symbols twice in a minute used to put two chains' worth of
    # broker history calls in flight at once - ~50 threads, a dropped market
    # feed and a chart that never loaded. The warm pass has one worker and the
    # newest selection wins: the old chain stops where it is, keeping whatever
    # it already cached.
    calls = []
    later = [{"symbol": "LATER1", "oi": 10}, {"symbol": "LATER2", "oi": 10}]

    def recording_history(symbol, *a, **k):
        calls.append(symbol)
        if len(calls) == 1:
            # The user switches the chart while the first chain is warming.
            svc._fetch_prev_session_oi(later, "NFO", "k")
        return [_bar("2026-09-15 15:29", 50), _bar("2026-09-16 09:15", 60)]

    monkeypatch.setattr(svc, "_history_rows", recording_history)
    svc._prev_oi_cache.clear()

    earlier = [{"symbol": f"EARLY{i}", "oi": 10} for i in range(5)]
    svc._fetch_prev_session_oi(earlier, "NFO", "k")
    svc._anchor_executor.submit(lambda: None).result(timeout=30)

    assert [c for c in calls if c.startswith("EARLY")] == ["EARLY0"], calls
    assert sorted(c for c in calls if c.startswith("LATER")) == ["LATER1", "LATER2"], calls


def test_a_failed_warm_pass_does_not_wedge_the_pending_state(monkeypatch):
    # Nobody reads the warm job's future. If it dies mid-chain, its legs must
    # not stay listed as "being warmed" - that suppresses the resubmit, and the
    # client would poll a pending answer every 10s that could never fill.
    def exploding_history(*a, **k):
        raise RuntimeError("broker said no")

    monkeypatch.setattr(svc, "_history_rows", exploding_history)
    svc._prev_oi_cache.clear()
    legs = [{"symbol": "WEDGE1", "oi": 10}]

    svc._fetch_prev_session_oi(legs, "NFO", "k")
    svc._anchor_executor.submit(lambda: None).result(timeout=30)

    calls = []
    monkeypatch.setattr(svc, "_history_rows", lambda symbol, *a, **k: calls.append(symbol) or None)
    svc._fetch_prev_session_oi(legs, "NFO", "k")
    svc._anchor_executor.submit(lambda: None).result(timeout=30)
    assert calls == ["WEDGE1"], "the next request must be able to retry the leg"
