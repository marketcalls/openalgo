import websocket_proxy  # noqa: F401  isort:skip

import pytest

from broker.indmoney.streaming import indmoney_adapter as adapter_module
from broker.indmoney.streaming.indmoney_adapter import IndmoneyWebSocketAdapter

TOKENS = {
    ("NIFTY03NOV2623300CE", "NFO"): {"token": "53940", "brexchange": "NSE"},
    ("NIFTY", "NSE_INDEX"): {"token": "40000001", "brexchange": "NSE"},
    ("RELIANCE", "NSE"): {"token": "2885", "brexchange": "NSE"},
    ("RELIANCE26NOVFUT", "BFO"): {"token": "2885", "brexchange": "BSE"},
}


class FakeWsClient:
    def __init__(self):
        self.unsubscribed = []

    def subscribe(self, instruments, mode):
        pass

    def unsubscribe(self, instruments, mode):
        self.unsubscribed.append((tuple(instruments), mode))


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.setattr(
        adapter_module.SymbolMapper,
        "get_token_from_symbol",
        staticmethod(lambda symbol, exchange: TOKENS.get((symbol, exchange))),
    )
    a = IndmoneyWebSocketAdapter()
    a.connected = True
    a.ws_client = FakeWsClient()
    a._start_batch_timer = lambda: None
    a.published = []
    a.publish_market_data = lambda topic, data: a.published.append((topic, data))
    return a


def _tick(instrument, mode, data):
    return {"mode": mode, "instrument": instrument, "timestamp": 1, "data": data}


def test_depth_subscription_is_served_from_the_quote_stream(adapter):
    result = adapter.subscribe("NIFTY03NOV2623300CE", "NFO", mode=3)

    assert result["status"] == "success"
    assert adapter.subscription_queue == [{"instrument_token": "NFO:53940", "mode": "quote"}]

    adapter._on_data(None, _tick("53940", "quote", {"open": 49, "high": 112.5, "close": 91}))

    topic, data = adapter.published[-1]
    assert topic == "NFO_NIFTY03NOV2623300CE_DEPTH"
    assert data["ltp"] == 91
    assert data["mode"] == 3


def test_ltp_and_depth_on_one_instrument_each_get_their_stream(adapter):
    adapter.subscribe("NIFTY03NOV2623300CE", "NFO", mode=1)
    adapter.subscribe("NIFTY03NOV2623300CE", "NFO", mode=3)

    adapter._on_data(None, _tick("53940", "ltp", {"ltp": 90.5}))
    adapter._on_data(None, _tick("53940", "quote", {"close": 91}))

    assert [topic for topic, _ in adapter.published] == [
        "NFO_NIFTY03NOV2623300CE_LTP",
        "NFO_NIFTY03NOV2623300CE_DEPTH",
    ]


def test_quote_tick_without_close_keeps_the_last_ltp(adapter):
    adapter.subscribe("NIFTY", "NSE_INDEX", mode=2)

    adapter._on_data(None, _tick("40000001", "quote", {"close": 23302.5, "volume": 0}))
    adapter._on_data(None, _tick("40000001", "quote", {"volume": 0}))

    assert [data["ltp"] for _, data in adapter.published] == [23302.5, 23302.5]


def test_unsubscribing_depth_keeps_the_quote_feed_another_mode_uses(adapter):
    adapter.subscribe("NIFTY03NOV2623300CE", "NFO", mode=2)
    adapter.subscribe("NIFTY03NOV2623300CE", "NFO", mode=3)

    adapter.unsubscribe("NIFTY03NOV2623300CE", "NFO", mode=3)
    assert adapter.ws_client.unsubscribed == []
    assert len(adapter.subscription_queue) == 2

    adapter.subscriptions["keep_alive"] = {"instrument_token": "NSE:1", "indmoney_mode": "ltp"}
    adapter.unsubscribe("NIFTY03NOV2623300CE", "NFO", mode=2)
    assert adapter.ws_client.unsubscribed == [(("NFO:53940",), "quote")]
    assert adapter.subscription_queue == []


def test_bare_token_on_two_segments_is_still_dropped(adapter):
    adapter.subscribe("RELIANCE", "NSE", mode=1)
    adapter.subscribe("RELIANCE26NOVFUT", "BFO", mode=1)

    adapter._on_data(None, _tick("2885", "ltp", {"ltp": 1426}))

    assert adapter.published == []
