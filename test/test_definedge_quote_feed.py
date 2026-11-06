"""Definedge streaming: every subscribed mode receives each tick, built from
the merged per-scrip snapshot, with OpenAlgo's reference keys."""

import websocket_proxy  # noqa: F401  isort:skip

import pytest

from broker.definedge.streaming.definedge_adapter import DefinedgeWebSocketAdapter


def _sub(mode):
    return {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "brexchange": "NSE",
        "definedge_exchange": "NSE",
        "token": "2885",
        "scrip": "NSE|2885",
        "mode": mode,
        "depth_level": 5,
        "actual_depth": 5,
    }


@pytest.fixture
def adapter():
    a = DefinedgeWebSocketAdapter()
    a.published = []
    a.publish_market_data = lambda topic, data: a.published.append((topic, data))
    return a


def _topics(adapter, suffix):
    return [data for topic, data in adapter.published if topic.endswith(suffix)]


TOUCHLINE = {
    "t": "tf",
    "e": "NSE",
    "tk": "2885",
    "ft": "1730784000",
    "lp": "1395.40",
    "pc": "0.32",
    "v": "11238602",
    "o": "1382.60",
    "h": "1398.00",
    "l": "1378.50",
    "c": "1391.00",
    "ap": "1391.24",
}

DEPTH = {
    "t": "df",
    "e": "NSE",
    "tk": "2885",
    "lp": "1395.50",
    "ltt": "14:25:31",
    "ltq": "7",
    "tbq": "120952",
    "tsq": "131730",
    "bp1": "1395.40",
    "bq1": "10",
    "sp1": "1395.60",
    "sq1": "12",
    "bp2": "1395.35",
    "sp2": "1395.65",
}


def test_touchline_reaches_quote_even_when_depth_subscribed_first(adapter):
    adapter.subscriptions = {"d": _sub(3), "q": _sub(2)}

    adapter._on_data(None, dict(TOUCHLINE))

    quotes = _topics(adapter, "_QUOTE")
    assert len(quotes) == 1
    assert quotes[0]["ltp"] == 1395.40
    assert quotes[0]["percent_change"] == 0.32
    # No depth data cached yet: Depth gets nothing rather than an empty book
    assert _topics(adapter, "_DEPTH") == []
    assert all(data for _, data in adapter.published)


def test_depth_tick_publishes_full_quote_and_depth(adapter):
    adapter.subscriptions = {"l": _sub(1), "q": _sub(2), "d": _sub(3)}

    adapter._on_data(None, dict(TOUCHLINE))
    adapter.published.clear()
    adapter._on_depth_data(None, dict(DEPTH))

    quote = _topics(adapter, "_QUOTE")[-1]
    assert quote["ltp"] == 1395.50
    assert quote["open"] == 1382.60
    assert quote["average_price"] == 1391.24
    assert quote["percent_change"] == 0.32
    assert quote["last_quantity"] == 7
    assert quote["last_trade_time"] == "14:25:31"
    # ltt carries the broker's last trade time, not the feed time
    assert quote["ltt"] == "14:25:31"

    depth = _topics(adapter, "_DEPTH")[-1]
    assert depth["average_price"] == 1391.24
    assert depth["percent_change"] == 0.32
    assert depth["total_buy_quantity"] == 120952
    assert depth["total_sell_quantity"] == 131730
    assert depth["total_buy_qty"] == 120952
    assert depth["last_quantity"] == 7
    assert depth["ltt"] == "14:25:31"
    assert depth["depth"]["buy"][0]["price"] == 1395.40

    assert _topics(adapter, "_LTP")[-1]["ltp"] == 1395.50


def test_touchline_after_depth_refreshes_depth_with_quote_fields(adapter):
    adapter.subscriptions = {"d": _sub(3), "q": _sub(2)}
    adapter._on_depth_data(None, dict(DEPTH))
    adapter.published.clear()

    adapter._on_data(None, {"t": "tf", "e": "NSE", "tk": "2885", "lp": "1396.00"})

    depth = _topics(adapter, "_DEPTH")[-1]
    assert depth["ltp"] == 1396.00
    assert depth["total_buy_quantity"] == 120952
    assert _topics(adapter, "_QUOTE")[-1]["ltp"] == 1396.00


def test_reference_keys_absent_when_feed_did_not_send_them(adapter):
    adapter.subscriptions = {"q": _sub(2)}
    adapter._on_data(None, {"t": "tf", "e": "NSE", "tk": "2885", "lp": "10", "ft": "123"})

    quote = _topics(adapter, "_QUOTE")[-1]
    assert "last_quantity" not in quote
    assert "last_trade_time" not in quote
    assert "percent_change" not in quote
    assert quote["ltt"] == "123"


def test_other_exchange_token_is_not_published(adapter):
    adapter.subscriptions = {"q": _sub(2)}
    adapter._on_data(None, {"t": "tf", "e": "BSE", "tk": "2885", "lp": "10"})
    assert adapter.published == []


# --- Quote takes the depth feed too, and never publishes unreceived fields -----


