"""Motilal market-data WebSocket reuse across BrokerData instances.

services/quotes_service.py and services/depth_service.py build a fresh
BrokerData for every request, so the old cache - an instance attribute,
self._websocket - could never hit. Every depth and multiquote call therefore
opened a brand new socket, and nothing ever closed it: the request handlers
unregister their scrips, which does not close the connection.

Those abandoned clients did not even become garbage - MotilalWebSocket.connect()
starts a reader thread bound to the instance - and their on_close handler kept
scheduling reconnects, so file descriptors and threads grew with request volume
rather than with users.

The connection now lives in a module-level registry keyed by the auth token,
which is what these tests pin: reuse must survive a new BrokerData.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

data_mod = pytest.importorskip("broker.motilal.api.data")
ws_mod = pytest.importorskip("broker.motilal.api.motilal_websocket")


@pytest.fixture(autouse=True)
def clean_registry():
    data_mod._WS_REGISTRY.clear()
    yield
    data_mod._WS_REGISTRY.clear()


@pytest.fixture(autouse=True)
def stub_client_code():
    """get_client_code() reads the auth DB; the socket identity is not under test."""
    with patch.object(data_mod, "get_client_code", return_value="AA020"):
        yield


def _live_socket():
    ws = MagicMock()
    ws.is_connected = True
    return ws


def _broker(auth_token="authtok-1"):
    b = data_mod.BrokerData.__new__(data_mod.BrokerData)
    b.auth_token = auth_token
    b._websocket = None
    return b


def test_a_second_brokerdata_reuses_the_live_connection():
    """The actual bug: the service makes a new BrokerData per request."""
    created = []

    def factory(client_id, auth_token, api_key):
        created.append(auth_token)
        return _live_socket()

    with patch.object(ws_mod, "MotilalWebSocket", side_effect=factory):
        first = _broker().get_websocket()
        second = _broker().get_websocket()  # different instance, same session

    assert first is second, "a new BrokerData rebuilt the socket instead of reusing it"
    assert len(created) == 1, f"connected {len(created)} times; expected 1"


def test_a_dead_connection_is_replaced_and_the_old_one_closed():
    dead = _live_socket()
    dead.is_connected = False
    data_mod._WS_REGISTRY["authtok-1"] = dead

    with patch.object(ws_mod, "MotilalWebSocket", return_value=_live_socket()):
        fresh = _broker().get_websocket()

    assert fresh is not dead
    assert dead.disconnect.called, "the dead socket was leaked instead of disconnected"


def test_force_new_replaces_even_a_healthy_connection():
    healthy = _live_socket()
    data_mod._WS_REGISTRY["authtok-1"] = healthy

    with patch.object(ws_mod, "MotilalWebSocket", return_value=_live_socket()):
        fresh = _broker().get_websocket(force_new=True)

    assert fresh is not healthy
    assert healthy.disconnect.called


def test_a_new_session_supersedes_and_closes_the_old_socket():
    """After the 6am token expiry the old socket must not be left behind.

    OpenAlgo is single-user/single-broker, so a second auth token means the
    token rolled over. Keeping the previous entry would strand a socket and its
    reader thread every day in a worker that never restarts.
    """
    with patch.object(ws_mod, "MotilalWebSocket", side_effect=lambda c, a, k: _live_socket()):
        old = _broker("authtok-1").get_websocket()
        new = _broker("authtok-2").get_websocket()

    assert old is not new
    assert set(data_mod._WS_REGISTRY) == {"authtok-2"}, "the superseded session leaked"
    assert old.disconnect.called, "the superseded socket was never closed"


def test_a_socket_that_never_connects_is_closed_not_registered():
    """A failed handshake must not leave its reader thread running."""
    stillborn = MagicMock()
    stillborn.is_connected = False

    with patch.object(ws_mod, "MotilalWebSocket", return_value=stillborn):
        with patch.object(data_mod.time, "monotonic", side_effect=[0, 99, 99]):
            assert _broker().get_websocket() is None

    assert stillborn.disconnect.called, "the unconnected socket was leaked"
    assert data_mod._WS_REGISTRY == {}


def test_a_socket_that_lost_the_registration_race_is_closed():
    """Two requests can miss the cache together; only one socket may survive.

    The socket is built outside the registry lock - connecting takes ~250ms and
    holding the lock would serialise every caller - so a cold start with two
    concurrent requests builds two. Registering the late one over the incumbent
    would strand the incumbent: precisely the leak the registry exists to stop.
    The incumbent wins because other requests may already be registering scrips
    on it.
    """
    incumbent = _live_socket()
    late = _live_socket()

    def factory(client_id, auth_token, api_key):
        # Another thread finished connecting while we were building ours.
        data_mod._WS_REGISTRY[auth_token] = incumbent
        return late

    with patch.object(ws_mod, "MotilalWebSocket", side_effect=factory):
        got = _broker().get_websocket()

    assert got is incumbent, "the late socket was registered over the incumbent"
    assert late.disconnect.called, "the duplicate socket was leaked"
    assert data_mod._WS_REGISTRY["authtok-1"] is incumbent


def test_close_all_websockets_empties_the_registry():
    """Logout revokes the session behind these sockets; they must not outlive it."""
    a, b = _live_socket(), _live_socket()
    data_mod._WS_REGISTRY.update({"s1": a, "s2": b})

    data_mod.close_all_websockets()

    assert data_mod._WS_REGISTRY == {}
    assert a.disconnect.called and b.disconnect.called


def test_no_auth_token_returns_none_without_connecting():
    with patch.object(ws_mod, "MotilalWebSocket") as ctor:
        assert _broker(auth_token=None).get_websocket() is None
    assert not ctor.called
