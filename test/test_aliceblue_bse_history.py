"""BSE historical data must not be hard-blocked (issue #1775, bug C).

get_history refused BSE before issuing any request, lumping it in with BCD.
That was wrong for BSE. Probed against a live account:

    BSE RELIANCE  D  365d -> 247 rows
    BSE RELIANCE  5m  30d -> 1621 rows
    BSE RELIANCE  1m   5d -> 1706 rows

Because it short-circuited before the HTTP call, nothing in the logs hinted the
data was there, so it read as a broker limitation rather than our own guard. The
effect was no BSE history anywhere: charts, /api/v1/history, Historify,
indicators.

BCD stays blocked - that one really is unsupported.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

data_mod = pytest.importorskip("broker.aliceblue.api.data")


def _broker():
    b = data_mod.BrokerData.__new__(data_mod.BrokerData)
    b.session_id = "jwt"
    b.timeframe_map = {"1m": "1", "5m": "5", "D": "D"}
    b._RESAMPLE_TIMEFRAMES = {}
    return b


def _api_rows(n=3):
    return {
        "result": [
            {
                "time": f"2026-08-0{i + 1} 00:00:00",
                "open": 1,
                "high": 2,
                "low": 0.5,
                "close": 1.5,
                "volume": 100,
            }
            for i in range(n)
        ]
    }


@pytest.mark.parametrize("interval", ["D", "5m", "1m"])
def test_bse_history_is_requested_not_refused(interval):
    """The guard must not short-circuit before the HTTP call."""
    b = _broker()
    client = MagicMock()
    client.post.return_value = MagicMock(
        status_code=200, json=MagicMock(return_value=_api_rows()), raise_for_status=MagicMock()
    )

    with (
        patch.object(data_mod, "get_httpx_client", return_value=client),
        patch.object(data_mod, "get_token", return_value="500325"),
        patch.object(data_mod, "get_br_symbol", return_value="RELIANCE"),
        patch.object(data_mod, "apply_rate_limit"),
    ):
        df = b.get_history("RELIANCE", "BSE", interval, "2026-08-01", "2026-08-03")

    assert client.post.called, f"BSE {interval} was refused without contacting AliceBlue"
    assert isinstance(df, pd.DataFrame)
    assert not df.empty, f"BSE {interval} returned no rows despite the API answering"


def test_bcd_is_still_blocked_without_a_request():
    """BCD genuinely is unsupported; do not spend a call discovering that."""
    b = _broker()
    client = MagicMock()

    with (
        patch.object(data_mod, "get_httpx_client", return_value=client),
        patch.object(data_mod, "get_token", return_value="1001"),
        patch.object(data_mod, "get_br_symbol", return_value="USDINR"),
        patch.object(data_mod, "apply_rate_limit"),
    ):
        df = b.get_history("USDINR", "BCD", "D", "2026-08-01", "2026-08-03")

    assert df.empty
    assert not client.post.called, "BCD should short-circuit, not call the API"


def test_nse_is_unaffected():
    b = _broker()
    client = MagicMock()
    client.post.return_value = MagicMock(
        status_code=200, json=MagicMock(return_value=_api_rows()), raise_for_status=MagicMock()
    )

    with (
        patch.object(data_mod, "get_httpx_client", return_value=client),
        patch.object(data_mod, "get_token", return_value="2885"),
        patch.object(data_mod, "get_br_symbol", return_value="RELIANCE"),
        patch.object(data_mod, "apply_rate_limit"),
    ):
        df = b.get_history("RELIANCE", "NSE", "D", "2026-08-01", "2026-08-03")

    assert client.post.called
    assert not df.empty
