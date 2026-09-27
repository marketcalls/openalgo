"""AliceBlue market-data WebSocket reuse across BrokerData instances.

services/quotes_service.py builds a fresh BrokerData for every request, so the
old cache - an instance attribute, self._websocket - could never hit. Each
quotes call therefore invalidated, recreated, reconnected and re-authenticated
the entire session: 692ms of churn around 64ms of data, and two REST calls
(invalidateWsSess + createWsSess) every time.

That matters beyond latency. AliceBlue allows 1800 requests / 15 minutes for
everything except orders, so an option chain polling every 5s spent about a
fifth of the quota on session churn alone.

The connection now lives in a module-level registry keyed by session_id, which
is what these tests pin: reuse must survive a new BrokerData.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

data_mod = pytest.importorskip("broker.aliceblue.api.data")


@pytest.fixture(autouse=True)
def clean_registry():
    data_mod._WS_REGISTRY.clear()
    yield
    data_mod._WS_REGISTRY.clear()


def _live_socket():
    ws = MagicMock()
    ws.is_connected = True
    ws.is_websocket_connected = MagicMock(return_value=True)
    return ws


def _broker(session_id="jwt-session-1"):
    b = data_mod.BrokerData.__new__(data_mod.BrokerData)
    b.session_id = session_id
    return b


def test_a_second_brokerdata_reuses_the_live_connection():
    """The actual bug: the service makes a new BrokerData per request."""
    created = []

    def factory(user_id, session_id):
        created.append(session_id)
        return _live_socket()

    with (
        patch.object(data_mod, "AliceBlueWebSocket", side_effect=factory),
        patch.object(data_mod, "Auth") as auth,
    ):
        auth.query.filter_by.return_value.first.return_value = MagicMock(user_id="1412368")

        first = _broker().get_websocket()
        second = _broker().get_websocket()  # different instance, same session

    assert first is second, "a new BrokerData rebuilt the socket instead of reusing it"
    assert len(created) == 1, f"connected {len(created)} times; expected 1"


def test_a_dead_connection_is_replaced_and_the_old_one_closed():
    dead = _live_socket()
    dead.is_websocket_connected = MagicMock(return_value=False)
    data_mod._WS_REGISTRY["jwt-session-1"] = dead

    with (
        patch.object(data_mod, "AliceBlueWebSocket", return_value=_live_socket()),
        patch.object(data_mod, "Auth") as auth,
    ):
        auth.query.filter_by.return_value.first.return_value = MagicMock(user_id="1412368")
        fresh = _broker().get_websocket()

    assert fresh is not dead
    assert dead.disconnect.called, "the dead socket was leaked instead of disconnected"


def test_force_new_replaces_even_a_healthy_connection():
    healthy = _live_socket()
    data_mod._WS_REGISTRY["jwt-session-1"] = healthy

    with (
        patch.object(data_mod, "AliceBlueWebSocket", return_value=_live_socket()),
        patch.object(data_mod, "Auth") as auth,
    ):
        auth.query.filter_by.return_value.first.return_value = MagicMock(user_id="1412368")
        fresh = _broker().get_websocket(force_new=True)

    assert fresh is not healthy
    assert healthy.disconnect.called


def test_a_new_session_supersedes_and_closes_the_old_socket():
    """After the ~3am token rollover the old socket must not be left behind.

    OpenAlgo is single-user/single-broker, so a second session_id means the
    token rolled over. Keeping the previous entry would strand a socket and its
    reader and heartbeat threads every day in a worker that never restarts.
    """
    with (
        patch.object(data_mod, "AliceBlueWebSocket", side_effect=lambda u, s: _live_socket()),
        patch.object(data_mod, "Auth") as auth,
    ):
        auth.query.filter_by.return_value.first.return_value = MagicMock(user_id="1412368")

        old = _broker("jwt-session-1").get_websocket()
        new = _broker("jwt-session-2").get_websocket()

    assert old is not new
    assert set(data_mod._WS_REGISTRY) == {"jwt-session-2"}, "the superseded session leaked"
    assert old.disconnect.called, "the superseded socket was never closed"


def test_close_all_websockets_empties_the_registry():
    """Logout revokes the session behind these sockets; they must not outlive it."""
    a, b = _live_socket(), _live_socket()
    data_mod._WS_REGISTRY.update({"s1": a, "s2": b})

    data_mod.close_all_websockets()

    assert data_mod._WS_REGISTRY == {}
    assert a.disconnect.called and b.disconnect.called


def test_no_session_id_returns_none_without_connecting():
    with patch.object(data_mod, "AliceBlueWebSocket") as ctor:
        assert _broker(session_id=None).get_websocket() is None
    assert not ctor.called
