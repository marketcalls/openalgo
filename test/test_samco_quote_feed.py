"""Samco streaming quote fields and tick routing.

- The exchange last-trade time (lTrdT / ltt / lttUTC, docs
  13-streaming-data.md) is published as ltt and last_trade_time; the local
  clock never stands in for it.
- avgPr, tBQ / tSQ (tbq / taq on quote2) are published as average_price,
  total_buy_quantity and total_sell_quantity in quote and depth.
- A tick is matched to a subscription by scrip code AND segment: the same
  scrip code on another segment is another instrument.
"""

import threading
from unittest.mock import MagicMock

import pytest

import websocket_proxy  # noqa: F401  (resolves the adapter import cycle)

ws_mod = pytest.importorskip("broker.samco.streaming.samcoWebSocket")
adapter_mod = pytest.importorskip("broker.samco.streaming.samco_adapter")

# Sample quote frame from docs 13-streaming-data.md
DOC_QUOTE = {
    "aPr": "44561.00",
    "bPr": "44554.00",
    "aSz": "1",
    "bSz": "1",
    "sym": "2885_NSE",
    "avgPr": "44371.85",
    "c": "44119.00",
    "h": "44786.00",
    "l": "43969.00",
    "o": "44105.00",
    "oI": "361290",
    "ch": "435.00",
    "chPer": "0.99",
    "lTrdT": "01 Oct 2019, 06:47:03 PM",
    "ltp": "44554.00",
    "ltq": "1",
    "ltt": "01 Oct 2019, 06:47:03 PM",
    "lttUTC": "01 Oct 2019, 01:17:03 PM",
    "tBQ": "973",
    "tSQ": "610",
    "vol": "782763833.41",
    "streaming_type": "quote",
}
# 2019-10-01 18:47:03 IST == 13:17:03 UTC
DOC_LTT_MS = 1569935823000


def _ws():
    ws = ws_mod.SamcoWebSocket.__new__(ws_mod.SamcoWebSocket)
    ws._tick_state = {}
    ws._tick_state_lock = threading.Lock()
    ws.logger = MagicMock()
    return ws


def _adapter(subscriptions):
    adapter = adapter_mod.SamcoWebSocketAdapter.__new__(adapter_mod.SamcoWebSocketAdapter)
    adapter.logger = MagicMock()
    adapter.lock = threading.Lock()
    adapter.subscriptions = subscriptions
    adapter.publish_market_data = MagicMock()
    return adapter


def _sub(token, brexchange, exchange, mode, symbol="SYM"):
    return {
        "symbol": symbol,
        "exchange": exchange,
        "brexchange": brexchange,
        "token": token,
        "mode": mode,
    }


def test_exchange_trade_time_is_published_as_ltt():
    normalized = _ws()._normalize_market_data(dict(DOC_QUOTE), "quote")
    adapter = _adapter({})
    for mode in (1, 2, 3):
        data = adapter._normalize_market_data(normalized, mode)
        assert data["ltt"] == DOC_LTT_MS
        assert data["last_trade_time"] == DOC_LTT_MS


def test_utc_trade_time_used_when_ist_fields_absent():
    frame = {k: v for k, v in DOC_QUOTE.items() if k not in ("lTrdT", "ltt")}
    normalized = _ws()._normalize_market_data(frame, "quote")
    assert normalized["last_trade_time_ms"] == DOC_LTT_MS


def test_ltt_omitted_when_samco_sends_no_trade_time():
    frame = {k: v for k, v in DOC_QUOTE.items() if k not in ("lTrdT", "ltt", "lttUTC")}
    normalized = _ws()._normalize_market_data(frame, "quote")
    data = _adapter({})._normalize_market_data(normalized, 2)
    assert "ltt" not in data
    assert "last_trade_time" not in data


def test_average_price_and_totals_published_in_quote_and_depth():
    normalized = _ws()._normalize_market_data(dict(DOC_QUOTE), "quote")
    adapter = _adapter({})
    for mode in (2, 3):
        data = adapter._normalize_market_data(normalized, mode)
        assert data["average_price"] == pytest.approx(44371.85)
        assert data["total_buy_quantity"] == 973
        assert data["total_sell_quantity"] == 610
    assert adapter._normalize_market_data(normalized, 2)["last_quantity"] == 1


