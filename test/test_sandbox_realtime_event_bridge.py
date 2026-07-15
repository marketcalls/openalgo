"""
Tests for sandbox.realtime_event_bridge.publish_sandbox_fill.

Sandbox already knows the exact order/trade/position state the instant
a fill happens (see sandbox/execution_engine.py), so this bridges that
straight onto the order_update/trade_update/position_update WebSocket
channels - bypassing the REST poller/diff engine entirely for sandbox
mode. publish_order_events is monkeypatched so no real ZMQ socket is
involved.
"""

from unittest.mock import patch

import pytest

from sandbox.realtime_event_bridge import publish_sandbox_fill

ORDER = {
    "orderid": "SB-1",
    "symbol": "SBIN",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 10,
    "price": 825.5,
    "product": "MIS",
    "pricetype": "MARKET",
    "order_status": "complete",
    "timestamp": "2026-07-15 09:16:23",
}

TRADE = {
    "orderid": "SB-1",
    "symbol": "SBIN",
    "exchange": "NSE",
    "product": "MIS",
    "action": "BUY",
    "quantity": 10,
    "average_price": 825.5,
    "trade_value": 8255.0,
    "timestamp": "2026-07-15 09:16:23",
}

POSITION = {
    "symbol": "SBIN",
    "exchange": "NSE",
    "product": "MIS",
    "quantity": 10,
    "average_price": 825.5,
    "ltp": 825.5,
    "pnl": 0.0,
}


class TestPublishSandboxFill:
    @patch("sandbox.realtime_event_bridge.publish_order_events")
    def test_publishes_order_and_trade_events(self, mock_publish):
        publish_sandbox_fill("zerodha", "user1", ORDER, TRADE)

        assert mock_publish.call_count == 1
        broker, user_id, events = mock_publish.call_args[0]
        assert broker == "zerodha"
        assert user_id == "user1"
        assert [e["event_type"] for e in events] == ["order_update", "trade_update"]
        assert events[0]["orderid"] == "SB-1"
        assert events[1]["fill_quantity"] == 10

    @patch("sandbox.realtime_event_bridge.publish_order_events")
    def test_includes_position_event_when_position_given(self, mock_publish):
        publish_sandbox_fill("zerodha", "user1", ORDER, TRADE, position=POSITION)

        _, _, events = mock_publish.call_args[0]
        assert [e["event_type"] for e in events] == [
            "order_update",
            "trade_update",
            "position_update",
        ]
        assert events[2]["net_quantity"] == 10

    @patch("sandbox.realtime_event_bridge.publish_order_events")
    def test_omits_position_event_when_position_not_given(self, mock_publish):
        publish_sandbox_fill("zerodha", "user1", ORDER, TRADE, position=None)

        _, _, events = mock_publish.call_args[0]
        assert len(events) == 2

    @patch("sandbox.realtime_event_bridge.publish_order_events")
    def test_never_raises_when_publish_fails(self, mock_publish):
        mock_publish.side_effect = RuntimeError("zmq boom")

        # must not propagate - a WS delivery failure must never break
        # sandbox order execution
        publish_sandbox_fill("zerodha", "user1", ORDER, TRADE)

    @patch("sandbox.realtime_event_bridge.publish_order_events")
    def test_skips_publishing_when_broker_unresolved(self, mock_publish):
        publish_sandbox_fill(None, "user1", ORDER, TRADE)

        mock_publish.assert_not_called()
