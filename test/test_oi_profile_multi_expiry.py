"""OI Profile sums OI per strike across the selected expiries."""

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
    monkeypatch.setattr(svc, "get_option_chain", lambda underlying, exchange, expiry_date, strike_count, api_key: chains[expiry_date])
    monkeypatch.setattr(svc, "_find_futures_symbol", lambda *a, **k: None)
    # Previous day's OI: half of current, for every leg.
    monkeypatch.setattr(
        svc,
        "_fetch_daily_oi_changes",
        lambda symbols, ex, key: {s["symbol"]: s["oi"] / 2 for s in symbols},
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
    monkeypatch.setattr(svc, "_fetch_daily_oi_changes", lambda symbols, ex, key: {})

    ok, resp, _ = svc.get_oi_profile_data(
        underlying="NIFTY", exchange="NFO", expiry_date="09OCT25", interval="5m", days=1, api_key="k"
    )
    assert ok
    assert resp["oi_chain"][0]["ce_oi"] == 100
    assert resp["expiry_dates"] == ["09OCT25"]


def test_include_change_false_skips_the_history_pass(monkeypatch):
    monkeypatch.setattr(svc, "get_option_chain", lambda **k: _chain("09OCT25", 100, 40))
    monkeypatch.setattr(svc, "_find_futures_symbol", lambda *a, **k: None)

    def _boom(*a, **k):
        raise AssertionError("OI change history must not be fetched")

    monkeypatch.setattr(svc, "_fetch_daily_oi_changes", _boom)

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
    monkeypatch.setattr(svc, "_fetch_daily_oi_changes", lambda symbols, ex, key: {})

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
    monkeypatch.setattr(svc, "_fetch_daily_oi_changes", lambda symbols, ex, key: {})

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


def _candle(close, oi, volume=100):
    return {"open": close, "high": close, "low": close, "close": close, "volume": volume, "oi": oi}


def test_previous_session_ignores_a_duplicated_trailing_candle():
    # After hours the broker appends a candle for the new date carrying the
    # last quote, so the newest two rows are identical. Yesterday is the one
    # before that pair, not the copy.
    candles = [_candle(120, 1_000_000), _candle(30, 3_800_000), _candle(30, 3_800_000)]
    assert svc._previous_session_oi(candles) == 1_000_000


def test_previous_session_is_the_prior_row_during_a_live_session():
    candles = [_candle(120, 1_000_000), _candle(30, 3_800_000), _candle(28, 3_900_000)]
    assert svc._previous_session_oi(candles) == 3_800_000


def test_previous_session_is_zero_without_two_sessions():
    assert svc._previous_session_oi([_candle(30, 3_800_000)]) == 0.0
    assert svc._previous_session_oi([]) == 0.0


def test_strike_count_reaches_the_chain_and_keys_the_cache(monkeypatch):
    asked = []

    def _chain_spy(**kwargs):
        asked.append(kwargs["strike_count"])
        return _chain("09OCT25", 100, 40)

    monkeypatch.setattr(svc, "get_option_chain", _chain_spy)
    monkeypatch.setattr(svc, "_find_futures_symbol", lambda *a, **k: None)
    monkeypatch.setattr(svc, "_fetch_daily_oi_changes", lambda symbols, ex, key: {})

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
