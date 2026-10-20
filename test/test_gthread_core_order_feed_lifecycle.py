"""The shared ZMQ publisher is never seen half built, and a stopped order feed stays stopped.

SharedZmqPublisher used to publish itself from ``__new__`` and mark itself
initialised in ``__init__`` before it had a context, a socket or a connection
flag. A second caller in that gap got the half-built object and failed on
``_connected``: the cache invalidation after a re-login (so the proxy kept the
old-token feed) or an order update was dropped. Under eventlet
``zmq.Context()`` never yielded, so nobody arrived in the gap.

The order-update adapters run in the app process. A disconnect (logout,
revoke) that landed while the run loop was fetching its URL and headers found
no socket to close, and the loop then opened one with the superseded token,
next to the adapter the next login starts: two feeds, every order update
twice. A connect() after disconnect() on the same object could also revive
the old loop beside the new one. Each loop now belongs to a generation and
stops once it is superseded.
"""

from __future__ import annotations

import threading
import time

import pytest

import websocket_proxy.connection_manager as connection_manager
import websocket_proxy.order_adapter as order_adapter

# --- core-12: the shared publisher --------------------------------------------


class FakeSocket:
    misuse = []

    def __init__(self):
        self.sent = []
        self.closed = False

    def setsockopt(self, *_args):
        pass

    def connect(self, _endpoint):
        pass

    def send_multipart(self, frames):
        if self.closed:
            FakeSocket.misuse.append(frames)
        self.sent.append(frames)

    def close(self, linger=None):
        self.closed = True


class SlowContext:
    built = 0

    def __init__(self):
        type(self).built += 1
        time.sleep(0.05)  # the gap a second caller used to land in

    def socket(self, _kind):
        return FakeSocket()

    def term(self):
        pass


@pytest.fixture
def fresh_publisher(monkeypatch):
    monkeypatch.setattr(connection_manager.SharedZmqPublisher, "_instance", None)
    monkeypatch.setattr(connection_manager.zmq, "Context", SlowContext)
    SlowContext.built = 0
    yield connection_manager.SharedZmqPublisher
    instance = connection_manager.SharedZmqPublisher._instance
    if instance is not None:
        instance.cleanup()


def test_concurrent_first_callers_get_one_finished_publisher(fresh_publisher):
    barrier = threading.Barrier(8)
    seen = []
    errors = []

    def caller():
        try:
            barrier.wait()
            publisher = fresh_publisher()
            seen.append(publisher)
            _ = publisher._connected  # the read that used to raise AttributeError
            _ = publisher.socket
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=caller) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)

    assert errors == [], errors[:3]
    assert SlowContext.built == 1
    assert len({id(p) for p in seen}) == 1
    assert fresh_publisher.instance() is seen[0]


def test_a_publish_racing_cleanup_never_uses_a_closed_socket(fresh_publisher):
    FakeSocket.misuse = []
    publisher = fresh_publisher.instance()
    publisher.connect()
    socket = publisher.socket
    stop = threading.Event()
    errors = []

    def publisher_loop():
        while not stop.is_set():
            try:
                publisher.publish("topic", {"x": 1})
            except BaseException as exc:  # noqa: BLE001 - reported below
                errors.append(exc)

    thread = threading.Thread(target=publisher_loop)
    thread.start()
    time.sleep(0.05)
    publisher.cleanup()
    time.sleep(0.05)
    stop.set()
    thread.join(10)

    assert socket.closed is True
    assert errors == []
    assert FakeSocket.misuse == []
    assert fresh_publisher._instance is None


def test_callers_still_construct_it_the_old_way(fresh_publisher):
    first = fresh_publisher()
    assert first is fresh_publisher()
    assert first.connected is False
    first.connect()
    assert first.connected is True


# --- core-13: order-update adapters -------------------------------------------


class FakeWebSocketApp:
    instances = []

    def __init__(self, url, **kwargs):
        self.url = url
        self.kwargs = kwargs
        self.ran = threading.Event()
        self.closed = threading.Event()
        FakeWebSocketApp.instances.append(self)

    def run_forever(self, **_kwargs):
        self.ran.set()
        on_open = self.kwargs.get("on_open")
        if on_open is not None:
            on_open(self)
        self.closed.wait(30)

    def close(self):
        self.closed.set()

    def send(self, _payload):
        pass


class BlockingUrlAdapter(order_adapter.BaseOrderUpdateAdapter):
    def __init__(self):
        super().__init__(broker_name="gtcore", user_id="u1")
        self.url_requested = threading.Event()
        self.release_url = threading.Event()

    def get_ws_url(self):
        self.url_requested.set()
        assert self.release_url.wait(30), "the test never released get_ws_url"
        return "wss://broker.example/orders"

    def get_headers(self):
        return {"Authorization": "token"}

    def normalize(self, raw_message):
        return None


@pytest.fixture
def fake_ws(monkeypatch):
    FakeWebSocketApp.instances = []
    monkeypatch.setattr(order_adapter.websocket, "WebSocketApp", FakeWebSocketApp)
    yield FakeWebSocketApp
    for app in FakeWebSocketApp.instances:
        app.close()


def test_a_disconnect_during_the_url_fetch_opens_no_socket(fake_ws):
    adapter = BlockingUrlAdapter()
    adapter.connect()
    assert adapter.url_requested.wait(10)

    # Logout lands while the loop is still fetching its URL and headers.
    adapter.disconnect()
    adapter.release_url.set()
    adapter._thread.join(5)

    ran = [app for app in fake_ws.instances if app.ran.is_set()]
    # Before the fix the loop opened a socket with the superseded token and
    # sat in run_forever until the broker closed it.
    assert ran == []
    assert not adapter._thread.is_alive()
    assert adapter.connected is False


def test_a_quiet_connect_and_disconnect_behave_as_before(fake_ws):
    adapter = BlockingUrlAdapter()
    adapter.release_url.set()
    adapter.connect()
    deadline = time.monotonic() + 10
    while not fake_ws.instances and time.monotonic() < deadline:
        time.sleep(0.01)
    assert fake_ws.instances[0].ran.wait(10)
    assert adapter.connected is True

    adapter.disconnect()
    adapter._thread.join(5)
    assert not adapter._thread.is_alive()
    assert adapter.connected is False
    assert fake_ws.instances[0].closed.is_set()


class QuietPoller(order_adapter.PollingOrderUpdateAdapter):
    loops = 0
    lock = threading.Lock()

    def _poll_loop(self, generation=None):
        with QuietPoller.lock:
            QuietPoller.loops += 1
        try:
            if generation is None:
                super()._poll_loop()
            else:
                super()._poll_loop(generation)
        finally:
            with QuietPoller.lock:
                QuietPoller.loops -= 1


def test_a_poller_restarted_quickly_runs_one_loop(monkeypatch):
    import database.auth_db as auth_db

    monkeypatch.setattr(auth_db, "get_auth_token", lambda _user: None)
    QuietPoller.loops = 0
    poller = QuietPoller("gtcore", "u1", poll_interval=1)
    poller.connect()
    time.sleep(0.1)
    poller.disconnect()
    poller.connect()  # before the old loop noticed the disconnect
    time.sleep(1.5)
    try:
        # Before the fix the old loop saw _running True again and kept going.
        assert QuietPoller.loops == 1
    finally:
        poller.disconnect()
        deadline = time.monotonic() + 5
        while QuietPoller.loops and time.monotonic() < deadline:
            time.sleep(0.05)
