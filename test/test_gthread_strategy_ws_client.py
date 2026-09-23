"""The in-process websocket client's lifecycle.

``services/websocket_client.py`` is the one market data connection the
scalping risk monitor, the strategy tick feed and the websocket service share.
Four lifecycle defects, each pinned here:

* it counted reconnects for its whole life and stopped for good at the fifth,
  while staying cached and ``running``: after the fifth proxy restart in a
  worker's lifetime every tick-driven scalping stop went quiet;
* a failed connect returned with both of its threads still running;
* ``get_websocket_client`` held one global lock across a connect of up to 20s,
  so every caller for every key queued behind it (a request thread each under
  the gthread worker);
* a client that had stopped for good was handed out forever.

The consumers keep working across a replacement: it adopts the callbacks they
registered, and they check ``alive`` rather than ``connected``.
"""

import asyncio
import json
import socket
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest
from websockets.asyncio.server import serve

from services import websocket_client as wc

ROOT = Path(__file__).resolve().parents[1]


class ProxyStub:
    """A websocket server on an ephemeral port that accepts any API key.

    ``drop_after_auth`` closes each connection with an error code shortly after
    acknowledging it, as a proxy restart does. The pause is longer than
    connect()'s 100 ms poll, so the first connect always sees it authenticated.
    """

    DROP_AFTER_SECONDS = 0.3

    def __init__(self, drop_after_auth=False):
        self.drop_after_auth = drop_after_auth
        self.auths = 0
        self.port = None
        self._ready = threading.Event()
        self._loop = asyncio.new_event_loop()
        self._stop = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        assert self._ready.wait(10), "the stub proxy did not start"

    async def _handler(self, websocket):
        async for message in websocket:
            data = json.loads(message)
            if data.get("action") == "authenticate":
                self.auths += 1
                await websocket.send(json.dumps({"type": "auth", "status": "success"}))
                if self.drop_after_auth:
                    await asyncio.sleep(self.DROP_AFTER_SECONDS)
                    await websocket.close(code=1011, reason="proxy restarting")
                    return

    def _run(self):
        asyncio.set_event_loop(self._loop)

        async def main():
            self._stop = self._loop.create_future()
            async with serve(self._handler, "127.0.0.1", 0) as server:
                self.port = server.sockets[0].getsockname()[1]
                self._ready.set()
                await self._stop

        self._loop.run_until_complete(main())

    def close(self):
        self._loop.call_soon_threadsafe(self._stop.set_result, None)
        self._thread.join(10)


