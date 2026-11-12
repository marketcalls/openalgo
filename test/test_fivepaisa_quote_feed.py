"""5Paisa streaming routing and quote fields.

- MarketFeedV3 frames go to LTP/QUOTE subscriptions, MarketDepthService
  frames to DEPTH subscriptions (docs 10-market-data-websocket.md).
- A depth payload carries the latest MarketFeedV3 quote fields for the same
  (Exch, ExchType, Token), because the proxy forwards DEPTH to QUOTE clients.
- Ticks are matched on Exch/ExchType + Token, not the bare scrip code.
- ChgPcnt is published as percent_change.
- TickDt /Date(-62135596800000)/ (doc sample) is not a time: ltt is omitted.
"""

import threading
from unittest.mock import MagicMock

import pytest

import websocket_proxy  # noqa: F401  (resolves the adapter import cycle)

adapter_mod = pytest.importorskip("broker.fivepaisa.streaming.fivepaisa_adapter")

FEED = {
    "Exch": "N",
    "ExchType": "C",
    "Token": 1660,
    "LastRate": 440.1,
    "LastQty": 5,
    "TotalQty": 1200,
    "High": 447.2,
    "Low": 439.5,
    "OpenRate": 445,
    "PClose": 442.9,
    "AvgRate": 441.3,
    "Time": 35950,
    "BidQty": 10,
    "BidRate": 440.0,
    "OffQty": 12,
    "OffRate": 440.2,
    "TBidQ": 100,
    "TOffQ": 200,
    "TickDt": "/Date(1759900055000)/",
    "ChgPcnt": -0.6321969,
}
DEPTH = {
    "Exch": "N",
    "ExchType": "C",
    "Token": 1660,
    "TBidQ": 86225,
    "TOffQ": 135100,
    "Details": [
        {"Quantity": 50, "Price": 440.0, "NumberOfOrders": 2, "BbBuySellFlag": 66},
        {"Quantity": 25, "Price": 440.2, "NumberOfOrders": 1, "BbBuySellFlag": 83},
    ],
    "TimeStamp": 0,
    "Time": "/Date(1640148238196)/",
}


def _sub(mode, exch="N", exch_type="C", token=1660, symbol="ITC", exchange="NSE"):
    return {
        "symbol": symbol,
        "exchange": exchange,
        "token": str(token),
        "mode": mode,
        "scrip_data": [{"Exch": exch, "ExchType": exch_type, "ScripCode": token}],
    }


def _adapter(*subs):
    adapter = adapter_mod.FivepaisaWebSocketAdapter.__new__(adapter_mod.FivepaisaWebSocketAdapter)
    adapter.logger = MagicMock()
    adapter.lock = threading.Lock()
    adapter.last_snapshot = {}
    adapter.subscriptions = {f"s{i}": s for i, s in enumerate(subs)}
    adapter.publish_market_data = MagicMock()
    return adapter


def _published(adapter):
    return [(c.args[0], c.args[1]) for c in adapter.publish_market_data.call_args_list]


def test_depth_payload_carries_latest_quote_fields():
    adapter = _adapter(_sub(3))
    adapter._on_data(None, dict(FEED))
    assert _published(adapter) == []  # a feed frame is not a depth update
    adapter._on_data(None, dict(DEPTH))
    [(topic, data)] = _published(adapter)
    assert topic == "NSE_ITC_DEPTH"
    assert data["ltp"] == 440.1
    assert data["volume"] == 1200
    assert data["open"] == 445
    assert data["high"] == 447.2
    assert data["low"] == 439.5
    assert data["close"] == 442.9
    assert data["average_price"] == 441.3
    assert data["last_quantity"] == 5
    assert data["percent_change"] == pytest.approx(-0.6321969)
    assert data["ltt"] == 1759900055000
    assert data["total_buy_quantity"] == 86225
    assert data["total_sell_quantity"] == 135100
    assert data["depth"]["buy"][0]["price"] == 440.0
    assert data["depth"]["sell"][0]["price"] == 440.2


def test_depth_before_any_feed_frame_publishes_no_quote_zeros():
    adapter = _adapter(_sub(3))
    adapter._on_data(None, dict(DEPTH))
    [(_, data)] = _published(adapter)
    for key in ("ltp", "volume", "open", "last_quantity"):
        assert key not in data
    assert data["depth"]["buy"]


