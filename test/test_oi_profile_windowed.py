"""OI Profile's OI-change calculation must pick the windowed path only when
both window_start and window_end are given, and fall back to the existing
"vs previous day's close" path otherwise. get_oi_profile_data() branches on
this internally (services/oi_profile_service.py) - a wrong branch means every
call silently reuses the wrong OI baseline, so this pins the branch itself
rather than the OI math each path already had before this change.
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import oi_profile_service as svc  # noqa: E402

CHAIN_RESPONSE = {
    "underlying": "NIFTY",
    "atm_strike": 24000,
    "underlying_ltp": 24000,
    "chain": [
        {
            "strike": 24000,
            "ce": {"oi": 100, "symbol": "NIFTY24000CE", "lotsize": 50},
            "pe": {"oi": 80, "symbol": "NIFTY24000PE", "lotsize": 50},
        }
    ],
}


def _run(window_start=None, window_end=None):
    with (
        patch.object(svc, "get_option_chain", return_value=(True, CHAIN_RESPONSE, 200)),
        patch.object(svc, "_find_futures_symbol", return_value=None),
        patch.object(svc, "_fetch_session_open_oi", return_value={}) as daily_mock,
        patch.object(svc, "_fetch_windowed_oi_changes", return_value={}) as windowed_mock,
    ):
        svc.get_oi_profile_data(
            underlying="NIFTY",
            exchange="NFO",
            expiry_date="10SEP26",
            interval="5m",
            days=1,
            api_key="test-key",
            window_start=window_start,
            window_end=window_end,
        )
        return daily_mock, windowed_mock


def test_default_call_uses_daily_path():
    daily_mock, windowed_mock = _run()
    daily_mock.assert_called_once()
    windowed_mock.assert_not_called()


def test_windowed_call_uses_windowed_path():
    daily_mock, windowed_mock = _run(window_start=1_700_000_000, window_end=1_700_003_600)
    windowed_mock.assert_called_once()
    daily_mock.assert_not_called()
    # interval, window_start, window_end must reach the windowed helper as given
    call_args = windowed_mock.call_args.args
    assert call_args[2] == "5m"  # interval
    assert call_args[3] == 1_700_000_000  # window_start
    assert call_args[4] == 1_700_003_600  # window_end


def test_oi_at_or_before_picks_last_candle_not_after_target():
    candles = [
        {"time": 100, "oi": 10},
        {"time": 200, "oi": 20},
        {"time": 300, "oi": 30},
    ]
    assert svc._oi_at_or_before(candles, 250) == 20
    assert svc._oi_at_or_before(candles, 300) == 30
    assert svc._oi_at_or_before(candles, 50) == 0.0