def _closed_port():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _wait_until(predicate, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


@pytest.fixture
def fast_backoff(monkeypatch):
    """A short reconnect backoff, so a run of drops takes seconds."""
    monkeypatch.setattr(wc.WebSocketClient, "RECONNECT_MAX_BACKOFF_SECONDS", 0.05)


@pytest.fixture
def fast(monkeypatch, fast_backoff):
    """Short connect timeouts too, for tests that expect a connect to fail."""
    monkeypatch.setattr(wc.WebSocketClient, "CONNECT_TIMEOUT_SECONDS", 1)


@pytest.fixture
def forget_clients():
    keys = []
    yield keys
    for key in keys:
        wc.close_websocket_client(key)


def test_a_client_keeps_reconnecting_past_the_fifth_drop(fast_backoff):
    stub = ProxyStub(drop_after_auth=True)
    client = wc.WebSocketClient("gt-reconnect-key", host="127.0.0.1", port=stub.port)
    try:
        assert client.connect()
        # The first authentication plus seven reconnects, each dropped again.
        assert _wait_until(lambda: stub.auths >= 8, 30), (
            f"the client stopped reconnecting after {stub.auths - 1} drops"
        )
        assert client.alive
    finally:
        client.disconnect()
        stub.close()
    assert not client.alive


def test_a_failed_connect_leaves_no_thread_behind(fast, forget_clients):
    port = _closed_port()
    baseline = threading.active_count()

    for attempt in range(3):
        key = f"gt-leak-key-{attempt}"
        forget_clients.append(key)
        with pytest.raises(ConnectionError):
            wc.get_websocket_client(key, host="127.0.0.1", port=port)

    assert _wait_until(lambda: threading.active_count() <= baseline, 5), (
        f"{threading.active_count() - baseline} thread(s) left running by failed connects"
    )


def test_a_slow_connect_for_one_key_does_not_hold_up_another(
    fast_backoff, forget_clients, monkeypatch
):
    # Long enough that waiting behind the unreachable key is unmistakable.
    monkeypatch.setattr(wc.WebSocketClient, "CONNECT_TIMEOUT_SECONDS", 3)
    stub = ProxyStub()
    closed = _closed_port()
    forget_clients.extend(["gt-slow-key", "gt-fast-key"])
    slow_started = threading.Event()

    def slow():
        slow_started.set()
        try:
            wc.get_websocket_client("gt-slow-key", host="127.0.0.1", port=closed)
        except ConnectionError:
            pass

    try:
        slow_thread = threading.Thread(target=slow)
        slow_thread.start()
        assert slow_started.wait(5)
        time.sleep(0.1)

        began = time.monotonic()
        client = wc.get_websocket_client("gt-fast-key", host="127.0.0.1", port=stub.port)
        elapsed = time.monotonic() - began

        assert client.alive
        assert elapsed < 2.0, f"a healthy key waited {elapsed:.2f}s behind an unreachable one"
        slow_thread.join(15)
    finally:
        wc.close_websocket_client("gt-fast-key")
        stub.close()


def test_concurrent_callers_for_one_key_share_one_connect(fast, forget_clients, monkeypatch):
    stub = ProxyStub()
    forget_clients.append("gt-shared-key")
    built = []
    real_init = wc.WebSocketClient.__init__

    def counting_init(self, *args, **kwargs):
        built.append(1)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(wc.WebSocketClient, "__init__", counting_init)
    start = threading.Barrier(6)
    got = []

    def caller():
        start.wait()
        got.append(wc.get_websocket_client("gt-shared-key", host="127.0.0.1", port=stub.port))

    try:
        threads = [threading.Thread(target=caller) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(15)
        assert len(got) == 6
        assert len({id(client) for client in got}) == 1
        assert len(built) == 1
    finally:
        wc.close_websocket_client("gt-shared-key")
        stub.close()


def test_a_stopped_client_is_replaced_and_keeps_its_callbacks(fast, forget_clients):
    stub = ProxyStub()
    forget_clients.append("gt-replace-key")

    def on_tick(_data):
        return None

    try:
        first = wc.get_websocket_client("gt-replace-key", host="127.0.0.1", port=stub.port)
        first.register_callback("market_data", on_tick)
        # Stopped for good (its loop has ended), as after a fatal error.
        first.disconnect()
        assert not first.alive

        second = wc.get_websocket_client("gt-replace-key", host="127.0.0.1", port=stub.port)

        assert second is not first
        assert second.alive
        assert second.has_callback("market_data", on_tick)
        assert second.callbacks["market_data"].count(on_tick) == 1
    finally:
        wc.close_websocket_client("gt-replace-key")
        stub.close()


def test_closing_a_key_forgets_its_client(fast):
    stub = ProxyStub()
    try:
        client = wc.get_websocket_client("gt-close-key", host="127.0.0.1", port=stub.port)
        assert wc.close_websocket_client("gt-close-key") is True
        assert not client.alive
        assert "gt-close-key" not in wc._client_instances
        assert wc.close_websocket_client("gt-close-key") is False
    finally:
        stub.close()


def test_the_dispatcher_blocks_instead_of_polling_where_nothing_is_patched():
    client = wc.WebSocketClient("gt-dispatch-key")
    calls = {"get": 0, "get_nowait": 0}
    real_queue = client._dispatch_queue

    class Spy:
        def get(self, *args, **kwargs):
            calls["get"] += 1
            return real_queue.get(*args, **kwargs)

        def get_nowait(self):
            calls["get_nowait"] += 1
            return real_queue.get_nowait()

        def put_nowait(self, item):
            real_queue.put_nowait(item)

    client._dispatch_queue = Spy()
    delivered = threading.Event()
    client.register_callback("market_data", lambda data: delivered.set())
    client.running = True
    dispatcher = threading.Thread(target=client._run_dispatch_loop, daemon=True)
    dispatcher.start()
    try:
        time.sleep(0.6)
        client._dispatch("market_data", {"symbol": "X"})
        assert delivered.wait(1)
    finally:
        client.running = False
        dispatcher.join(2)
    assert calls["get_nowait"] == 0
    # About two wakeups in 0.6s, where 5 ms polling made over a hundred.
    assert calls["get"] <= 6, calls


class _FakeClient:
    """Stands in for a WebSocketClient for the strategy tick feed."""

    def __init__(self, alive=True, callbacks=None):
        self.alive = alive
        self.connected = alive
        self.callbacks = callbacks if callbacks is not None else {}

    def register_callback(self, event_type, callback):
        self.callbacks.setdefault(event_type, []).append(callback)

    def unregister_callback(self, event_type, callback):
        handlers = self.callbacks.get(event_type, [])
        if callback in handlers:
            handlers.remove(callback)


def test_the_strategy_tick_feed_registers_once_on_each_client_it_is_given():
    from services.strategy_module import tick_feed as tf

    fresh = _FakeClient()
    handed = [fresh]
    feed = tf.RiskTickFeed(
        ws_provider=lambda _key: handed[0],
        quote_fetcher=lambda symbols, api_key: (True, {"results": []}, 200),
        api_key_provider=lambda: "k",
    )
    with feed._ws_lock:
        assert feed._ensure_ws() is fresh
        assert feed._ensure_ws() is fresh  # alive: kept, not fetched again
    assert fresh.callbacks["market_data"] == [feed.on_tick]
    assert fresh.callbacks["auth"] == [feed._on_auth]

    # The shared client stopped for good. Its replacement adopted the
    # callbacks, so the feed must not register them a second time.
    fresh.alive = False
    adopted = _FakeClient(callbacks={"market_data": [feed.on_tick], "auth": [feed._on_auth]})
    handed[0] = adopted
    with feed._ws_lock:
        assert feed._ensure_ws() is adopted
    assert adopted.callbacks["market_data"] == [feed.on_tick]
    assert adopted.callbacks["auth"] == [feed._on_auth]

    # A replacement that carries nothing gets both, which a remembered
    # "already registered" flag used to skip.
    adopted.alive = False
    bare = _FakeClient()
    handed[0] = bare
    try:
        with feed._ws_lock:
            assert feed._ensure_ws() is bare
        assert bare.callbacks["market_data"] == [feed.on_tick]
        assert bare.callbacks["auth"] == [feed._on_auth]
    finally:
        feed.stop()


# ---------------------------------------------------------------------------
# Under eventlet
# ---------------------------------------------------------------------------


EVENTLET_BODY = """
import eventlet
eventlet.monkey_patch()

import time

import utils.real_threading as rt
from services import websocket_client as wc

# As app.py does at import: marks the hub's thread and starts its drainer.
assert rt.start_hub_worker()

# Single flight under eventlet: the second caller waits cooperatively while the
# first connects, and the hub keeps running the whole time.
connects = []

def slow_connect(self):
    connects.append(1)
    self.running = True
    self.thread = rt.Thread(target=lambda: rt.sleep(3), daemon=True)
    self.thread.start()
    eventlet.sleep(0.5)
    self.connected = self.authenticated = True
    return True

wc.WebSocketClient.connect = slow_connect
ticks = []

def ticker():
    for _ in range(60):
        ticks.append(time.monotonic())
        eventlet.sleep(0.01)

t = eventlet.spawn(ticker)
a = eventlet.spawn(wc.get_websocket_client, "ev-key")
b = eventlet.spawn(wc.get_websocket_client, "ev-key")
first, second = a.wait(), b.wait()
t.wait()
assert first is second, "two clients for one key"
assert len(connects) == 1, connects
assert len(ticks) == 60
gaps = [later - earlier for earlier, later in zip(ticks, ticks[1:])]
assert max(gaps) < 0.25, f"the hub stalled for {max(gaps):.2f}s during a connect"

# The dispatcher still polls under eventlet (a blocking get from a green thread
# would freeze the worker), and callbacks still run on the hub.
client = wc.WebSocketClient("ev-dispatch")
seen = []
client.register_callback("market_data", lambda data: seen.append(rt.on_hub_thread()))
client.running = True
import threading
dispatcher = threading.Thread(target=client._run_dispatch_loop, daemon=True)
dispatcher.start()

def feed():
    client._dispatch("market_data", {"symbol": "X"})

loop_thread = rt.Thread(target=feed, daemon=True)
loop_thread.start()
deadline = time.monotonic() + 3
while not seen and time.monotonic() < deadline:
    eventlet.sleep(0.01)
client.running = False
assert seen == [True], seen
print("OK")
"""


def test_under_eventlet_connects_are_single_flight_and_the_hub_stays_live():
    pytest.importorskip(
        "eventlet",
        reason="eventlet is installed by the production installer, not by pyproject",
    )
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(EVENTLET_BODY)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(ROOT),
    )
    assert "OK" in result.stdout, result.stderr[-4000:]