def test_depth_frame_totals_tbq_taq_published():
    ws = _ws()
    ws._normalize_market_data(dict(DOC_QUOTE), "quote")
    depth_frame = {
        "symbol": "2885_NSE",
        "tbq": "1778050",
        "taq": "5471990",
        "bidValues": [{"price": "44554", "qty": "1", "no": "1"}],
        "askValues": [{"price": "44561", "qty": "1", "no": "1"}],
    }
    normalized = ws._normalize_market_data(depth_frame, "quote2")
    data = _adapter({})._normalize_market_data(normalized, 3)
    assert data["total_buy_quantity"] == 1778050
    assert data["total_sell_quantity"] == 5471990
    assert data["average_price"] == pytest.approx(44371.85)
    assert data["ltt"] == DOC_LTT_MS


def test_fields_not_sent_are_left_out():
    normalized = _ws()._normalize_market_data({"sym": "1_NSE", "ltp": "10"}, "quote")
    data = _adapter({})._normalize_market_data(normalized, 2)
    for key in ("average_price", "total_buy_quantity", "total_sell_quantity", "ltt"):
        assert key not in data


def test_tick_from_another_segment_is_not_routed():
    adapter = _adapter({"a": _sub("11536", "NFO", "NFO", 2)})
    adapter._on_data(None, {"symbol": "11536_NSE", "subscription_mode": 2})
    adapter.publish_market_data.assert_not_called()


def test_tick_from_the_subscribed_segment_is_routed():
    adapter = _adapter(
        {
            "nfo": _sub("11536", "NFO", "NFO", 2, symbol="FUT"),
            "nse": _sub("11536", "NSE", "NSE", 2, symbol="EQ"),
        }
    )
    adapter._on_data(None, {"symbol": "11536_NFO", "subscription_mode": 2})
    topics = [c.args[0] for c in adapter.publish_market_data.call_args_list]
    assert topics == ["NFO_FUT_QUOTE"]


def test_mcx_tick_routed_by_streaming_segment():
    # MCX derivatives stream as <scrip>_MFO; brexchange MFO maps to MFO.
    adapter = _adapter({"m": _sub("464925", "MFO", "MCX", 1, symbol="CRUDE")})
    adapter._on_data(None, {"symbol": "464925_MFO", "subscription_mode": 2})
    assert adapter.publish_market_data.call_count == 1


# --- review follow-ups ---------------------------------------------------------


def test_a_zero_depth_total_is_kept_not_replaced_by_the_quote_total():
    """quote2 reports tbq/taq of 0 (numeric: the string "0" was already kept);
    the merged state also holds the quote stream's tBQ/tSQ. 0 is a real total
    and must not fall back to them."""
    ws = _ws()
    ws._normalize_market_data(dict(DOC_QUOTE), "quote")  # tBQ 973, tSQ 610
    normalized = ws._normalize_market_data(
        {"symbol": "2885_NSE", "tbq": 0, "taq": 0, "bidValues": [], "askValues": []},
        "quote2",
    )
    data = _adapter({})._normalize_market_data(normalized, 3)
    assert data["total_buy_quantity"] == 0
    assert data["total_sell_quantity"] == 0


def test_a_bare_scrip_code_shared_by_two_segments_is_not_routed():
    adapter = _adapter(
        {
            "nfo": _sub("11536", "NFO", "NFO", 2, symbol="FUT"),
            "nse": _sub("11536", "NSE", "NSE", 2, symbol="EQ"),
        }
    )
    adapter._on_data(None, {"symbol": "11536", "subscription_mode": 2})
    adapter.publish_market_data.assert_not_called()


def test_a_bare_scrip_code_in_one_segment_and_an_index_id_are_routed():
    adapter = _adapter(
        {
            "nse": _sub("11536", "NSE", "NSE", 2, symbol="EQ"),
            "idx": _sub("-23", "NSE", "NSE_INDEX", 1, symbol="NIFTY"),
        }
    )
    adapter._on_data(None, {"symbol": "11536", "subscription_mode": 2})
    adapter._on_data(None, {"symbol": "-23", "subscription_mode": 2})
    topics = [c.args[0] for c in adapter.publish_market_data.call_args_list]
    assert topics == ["NSE_EQ_QUOTE", "NSE_INDEX_NIFTY_LTP"]
