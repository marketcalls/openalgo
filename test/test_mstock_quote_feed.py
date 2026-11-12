"""mstock streaming: ticks route on exchange type and token, and carry the
trade time and last_quantity the packet holds."""

import websocket_proxy  # noqa: F401  isort:skip

import pytest

from broker.mstock.streaming.mstock_adapter import MstockWebSocketAdapter


@pytest.fixture
def adapter():
    a = MstockWebSocketAdapter()
    a.published = []
    a.publish_market_data = lambda topic, data: a.published.append((topic, data))
    a.subscriptions = {
        "nse": {
            "symbol": "INFY",
            "exchange": "NSE",
            "brexchange": "NSE",
            "token": "1594",
            "mode": 2,
            "depth_level": 5,
            "exchange_type": 1,
        },
        "bse": {
            "symbol": "OTHER",
            "exchange": "BSE",
            "brexchange": "BSE",
            "token": "1594",
            "mode": 2,
            "depth_level": 5,
            "exchange_type": 3,
        },
    }
    return a


def _quote_packet(**overrides):
    packet = {
        "subscription_mode": 2,
        "exchange_type": 1,
        "token": "1594",
        "exchange_timestamp": 1730784000000,
        "ltp": 1500.5,
        "last_traded_qty": 25,
        "avg_price": 1498.0,
        "volume": 1000,
        "total_buy_qty": 10.0,
        "total_sell_qty": 20.0,
        "open": 1490.0,
        "high": 1505.0,
        "low": 1485.0,
        "close": 1495.0,
        "last_traded_timestamp": 0,
    }
    packet.update(overrides)
    return packet


def test_tick_routes_on_exchange_type_and_token(adapter):
    adapter._on_data(_quote_packet())

    assert [topic for topic, _ in adapter.published] == ["NSE_INFY_QUOTE"]


def test_quote_carries_exchange_time_and_last_quantity(adapter):
    adapter._on_data(_quote_packet())

    data = adapter.published[0][1]
    assert data["last_quantity"] == 25
    assert data["last_trade_quantity"] == 25
    assert data["last_trade_time"] == 1730784000000
    assert data["ltt"] == 1730784000000


def test_full_packet_prefers_last_traded_timestamp(adapter):
    adapter._on_data(
        _quote_packet(subscription_mode=3, last_traded_timestamp=1730783990, bids=[], asks=[])
    )

    data = adapter.published[0][1]
    assert data["last_trade_time"] == 1730783990
    assert data["exchange_timestamp"] == 1730784000000


def test_no_time_published_when_feed_sends_none(adapter):
    adapter._on_data(_quote_packet(exchange_timestamp=0))
    assert "last_trade_time" not in adapter.published[0][1]


# --- review follow-ups ---------------------------------------------------------


def test_a_tick_for_another_token_on_the_same_exchange_is_not_published(adapter):
    adapter._on_data(_quote_packet(token="2885"))
    assert adapter.published == []


def test_full_packet_without_a_trade_publishes_no_trade_time(adapter):
    adapter._on_data(_quote_packet(subscription_mode=3, last_traded_timestamp=0, bids=[], asks=[]))
    data = adapter.published[0][1]
    assert "last_trade_time" not in data
    assert "ltt" not in data
    assert data["exchange_timestamp"] == 1730784000000


class _FakeClient:
    def __init__(self):
        self.frames = []

    def is_connected(self):
        return True

    def subscribe_batch(self, subs, mode):
        self.frames.append((mode, [(s["exchange_type"], s["token"]) for s in subs]))
        return True


def test_same_token_on_two_exchanges_is_subscribed_for_both(monkeypatch):
    import broker.mstock.streaming.mstock_adapter as mod

    listing = {"INFY": ("1594", "NSE"), "OTHER": ("1594", "BSE")}
    monkeypatch.setattr(
        mod.SymbolMapper,
        "get_token_from_symbol",
        lambda s, e: {"token": listing[s][0], "brexchange": listing[s][1]},
    )
    a = MstockWebSocketAdapter()
    a.ws_client = _FakeClient()
    a.running = True
    a._start_batch_timer = lambda: None

    a.subscribe("INFY", "NSE", 2)
    a.subscribe("OTHER", "BSE", 2)
    assert len(a.subscription_queue) == 2, "the BSE listing must not look already live"

    a._process_batch_subscriptions()
    sent = sorted(pair for _, pairs in a.ws_client.frames for pair in pairs)
    nse, bse = (mod.MstockExchangeMapper.get_exchange_type(x) for x in ("NSE", "BSE"))
    assert sent == sorted([(nse, "1594"), (bse, "1594")])
    assert a.token_modes == {f"{nse}|1594": 2, f"{bse}|1594": 2}
