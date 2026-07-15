"""
Bookkeeping for which WebSocket clients are subscribed to the
order_update/trade_update/position_update channels, and for mapping a
ZMQ topic (e.g. "zerodha_user1_orders") onto its channel name.

Deliberately has no symbol/exchange/mode dimension, unlike the
market-data subscription_index in websocket_proxy/server.py - OpenAlgo
is single-user/single-broker per deployment, so there is exactly one
account's order/trade/position stream per instance. A client subscribes
to a channel by name, not to a specific session.
"""

ORDER_UPDATE = "order_update"
TRADE_UPDATE = "trade_update"
POSITION_UPDATE = "position_update"

CHANNELS = {ORDER_UPDATE, TRADE_UPDATE, POSITION_UPDATE}

_TOPIC_SUFFIX_TO_CHANNEL = {
    "_orders": ORDER_UPDATE,
    "_trades": TRADE_UPDATE,
    "_positions": POSITION_UPDATE,
}


def channel_for_topic(topic: str) -> str | None:
    """Map a ZMQ topic like 'zerodha_user1_orders' to its channel name,
    or None if it's an ordinary market-data topic (or anything else
    unrelated). Uses suffix matching rather than splitting on "_", since
    a user_id may itself contain underscores."""
    for suffix, channel in _TOPIC_SUFFIX_TO_CHANNEL.items():
        if topic.endswith(suffix):
            return channel
    return None


class OrderChannelRegistry:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[str]] = {channel: set() for channel in CHANNELS}

    def subscribe(self, client_id: str, channel: str) -> bool:
        if channel not in CHANNELS:
            return False
        self._subscribers[channel].add(client_id)
        return True

    def unsubscribe(self, client_id: str, channel: str) -> None:
        self._subscribers.get(channel, set()).discard(client_id)

    def remove_client(self, client_id: str) -> None:
        """Called on client disconnect to clear it from every channel."""
        for subscribers in self._subscribers.values():
            subscribers.discard(client_id)

    def get_subscribers(self, channel: str) -> set[str]:
        return set(self._subscribers.get(channel, set()))
