"""
Tests for websocket_proxy.order_channel_registry.

Pure bookkeeping for which WebSocket clients are subscribed to the
order_update/trade_update/position_update channels, and for mapping a
ZMQ topic (e.g. "zerodha_user1_orders") to its channel name. No
asyncio/websocket/ZMQ I/O involved - see websocket_proxy/server.py for
where this plugs into the live proxy.
"""

import pytest

from websocket_proxy.order_channel_registry import (
    ORDER_UPDATE,
    POSITION_UPDATE,
    TRADE_UPDATE,
    OrderChannelRegistry,
    channel_for_topic,
)


class TestChannelForTopic:
    def test_maps_orders_suffix(self):
        assert channel_for_topic("zerodha_user1_orders") == ORDER_UPDATE

    def test_maps_trades_suffix(self):
        assert channel_for_topic("zerodha_user1_trades") == TRADE_UPDATE

    def test_maps_positions_suffix(self):
        assert channel_for_topic("zerodha_user1_positions") == POSITION_UPDATE

    def test_returns_none_for_ordinary_market_data_topic(self):
        assert channel_for_topic("NSE_RELIANCE_LTP") is None

    def test_returns_none_for_unrelated_topic(self):
        assert channel_for_topic("zerodha_user1_margins") is None

    def test_user_id_containing_underscores_still_resolves(self):
        # user_id itself may contain underscores - suffix matching (not
        # split-based parsing) must not be thrown off by that.
        assert channel_for_topic("dhan_john_doe_orders") == ORDER_UPDATE


class TestOrderChannelRegistry:
    def test_subscribe_then_get_subscribers_returns_client(self):
        registry = OrderChannelRegistry()

        registry.subscribe("client1", ORDER_UPDATE)

        assert registry.get_subscribers(ORDER_UPDATE) == {"client1"}

    def test_subscribe_rejects_unknown_channel(self):
        registry = OrderChannelRegistry()

        accepted = registry.subscribe("client1", "not_a_real_channel")

        assert accepted is False
        assert registry.get_subscribers("not_a_real_channel") == set()

    def test_multiple_clients_can_subscribe_to_same_channel(self):
        registry = OrderChannelRegistry()

        registry.subscribe("client1", ORDER_UPDATE)
        registry.subscribe("client2", ORDER_UPDATE)

        assert registry.get_subscribers(ORDER_UPDATE) == {"client1", "client2"}

    def test_a_client_can_subscribe_to_multiple_channels(self):
        registry = OrderChannelRegistry()

        registry.subscribe("client1", ORDER_UPDATE)
        registry.subscribe("client1", TRADE_UPDATE)

        assert "client1" in registry.get_subscribers(ORDER_UPDATE)
        assert "client1" in registry.get_subscribers(TRADE_UPDATE)
        assert "client1" not in registry.get_subscribers(POSITION_UPDATE)

    def test_unsubscribe_removes_only_that_channel(self):
        registry = OrderChannelRegistry()
        registry.subscribe("client1", ORDER_UPDATE)
        registry.subscribe("client1", TRADE_UPDATE)

        registry.unsubscribe("client1", ORDER_UPDATE)

        assert registry.get_subscribers(ORDER_UPDATE) == set()
        assert registry.get_subscribers(TRADE_UPDATE) == {"client1"}

    def test_unsubscribe_missing_client_is_a_noop(self):
        registry = OrderChannelRegistry()

        registry.unsubscribe("ghost", ORDER_UPDATE)  # must not raise

        assert registry.get_subscribers(ORDER_UPDATE) == set()

    def test_remove_client_clears_every_channel(self):
        registry = OrderChannelRegistry()
        registry.subscribe("client1", ORDER_UPDATE)
        registry.subscribe("client1", TRADE_UPDATE)
        registry.subscribe("client1", POSITION_UPDATE)
        registry.subscribe("client2", ORDER_UPDATE)

        registry.remove_client("client1")

        assert registry.get_subscribers(ORDER_UPDATE) == {"client2"}
        assert registry.get_subscribers(TRADE_UPDATE) == set()
        assert registry.get_subscribers(POSITION_UPDATE) == set()

    def test_get_subscribers_returns_a_copy_not_a_live_reference(self):
        registry = OrderChannelRegistry()
        registry.subscribe("client1", ORDER_UPDATE)

        snapshot = registry.get_subscribers(ORDER_UPDATE)
        snapshot.add("intruder")

        assert registry.get_subscribers(ORDER_UPDATE) == {"client1"}
