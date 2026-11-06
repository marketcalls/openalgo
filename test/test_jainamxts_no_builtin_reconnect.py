"""The JainamXTS Socket.IO client leaves reconnecting to the adapter.

The adapter retries through ``_on_close -> _connect_with_retry``. If the
Socket.IO client also reconnects on its own, both fire on a drop.
"""

from __future__ import annotations

from broker.jainamxts.streaming.jainamxts_websocket import JainamXTSWebSocketClient


def test_socketio_client_has_builtin_reconnection_disabled():
    client = JainamXTSWebSocketClient("key", "secret", "user")
    assert client.sio.reconnection is False
