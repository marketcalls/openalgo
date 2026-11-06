"""JainamXTS leaves reconnecting to its adapter alone.

On a drop the client's ``_on_disconnect`` hands off to the adapter, whose
``_connect_with_retry`` logs in again and reconnects. If python-socketio's own
reconnect loop also runs, the two race and can open two sessions. Issue #1356.
"""

from broker.jainamxts.streaming.jainamxts_websocket import JainamXTSWebSocketClient


def test_socketio_builtin_reconnection_is_disabled():
    client = JainamXTSWebSocketClient(api_key="key", api_secret="secret", user_id="user")

    assert client.sio.reconnection is False
