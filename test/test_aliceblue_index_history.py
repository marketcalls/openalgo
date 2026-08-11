"""AliceBlue index history needs the undocumented "::index" exchange suffix.

The chart API answers "No data available" for every index token unless the
exchange is sent as "NSE::index" rather than "NSE". Probed live against a real
account, plain "NSE" failed for NIFTY 50 on every exchange spelling (NSE,
NSE_INDEX, INDICES, NFO, nse, nse_cm, nse_idx, IDX, INDEX, NSE_INDICES), every
resolution (D, 1, 1D) and every window (2024, 2025, last 5 days, last 2 years),
while a futures contract and an ETF returned data from the same session.

That is what made index history look like a broker limitation (#1776). It is
not. The suffix appears nowhere in the REST reference, but AliceBlue's own SDK
sends it - Ant-A3-tradehub-sdk-production, TradeMaster/TradeSync.py:

    "exchange": instrument.exchange if not indices
                else f"{instrument.exchange}::index"

With the suffix, NIFTY 50 / NIFTY BANK / INDIA VIX / NIFTY FIN SERVICE /
NIFTY MIDCAP SELECT / SENSEX / BANKEX all return daily and 1m candles back
2 years.

The suffix is index-only: "NSE::index" with an equity token returns nothing,
just as "NSE" with an index token does. So it must be applied to the index
exchanges and to nothing else.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

data_mod = pytest.importorskip("broker.aliceblue.api.data")


def _capture_payload(symbol, exchange, timeframe="D"):
    """Run get_history and return the payload that reached the chart API."""
    bd = data_mod.BrokerData("session-token")
    captured = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"stat": "Ok", "result": []}

    def _post(url, headers=None, json=None, timeout=None):
        captured.update(json or {})
        return _Resp()

    client = MagicMock()
    client.post.side_effect = _post

    with (
        patch.object(data_mod, "get_token", return_value="26000"),
        patch.object(data_mod, "get_httpx_client", return_value=client),
        patch.object(data_mod, "apply_rate_limit"),
    ):
        bd.get_history(symbol, exchange, timeframe, "2026-07-01", "2026-08-07")

    return captured


@pytest.mark.parametrize(
    "exchange,expected",
    [
        ("NSE_INDEX", "NSE::index"),
        ("BSE_INDEX", "BSE::index"),
        ("MCX_INDEX", "MCX::index"),
    ],
)
def test_index_exchanges_get_the_suffix(exchange, expected):
    assert _capture_payload("NIFTY", exchange)["exchange"] == expected


@pytest.mark.parametrize("exchange", ["NSE", "BSE", "NFO", "BFO", "MCX", "CDS"])
def test_tradable_exchanges_are_sent_unchanged(exchange):
    """"NSE::index" with an equity token returns nothing, so the suffix must
    not leak onto non-index requests."""
    sent = _capture_payload("RELIANCE", exchange)["exchange"]
    assert sent == exchange
    assert "::index" not in sent


def test_the_suffix_survives_intraday_requests():
    """Resampled timeframes route through the same 1m fetch."""
    assert _capture_payload("NIFTY", "NSE_INDEX", "1m")["exchange"] == "NSE::index"


def test_the_futures_proxy_is_gone():
    """Index history was previously faked from the nearest futures contract.

    Futures carry basis, so an indicator computed over the proxy was not the
    index's, and nothing on the chart said a substitution had happened. Now
    that the real data is reachable there is no reason to keep it, and no
    reason to let it come back.
    """
    assert not hasattr(data_mod.BrokerData, "_get_index_history_via_futures")

    source = open(data_mod.__file__, encoding="utf-8").read()
    assert "fno_search_symbols" not in source, "futures-proxy lookup reintroduced"
