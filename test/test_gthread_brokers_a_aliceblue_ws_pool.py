"""AliceBlue's pooled market-data socket: one build per burst, shared subscriptions.

Quotes, depth and multiquotes on AliceBlue go through one market-data socket
per broker session, pooled in ``broker/aliceblue/api/data._WS_REGISTRY``. Two
races lived around it:

* **Concurrent first use built several sockets.** The registry was checked,
  released, and the socket built and connected outside any lock, so the first
  burst after an idle minute (an option chain fires multiquotes, depth and an
  index quote together) sent every request down the build path. Each loser's
  socket was overwritten in the registry and never disconnected; its connect
  had invalidated the winner's server session, and its reconnect loop, which
  has no attempt cap, ran for the life of the worker. Builds now queue on one
  lock and later callers take the socket the first one built, force_new
  included.
* **One request's unsubscribe erased another's tick.** Two requests quoting
  the same instrument both subscribed, and the first to finish unsubscribed at
  the broker and dropped the cached quote while the second was still waiting
  for it. Subscriptions are now counted per instrument.

Both interleavings exist under eventlet too (connect and the wait yield); the
gthread worker only makes them more frequent.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from broker.aliceblue.api import alicebluewebsocket as ws_mod
from broker.aliceblue.api import data as data_mod

THREADS = 16


class FakeSocket:
    """Stands in for AliceBlueWebSocket: connects on a thread after a delay."""

    built: list[FakeSocket] = []
    built_lock = threading.Lock()

    def __init__(self, user_id, session_id):
        self.user_id = user_id
        self.session_id = session_id
        self.is_connected = False
        self.disconnected = False
        with FakeSocket.built_lock:
            FakeSocket.built.append(self)

    def connect(self):
        def finish():
            time.sleep(0.2)
            self.is_connected = True

        threading.Thread(target=finish, daemon=True).start()

    def is_websocket_connected(self):
        return self.is_connected and not self.disconnected

    def disconnect(self):
        self.disconnected = True
        self.is_connected = False


@pytest.fixture
def pool(monkeypatch):
    FakeSocket.built = []
    monkeypatch.setattr(data_mod, "AliceBlueWebSocket", FakeSocket)
    auth = MagicMock()
    auth.query.filter_by.return_value.first.return_value = SimpleNamespace(user_id="U1")
    monkeypatch.setattr(data_mod, "Auth", auth)
    data_mod._WS_REGISTRY.clear()
    yield
    data_mod._WS_REGISTRY.clear()


def _burst(count, call):
    barrier = threading.Barrier(count)
    got: list = [None] * count
    errors: list = []

    def worker(index):
        try:
            barrier.wait(10)
            got[index] = call()
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
        assert not thread.is_alive(), "a caller hung waiting for the socket"
    assert errors == [], errors[:3]
    return got


def _orphans():
    """Sockets built, not registered, and never disconnected: the leak."""
    registered = set(map(id, data_mod._WS_REGISTRY.values()))
    return [s for s in FakeSocket.built if id(s) not in registered and not s.disconnected]


def test_a_burst_of_first_requests_builds_one_socket(pool):
    got = _burst(THREADS, lambda: data_mod.BrokerData("session-1").get_websocket())

    assert len(FakeSocket.built) == 1, f"{len(FakeSocket.built)} sockets built"
    assert all(ws is got[0] for ws in got)
    assert data_mod._WS_REGISTRY == {"session-1": got[0]}
    assert _orphans() == []


def test_a_burst_of_force_new_requests_replaces_the_socket_once(pool):
    broken = FakeSocket("U1", "session-1")
    broken.is_connected = True
    data_mod._WS_REGISTRY["session-1"] = broken

    got = _burst(8, lambda: data_mod.BrokerData("session-1").get_websocket(force_new=True))

    fresh = [s for s in FakeSocket.built if s is not broken]
    assert len(fresh) == 1, f"{len(fresh)} replacement sockets built"
    assert all(ws is fresh[0] for ws in got), "a caller tore down another's fresh socket"
    assert broken.disconnected
    assert _orphans() == []


def test_force_new_alone_still_replaces_a_healthy_socket(pool):
    """The quiet path is unchanged: a lone force_new always rebuilds."""
    first = data_mod.BrokerData("session-1").get_websocket()
    second = data_mod.BrokerData("session-1").get_websocket(force_new=True)

    assert second is not first
    assert first.disconnected
    assert data_mod._WS_REGISTRY == {"session-1": second}


# --- shared subscriptions -----------------------------------------------------


def _client():
    client = ws_mod.AliceBlueWebSocket("U1", "session-1")
    client.ws = MagicMock()
    client.is_connected = True
    return client


def _instrument(exchange="NSE", token="2885"):
    return SimpleNamespace(exchange=exchange, token=token, symbol="RELIANCE-EQ")


def _sent(client):
    import json

    return [json.loads(call.args[0]) for call in client.ws.send.call_args_list]


def test_an_unsubscribe_keeps_a_tick_another_request_is_waiting_for(pool):
    client = _client()
    inst = _instrument()

    assert client.subscribe([inst])  # request A
    assert client.subscribe([inst])  # request B, same instrument
    client.last_quotes["NSE:2885"] = {"ltp": 1300.5}

    client.unsubscribe([inst])  # A is done
    assert client.get_quote("NSE", "2885") == {"ltp": 1300.5}, "B lost the tick it waits on"
    assert "NSE|2885" in client.subscriptions
    assert [m["t"] for m in _sent(client)] == ["t", "t"], "the feed was ended under B"

    client.unsubscribe([inst])  # B is done
    assert client.get_quote("NSE", "2885") is None
    assert client.subscriptions == {} and client.subscribed_tokens == set()
    assert [m["t"] for m in _sent(client)] == ["t", "t", "u"]


def test_a_lone_subscriber_unsubscribes_as_before(pool):
    client = _client()
    keep, drop = _instrument(token="1594"), _instrument(token="2885")
    client.subscribe([keep, drop])
    client.last_quotes.update({"NSE:1594": {"ltp": 1}, "NSE:2885": {"ltp": 2}})

    client.unsubscribe([drop])

    assert client.get_quote("NSE", "1594") == {"ltp": 1}
    assert client.get_quote("NSE", "2885") is None
    assert _sent(client)[-1] == {"t": "u", "k": "NSE|2885"}


def test_a_failed_subscribe_leaves_no_claim_behind(pool):
    client = _client()
    inst = _instrument()
    client.ws.send.side_effect = [OSError("socket closed"), None, None]

    assert client.subscribe([inst]) is False
    assert client.subscribe([inst]) is True
    client.unsubscribe([inst])

    # The failed call took its count back, so one unsubscribe releases it.
    assert client.subscriptions == {}
    assert client._subscription_refs == {}


def test_concurrent_quotes_on_one_instrument_all_see_the_tick(pool):
    """Barrier-driven: every overlapping request reads the tick before any leaves."""
    client = _client()
    inst = _instrument()
    subscribed = threading.Barrier(8)
    seen = []
    lock = threading.Lock()

    def quote_request():
        client.subscribe([inst])
        client.last_quotes["NSE:2885"] = {"ltp": 1300.5}
        subscribed.wait(10)  # all eight are subscribed before any finishes
        with lock:
            seen.append(client.get_quote("NSE", "2885"))
        client.unsubscribe([inst])

    threads = [threading.Thread(target=quote_request) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)

    assert seen == [{"ltp": 1300.5}] * 8
    assert client.subscriptions == {} and client.last_quotes == {}
    assert [m["t"] for m in _sent(client)].count("u") == 1


def test_a_depth_request_gives_its_claim_back_even_when_it_fails(pool, monkeypatch):
    """A claim never given back would keep the instrument subscribed for good."""
    client = _client()
    monkeypatch.setattr(data_mod.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(data_mod, "get_br_symbol", lambda symbol, exchange: symbol)
    monkeypatch.setattr(data_mod, "get_token", lambda symbol, exchange: "2885")
    broker = data_mod.BrokerData("session-1")
    monkeypatch.setattr(broker, "get_websocket", lambda force_new=False: client)

    def broken_read(exchange, token):
        raise RuntimeError("socket closed mid-read")

    monkeypatch.setattr(client, "get_market_depth", broken_read)

    with pytest.raises(Exception, match="socket closed mid-read"):
        broker.get_depth("RELIANCE", "NSE")

    assert client._subscription_refs == {}
    assert client.subscriptions == {}
    assert [m["t"] for m in _sent(client)] == ["d", "u"]
