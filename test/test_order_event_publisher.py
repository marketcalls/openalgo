"""
Tests for websocket_proxy.order_event_publisher.publish_order_events.

The real SharedZmqPublisher is a process-wide singleton wrapping a live
ZMQ socket, so a fake publisher (connect()/publish() spies) is injected
instead of exercising the real ZMQ bus here.
"""

from websocket_proxy.order_event_publisher import publish_order_events, publish_snapshot


class FakePublisher:
    def __init__(self):
        self.connected = False
        self.published = []  # list of (topic, data)

    def connect(self):
        self.connected = True

    def publish(self, topic, data):
        self.published.append((topic, data))


ORDER_EVENT = {"event_type": "order_update", "orderid": "1"}
TRADE_EVENT = {"event_type": "trade_update", "orderid": "1", "tradeid": "1:10:100.0:t1"}
POSITION_EVENT = {"event_type": "position_update", "symbol": "SBIN"}


class TestPublishOrderEvents:
    def test_publishes_order_update_on_orders_topic(self):
        fake = FakePublisher()

        publish_order_events("zerodha", "user1", [ORDER_EVENT], publisher=fake)

        assert fake.published == [("zerodha_user1_orders", ORDER_EVENT)]

    def test_publishes_trade_update_on_trades_topic(self):
        fake = FakePublisher()

        publish_order_events("zerodha", "user1", [TRADE_EVENT], publisher=fake)

        assert fake.published == [("zerodha_user1_trades", TRADE_EVENT)]

    def test_publishes_position_update_on_positions_topic(self):
        fake = FakePublisher()

        publish_order_events("zerodha", "user1", [POSITION_EVENT], publisher=fake)

        assert fake.published == [("zerodha_user1_positions", POSITION_EVENT)]

    def test_publishes_multiple_events_in_order(self):
        fake = FakePublisher()

        publish_order_events(
            "zerodha", "user1", [ORDER_EVENT, TRADE_EVENT, POSITION_EVENT], publisher=fake
        )

        assert [topic for topic, _ in fake.published] == [
            "zerodha_user1_orders",
            "zerodha_user1_trades",
            "zerodha_user1_positions",
        ]

    def test_connects_before_publishing(self):
        fake = FakePublisher()

        publish_order_events("zerodha", "user1", [ORDER_EVENT], publisher=fake)

        assert fake.connected is True

    def test_noop_on_empty_events(self):
        fake = FakePublisher()

        publish_order_events("zerodha", "user1", [], publisher=fake)

        assert fake.connected is False
        assert fake.published == []

    def test_skips_event_with_unknown_event_type_without_raising(self):
        fake = FakePublisher()
        bad_event = {"event_type": "unknown_thing"}

        publish_order_events("zerodha", "user1", [bad_event, ORDER_EVENT], publisher=fake)

        assert fake.published == [("zerodha_user1_orders", ORDER_EVENT)]

    def test_topic_is_scoped_by_broker_and_user(self):
        fake = FakePublisher()

        publish_order_events("dhan", "user2", [ORDER_EVENT], publisher=fake)

        assert fake.published == [("dhan_user2_orders", ORDER_EVENT)]


class TestPublishSnapshot:
    def test_publishes_on_snapshot_topic(self):
        fake = FakePublisher()
        snapshot = {"generation": 3, "orders": [], "trades": [], "positions": []}

        publish_snapshot("zerodha", "user1", snapshot, publisher=fake)

        assert fake.published == [("zerodha_user1_snapshot", snapshot)]

    def test_connects_before_publishing(self):
        fake = FakePublisher()

        publish_snapshot("zerodha", "user1", {"generation": 0}, publisher=fake)

        assert fake.connected is True