def _subscribe(adapter, mode, monkeypatch):
    import broker.definedge.streaming.definedge_adapter as mod

    monkeypatch.setattr(
        mod.SymbolMapper,
        "get_token_from_symbol",
        lambda s, e: {"token": "2885", "brexchange": "NSE"},
    )
    adapter.connected = True
    adapter.ws_client = object()
    adapter._start_batch_timer = lambda: None
    return adapter.subscribe("RELIANCE", "NSE", mode)


def test_quote_subscribes_the_touchline_and_the_depth_feed(adapter, monkeypatch):
    assert _subscribe(adapter, 2, monkeypatch)["status"] == "success"
    assert {q["type"] for q in adapter.subscription_queue} == {"tick", "depth"}


def test_ltp_subscribes_only_the_touchline(adapter, monkeypatch):
    assert _subscribe(adapter, 1, monkeypatch)["status"] == "success"
    assert {q["type"] for q in adapter.subscription_queue} == {"tick"}


def test_depth_ack_fills_a_quote_only_subscriber_without_a_depth_topic(adapter):
    adapter.subscriptions = {"q": _sub(2)}
    # A touchline ack without OHLC, then the depth ack with the full snapshot
    adapter._on_data(None, {"t": "tk", "e": "NSE", "tk": "2885", "lp": "1395.40"})
    adapter._on_depth_data(None, {**DEPTH, "t": "dk", "o": "1382.60", "c": "1391.00"})

    assert _topics(adapter, "_DEPTH") == []
    quote = _topics(adapter, "_QUOTE")[-1]
    assert quote["open"] == 1382.60
    assert quote["close"] == 1391.00
    assert quote["last_quantity"] == 7
    assert quote["last_trade_time"] == "14:25:31"
    assert quote["total_buy_quantity"] == 120952


def test_quote_never_publishes_fields_not_received_as_zero(adapter):
    adapter.subscriptions = {"q": _sub(2)}
    adapter._on_data(None, {"t": "tf", "e": "NSE", "tk": "2885", "lp": "1800.10"})

    quote = _topics(adapter, "_QUOTE")[-1]
    assert quote["ltp"] == 1800.10
    for key in ("open", "high", "low", "close", "volume", "average_price", "oi", "bid"):
        assert key not in quote, key


def test_unsubscribing_quote_releases_both_feeds(adapter, monkeypatch):
    _subscribe(adapter, 2, monkeypatch)
    calls = []

    class _Ws:
        def unsubscribe(self, sub_type, tokens):
            calls.append(sub_type)
            return True

    adapter.ws_client = _Ws()
    adapter.unsubscribe("RELIANCE", "NSE", 2)
    assert sorted(calls) == ["depth", "tick"]
    assert "NSE|2885" not in adapter.ws_subscription_refs


def test_unsubscribing_quote_keeps_the_depth_feed_a_depth_subscriber_needs(adapter, monkeypatch):
    _subscribe(adapter, 3, monkeypatch)
    _subscribe(adapter, 2, monkeypatch)
    calls = []

    class _Ws:
        def unsubscribe(self, sub_type, tokens):
            calls.append(sub_type)
            return True

    adapter.ws_client = _Ws()
    adapter.unsubscribe("RELIANCE", "NSE", 2)
    assert calls == ["tick"]
    assert adapter.ws_subscription_refs["NSE|2885"]["depth_count"] == 1, (
        "Quote gave back its depth reference; the Depth subscriber holds the other"
    )


# --- review follow-ups ---------------------------------------------------------


class _RecordingWs:
    def __init__(self):
        self.calls = []

    def unsubscribe(self, sub_type, tokens):
        self.calls.append(sub_type)
        return True


def test_two_clients_on_one_symbol_release_the_feed_when_both_leave(adapter, monkeypatch):
    _subscribe(adapter, 1, monkeypatch)
    _subscribe(adapter, 1, monkeypatch)
    ws = _RecordingWs()
    adapter.ws_client = ws

    adapter.unsubscribe("RELIANCE", "NSE", 1)
    assert ws.calls == [], "the other client still needs the touchline"
    adapter.unsubscribe("RELIANCE", "NSE", 1)
    assert ws.calls == ["tick"]
    assert "NSE|2885" not in adapter.ws_subscription_refs


def test_a_dash_ltp_does_not_stop_the_other_modes(adapter):
    adapter.subscriptions = {"l": _sub(1), "q": _sub(2)}
    adapter._on_data(None, {**TOUCHLINE, "lp": "-"})

    assert _topics(adapter, "_LTP") == [], "no price, nothing to send on LTP"
    quote = _topics(adapter, "_QUOTE")[-1]
    assert quote["open"] == 1382.60


def test_a_level_one_only_depth_message_publishes_depth(adapter):
    adapter.subscriptions = {"d": _sub(3)}
    adapter._on_depth_data(
        None,
        {"t": "df", "e": "NSE", "tk": "2885", "lp": "1395.50", "bp1": "1395.40", "sp1": "1395.60"},
    )
    depth = _topics(adapter, "_DEPTH")[-1]
    assert depth["depth"]["buy"][0]["price"] == 1395.40
    assert depth["depth"]["sell"][0]["price"] == 1395.60