def test_depth_frame_is_not_published_to_quote_subscription():
    adapter = _adapter(_sub(2))
    adapter._on_data(None, dict(FEED))
    adapter._on_data(None, dict(DEPTH))
    published = _published(adapter)
    assert len(published) == 1
    topic, data = published[0]
    assert topic == "NSE_ITC_QUOTE"
    assert data["volume"] == 1200
    assert data["last_quantity"] == 5
    assert data["percent_change"] == pytest.approx(-0.6321969)
    assert data["ltt"] == 1759900055000


def test_frames_routed_by_exchange_and_segment():
    adapter = _adapter(_sub(2, exch="B", symbol="ITC", exchange="BSE"))
    adapter._on_data(None, dict(FEED))  # Exch N, same token
    assert _published(adapter) == []
    adapter._on_data(None, {**FEED, "Exch": "B"})
    assert [t for t, _ in _published(adapter)] == ["BSE_ITC_QUOTE"]


def test_negative_tickdt_omits_ltt():
    adapter = _adapter(_sub(1), _sub(2))
    adapter._on_data(None, {**FEED, "TickDt": "/Date(-62135596800000)/"})
    for _, data in _published(adapter):
        assert "ltt" not in data
    assert adapter._parse_fivepaisa_time("/Date(-62135596800000)/") == 0
    assert adapter._parse_fivepaisa_time("/Date(1759900055000+0530)/") == 1759900055000


def test_zero_price_holds_last_value_but_quantities_follow_the_feed():
    adapter = _adapter(_sub(2))
    adapter._on_data(None, dict(FEED))
    adapter._on_data(None, {**FEED, "LastRate": 0, "LastQty": 0, "TotalQty": 1300})
    _, data = _published(adapter)[-1]
    assert data["ltp"] == 440.1
    assert data["last_quantity"] == 0
    assert data["volume"] == 1300


def test_unsubscribe_releases_scrip_snapshot(monkeypatch):
    adapter = _adapter(_sub(2))
    adapter._on_data(None, dict(FEED))
    assert ("N", "C", "1660") in adapter.last_snapshot
    adapter.pending_subscriptions = []
    adapter.connected = False
    adapter.ws_client = None
    adapter.subscriptions = {"ITC_NSE_2": _sub(2)}
    # monkeypatch restores the original staticmethod descriptor afterwards;
    # putting back the bare function would leave it unbound for later tests.
    monkeypatch.setattr(
        adapter_mod.SymbolMapper,
        "get_token_from_symbol",
        staticmethod(lambda symbol, exchange: {"token": "1660", "brexchange": "NSE"}),
    )
    adapter.unsubscribe("ITC", "NSE", 2)
    assert adapter.last_snapshot == {}


# --- review follow-ups ---------------------------------------------------------


def test_same_exchange_other_segment_is_not_routed():
    """Cash (C) and derivatives (D) on NSE can share a token: the segment
    decides, so a matching Exch and Token alone must not route the frame."""
    adapter = _adapter(_sub(2, exch="N", exch_type="D", symbol="ITCFUT", exchange="NFO"))
    adapter._on_data(None, dict(FEED))  # Exch N, ExchType C, same token
    assert _published(adapter) == []
    adapter._on_data(None, {**FEED, "ExchType": "D"})
    assert [t for t, _ in _published(adapter)] == ["NFO_ITCFUT_QUOTE"]


def test_frames_for_an_unsubscribed_scrip_keep_no_snapshot():
    adapter = _adapter(_sub(2))
    adapter._on_data(None, {**FEED, "Token": 9999})
    adapter._on_data(None, {**DEPTH, "Token": 9999})
    assert list(adapter.last_snapshot) == [] or all(
        key[-1] != "9999" and key[-1] != 9999 for key in adapter.last_snapshot
    )
    assert not any("9999" in str(key) for key in adapter.last_snapshot)


def test_a_depth_subscriber_still_keeps_the_feed_snapshot():
    """A Depth-only subscription is not published from feed frames, but needs
    their quote fields merged into its depth payloads."""
    adapter = _adapter(_sub(3))
    adapter._on_data(None, dict(FEED))
    adapter._on_data(None, dict(DEPTH))
    depth = [d for t, d in _published(adapter) if t.endswith("_DEPTH")][-1]
    assert depth["ltp"] == 440.1
    assert depth["volume"] == 1200
