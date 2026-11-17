"""Wisdom (Symphony XTS) market data feed: reconnect, lock discipline and batching.

Issue #1351. Everything here runs against fakes: a fake socketio.Client stands
in for the Socket.IO transport and a fake requests module answers the market
data login and the subscription endpoint, so no test opens a socket or reaches
Wisdom. The adapter's own feed and sender threads do run, with their waits
shortened.

What the fakes model of python-socketio 5: the client's "connect" handler runs
before connect() returns, the "disconnect" handler gets a reason argument, a
dropped transport raises "disconnect" once, and Engine.IO's state reads
"connected" only while the transport is up.
"""

import websocket_proxy  # noqa: F401  isort:skip  (the proxy package imports the adapters)

import json
import threading
import time
import types

import pytest

from broker.wisdom.streaming import wisdom_adapter as adapter_module
from broker.wisdom.streaming import wisdom_websocket as ws_module
from broker.wisdom.streaming.wisdom_adapter import WisdomWebSocketAdapter

AUTH = {"auth_token": "auth", "feed_token": "feed", "api_key": "key", "api_secret": "secret"}


def wait_until(condition, timeout=3.0, message="condition not met"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.005)
    raise AssertionError(message)


def feed_threads():
    return [t for t in threading.enumerate() if t.name in ("wisdom-feed", "wisdom-subscribe")]


class FakeEngineIO:
    def __init__(self, sio):
        self.sio = sio
        self.state = "disconnected"
        self.ping_interval = 25
        self.ping_timeout = 20
        self.aborted = False

    def disconnect(self, abort=False, reason=None):
        self.aborted = True
        self.sio.drop("client disconnect")


class FakeSocketIO:
    """One socketio.Client. `world` collects every instance and an event log."""

    def __init__(self, world, **kwargs):
        self.world = world
        self.kwargs = kwargs
        self.handlers = {}
        self.connected = False
        self.url = None
        self.eio = FakeEngineIO(self)
        with world.lock:
            world.sockets.append(self)

    def on(self, event, handler):
        self.handlers[event] = handler

    def connect(self, url, **kwargs):
        self.url = url
        self.world.log.append(("open", self))
        if self.world.handshake_gate is not None:
            self.world.handshake_started.set()
            self.world.handshake_gate.wait(5)
        if self.world.refuse_connects:
            with self.world.lock:
                self.world.refused += 1
            raise ConnectionError("refused")
        self.eio.state = "connected"
        self.handlers["connect"]()
        self.connected = True

    def disconnect(self):
        self.drop("client disconnect")

    def drop(self, reason="transport error"):
        """The transport closes, as Engine.IO reports it."""
        was_connected = self.connected
        self.connected = False
        if self.eio.state == "connected":
            self.world.log.append(("close", self))
        self.eio.state = "disconnected"
        if was_connected:
            self.handlers["disconnect"](reason)


class FakeResponse:
    def __init__(self, body, status_code=200):
        self.body = body
        self.status_code = status_code

    def json(self):
        return self.body

    @property
    def text(self):
        return json.dumps(self.body)


class FakeRequestException(Exception):
    pass


class World:
    """The fake broker: login, subscribe and unsubscribe, plus the sockets."""

    def __init__(self):
        self.lock = threading.Lock()
        self.sockets = []
        self.log = []
        self.logins = 0
        self.posts = []  # (authorization, body)
        self.puts = []
        self.refuse_connects = False
        self.refused = 0
        self.handshake_gate = None
        self.handshake_started = threading.Event()
        self.reply = None  # callable(body) -> FakeResponse, or None for success
        self.before_post = None  # callable(body), runs before the reply

    def post(self, url, json=None, headers=None, timeout=None):
        if url.endswith("/auth/login"):
            with self.lock:
                self.logins += 1
                token = f"token-{self.logins}"
            return FakeResponse({"type": "success", "result": {"token": token, "userID": "U1"}})
        if self.before_post is not None:
            self.before_post(json)
        with self.lock:
            self.posts.append((headers["Authorization"], json))
        if self.reply is not None:
            return self.reply(json)
        return FakeResponse({"type": "success", "result": {"listQuotes": []}})

    def put(self, url, json=None, headers=None, timeout=None):
        with self.lock:
            self.puts.append((headers["Authorization"], json))
        return FakeResponse({"type": "success"})

    def posted_ids(self, token=None):
        return [
            i["exchangeInstrumentID"]
            for auth, body in self.posts
            if token is None or auth == token
            for i in body["instruments"]
        ]


@pytest.fixture
def world(monkeypatch):
    w = World()
    monkeypatch.setattr(
        ws_module,
        "socketio",
        types.SimpleNamespace(Client=lambda **kwargs: FakeSocketIO(w, **kwargs)),
    )
    monkeypatch.setattr(
        ws_module,
        "requests",
        types.SimpleNamespace(post=w.post, put=w.put, RequestException=FakeRequestException),
    )
    monkeypatch.setattr(
        adapter_module.SymbolMapper,
        "get_token_from_symbol",
        lambda symbol, exchange: {"token": symbol[3:], "brexchange": "NSECM"},
    )
    monkeypatch.setattr(
        adapter_module,
        "get_symbol",
        lambda token, exchange: f"SYM{token}" if exchange == "NSE" else None,
    )
    return w


@pytest.fixture
def adapter(world):
    a = WisdomWebSocketAdapter()
    a.ticks = []
    a.publish_market_data = lambda topic, data: a.ticks.append((topic, data))
    a.SUBSCRIPTION_COLLECT_WINDOW = 0.05
    a.SUBSCRIPTION_DELAY = 0
    a.CONNECTION_CHECK_INTERVAL = 0.05
    a.reconnect_delay = 0.01
    a.max_reconnect_delay = 0.05
    a.initialize("wisdom", "user1", AUTH)
    yield a
    a.disconnect()
    wait_until(lambda: not feed_threads(), message="a feed thread outlived disconnect()")


def connect(adapter, world, count=1):
    adapter.connect()
    wait_until(
        lambda: len(world.sockets) >= count and world.sockets[count - 1].connected,
        message=f"connection {count} did not open",
    )
    return world.sockets[count - 1]


def sender_idle(adapter):
    with adapter.lock:
        return adapter._sender_thread is None and not adapter.pending_subscriptions


# ---------------------------------------------------------------------------
# 1. No subscription request is sent while the adapter lock is held.
# ---------------------------------------------------------------------------


def test_slow_resubscribe_does_not_hold_the_adapter_lock(adapter, world):
    for n in range(1, 4):
        adapter.subscribe(f"SYM{n}", "NSE", 2)

    release = threading.Event()
    lock_free_during_send = []

    def slow_broker(_body):
        lock_free_during_send.append(not adapter.lock.locked())
        release.wait(5)

    world.before_post = slow_broker
    connect(adapter, world)
    wait_until(lambda: lock_free_during_send, message="the resubscribe never reached the broker")

    # The broker is still answering the resubscribe. A new subscribe and an
    # unsubscribe must not queue behind it.
    started = time.monotonic()
    adapter.subscribe("SYM9", "NSE", 2)
    adapter.unsubscribe("SYM2", "NSE", 2)
    elapsed = time.monotonic() - started
    release.set()

    assert elapsed < 1.0, f"subscribe and unsubscribe waited {elapsed:.1f}s on a slow broker"
    wait_until(lambda: sender_idle(adapter) and len(world.posted_ids()) == 4)
    assert all(lock_free_during_send), "a subscription request was sent under the adapter lock"
    assert set(world.posted_ids()) == {"1", "2", "3", "9"}


# ---------------------------------------------------------------------------
# 2. Reconnect: one mechanism, fresh login, old socket closed first,
#    everything resubscribed, and a clean stop.
# ---------------------------------------------------------------------------


def test_socketio_builtin_reconnection_is_off(adapter, world):
    first = connect(adapter, world)
    first.drop()
    connect(adapter, world, count=2)

    assert [s.kwargs.get("reconnection") for s in world.sockets] == [False, False]


def test_dropped_connection_reconnects_with_a_fresh_login_and_resubscribes(adapter, world):
    for n in (1, 2, 3):
        adapter.subscribe(f"SYM{n}", "NSE", 1)
    first = connect(adapter, world)
    wait_until(lambda: sorted(world.posted_ids("token-1")) == ["1", "2", "3"])

    first.drop("transport error")
    second = connect(adapter, world, count=2)
    wait_until(lambda: sorted(world.posted_ids("token-2")) == ["1", "2", "3"])

    assert world.logins == 2
    assert "token=token-2" in second.url
    # The old socket was closed before the new one was opened.
    assert first.eio.aborted
    assert world.log.index(("close", first)) < world.log.index(("open", second))
    assert adapter.connected and adapter.ws_client.sio is second


def test_transport_lost_without_a_close_event_is_reconnected(adapter, world):
    # python-socketio raises no close event for a transport that drops before
    # its connect() returns; the feed thread has to notice on its own.
    first = connect(adapter, world)
    first.connected = False
    first.eio.state = "disconnected"

    connect(adapter, world, count=2)
    assert world.logins == 2


def test_engineio_idle_timeout_floor_is_applied(adapter, world):
    first = connect(adapter, world)

    # The server offered 25s and 20s; the write loop's idle limit is the
    # larger plus 5 seconds.
    assert max(first.eio.ping_interval, first.eio.ping_timeout) + 5 >= 300


def test_repeated_reconnects_release_every_socket_and_thread(adapter, world):
    adapter.SUBSCRIPTION_COLLECT_WINDOW = 0
    adapter.subscribe("SYM1", "NSE", 1)
    adapter.subscribe("SYM2", "NSE", 2)
    connect(adapter, world)
    wait_until(lambda: sender_idle(adapter) and len(world.posts) == 2)
    baseline = threading.active_count()

    cycles = 50
    for cycle in range(cycles):
        world.sockets[-1].drop()
        connect(adapter, world, count=cycle + 2)
        expected = 2 * (cycle + 2)
        wait_until(lambda n=expected: sender_idle(adapter) and len(world.posts) == n)

    old, live = world.sockets[:-1], world.sockets[-1]
    assert len(old) == cycles
    assert all(s.eio.aborted and not s.connected for s in old), "an old socket was left open"
    assert live.connected and adapter.ws_client.sio is live
    assert len(adapter.ws_client.subscriptions) == 2
    assert not adapter.pending_subscriptions
    assert len([t for t in threading.enumerate() if t.name == "wisdom-feed"]) == 1
    assert threading.active_count() <= baseline + 1


def test_failed_connects_back_off_and_then_give_up(adapter, world):
    world.refuse_connects = True
    adapter.max_reconnect_attempts = 3
    adapter.connect()

    wait_until(
        lambda: not [t for t in threading.enumerate() if t.name == "wisdom-feed"],
        message="the feed thread never gave up",
    )
    assert len(world.sockets) == 3
    assert world.logins == 3
    assert not any(s.connected for s in world.sockets)


def test_disconnect_interrupts_the_backoff_wait(adapter, world):
    world.refuse_connects = True
    adapter.reconnect_delay = 30
    adapter.max_reconnect_delay = 60
    adapter.connect()
    wait_until(lambda: world.refused == 1)
    time.sleep(0.2)  # the feed thread is now in its 60 second backoff

    started = time.monotonic()
    adapter.disconnect()
    wait_until(
        lambda: not feed_threads(), timeout=1.0, message="disconnect() did not wake the backoff"
    )
    assert time.monotonic() - started < 1.0
    assert len(world.sockets) == 1


def test_disconnect_closes_the_socket_and_stops_every_thread(adapter, world):
    for n in (1, 2):
        adapter.subscribe(f"SYM{n}", "NSE", 2)
    first = connect(adapter, world)
    wait_until(lambda: sender_idle(adapter))

    adapter.disconnect()
    wait_until(lambda: not feed_threads(), message="a thread outlived disconnect()")

    assert not first.connected and first.eio.aborted
    assert adapter.ws_client is None and not adapter.running
    assert adapter._zmq_cleaned_up
    # A close the broker sends late starts nothing.
    first.handlers["disconnect"]("transport error")
    time.sleep(0.1)
    assert len(world.sockets) == 1 and not feed_threads()


def test_disconnect_during_the_handshake_leaves_no_socket_open(adapter, world):
    world.handshake_gate = threading.Event()
    adapter.connect()
    assert world.handshake_started.wait(3)

    client = adapter.ws_client
    adapter.disconnect()  # finds the socket still opening, nothing to close yet
    world.handshake_gate.set()  # the handshake then completes

    wait_until(lambda: not feed_threads(), message="the feed thread outlived disconnect()")
    assert len(world.sockets) == 1
    assert not world.sockets[0].connected, "a socket opened during disconnect() was left open"
    assert client.sio is None


# ---------------------------------------------------------------------------
# 3. Close callbacks start nothing, and a stale close changes nothing.
# ---------------------------------------------------------------------------


def test_concurrent_close_callbacks_start_one_reconnect(adapter, world):
    first = connect(adapter, world)
    first.connected = False
    first.eio.state = "disconnected"

    barrier = threading.Barrier(8)

    def close_event():
        barrier.wait()
        first.handlers["disconnect"]("transport error")
        adapter._on_close(adapter.ws_client)

    callers = [threading.Thread(target=close_event) for _ in range(8)]
    for t in callers:
        t.start()
    for t in callers:
        t.join(5)

    connect(adapter, world, count=2)
    time.sleep(0.2)  # room for any extra reconnect to show itself
    assert len(world.sockets) == 2
    assert world.logins == 2
    assert len([t for t in threading.enumerate() if t.name == "wisdom-feed"]) == 1


def test_stale_close_does_not_tear_down_the_new_connection(adapter, world):
    adapter.subscribe("SYM1", "NSE", 2)
    first = connect(adapter, world)
    first.drop()
    second = connect(adapter, world, count=2)
    wait_until(lambda: world.posted_ids("token-2") == ["1"])

    # The old socket's close arrives late, after the new one is up.
    first.handlers["disconnect"]("transport error")
    time.sleep(0.2)

    assert adapter.connected
    assert adapter.ws_client.connected
    assert second.connected and not second.eio.aborted
    assert len(world.sockets) == 2


# ---------------------------------------------------------------------------
# 4. Subscribe batching.
# ---------------------------------------------------------------------------


def test_book_is_sent_in_capped_batches_per_mode(adapter, world):
    # Stored while disconnected, so the connection queues all of it at once.
    for n in range(120):
        adapter.subscribe(f"SYM{n}", "NSE", 1)
        if n < 55:
            adapter.subscribe(f"SYM{1000 + n}", "NSE", 3, 5)
    connect(adapter, world)
    wait_until(lambda: len(world.posted_ids()) == 175 and sender_idle(adapter))

    sizes = {1512: [], 1502: []}
    for _, body in world.posts:
        sizes[body["xtsMessageCode"]].append(len(body["instruments"]))
    assert sizes == {1512: [50, 50, 20], 1502: [50, 5]}
    assert len(set(world.posted_ids())) == 175


def test_live_subscribe_burst_is_coalesced(adapter, world):
    connect(adapter, world)
    adapter.SUBSCRIPTION_COLLECT_WINDOW = 0.5
    for n in range(20):
        adapter.subscribe(f"SYM{n}", "NSE", 2)
    senders = [t for t in threading.enumerate() if t.name == "wisdom-subscribe"]
    assert len(senders) == 1, f"{len(senders)} sender threads for one burst"
    wait_until(lambda: len(world.posted_ids()) == 20 and sender_idle(adapter))

    assert len(world.posts) <= 2, f"20 subscribes took {len(world.posts)} requests"


def test_refused_batch_is_retried_one_instrument_at_a_time(adapter, world):
    def reply(body):
        ids = [i["exchangeInstrumentID"] for i in body["instruments"]]
        if "2" in ids:
            return FakeResponse(
                {"type": "error", "code": "e-session-0002", "description": "Already Subscribed"},
                status_code=400,
            )
        return FakeResponse({"type": "success", "result": {"listQuotes": []}})

    world.reply = reply
    for n in (1, 2, 3):
        adapter.subscribe(f"SYM{n}", "NSE", 2)
    connect(adapter, world)
    wait_until(lambda: len(world.posts) == 4 and sender_idle(adapter))

    singles = [body["instruments"] for _, body in world.posts[1:]]
    assert singles == [
        [{"exchangeSegment": 1, "exchangeInstrumentID": "1"}],
        [{"exchangeSegment": 1, "exchangeInstrumentID": "2"}],
        [{"exchangeSegment": 1, "exchangeInstrumentID": "3"}],
    ]


def test_failed_send_is_retried(adapter, world):
    failures = []

    def flaky(_body):
        if not failures:
            failures.append(1)
            raise FakeRequestException("connection reset")

    world.before_post = flaky
    connect(adapter, world)
    adapter.subscribe("SYM1", "NSE", 2)
    wait_until(lambda: world.posted_ids() == ["1"] and sender_idle(adapter))
    assert failures == [1]


def test_unsubscribe_cancels_a_queued_subscribe(adapter, world):
    connect(adapter, world)
    adapter.SUBSCRIPTION_COLLECT_WINDOW = 0.3
    adapter.subscribe("SYM1", "NSE", 2)
    adapter.subscribe("SYM2", "NSE", 2)
    adapter.unsubscribe("SYM1", "NSE", 2)
    wait_until(lambda: sender_idle(adapter))
    time.sleep(0.05)

    assert world.posted_ids() == ["2"]


def test_initial_quotes_of_a_batch_are_published(adapter, world):
    quotes = [
        json.dumps(
            {
                "MessageCode": 1512,
                "ExchangeSegment": 1,
                "ExchangeInstrumentID": n,
                "LastTradedPrice": 100.5 + n,
                "LastTradedTime": 1700000000,
                "LastTradedQunatity": 10,
            }
        )
        for n in (1, 2)
    ]
    world.reply = lambda body: FakeResponse({"type": "success", "result": {"listQuotes": quotes}})
    adapter.subscribe("SYM1", "NSE", 1)
    adapter.subscribe("SYM2", "NSE", 1)
    connect(adapter, world)
    wait_until(lambda: len(adapter.ticks) == 2 and sender_idle(adapter))

    assert len(world.posts) == 1
    by_topic = dict(adapter.ticks)
    assert set(by_topic) == {"NSE_SYM1_LTP", "NSE_SYM2_LTP"}
    tick = by_topic["NSE_SYM1_LTP"]
    assert {k: tick[k] for k in ("ltp", "ltt", "ltq", "symbol", "exchange", "mode")} == {
        "ltp": 101.5,
        "ltt": 1700000000,
        "ltq": 10,
        "symbol": "SYM1",
        "exchange": "NSE",
        "mode": 1,
    }


# ---------------------------------------------------------------------------
# Unsubscribe: drop one symbol, keep the feed.
# ---------------------------------------------------------------------------


def test_unsubscribe_keeps_the_feed_running_for_other_symbols(adapter, world):
    adapter.subscribe("SYM1", "NSE", 2)
    adapter.subscribe("SYM2", "NSE", 2)
    first = connect(adapter, world)
    wait_until(lambda: sender_idle(adapter) and len(world.posted_ids()) == 2)

    result = adapter.unsubscribe("SYM1", "NSE", 2)

    assert result["status"] == "success"
    assert adapter.running and adapter.connected and adapter.ws_client is not None
    assert first.connected
    assert list(adapter.subscriptions) == ["SYM2_NSE_2"]
    assert [body["xtsMessageCode"] for _, body in world.puts] == [1501]


def test_unsubscribe_depth_removes_every_depth_level(adapter, world):
    adapter.subscribe("SYM7", "NSE", 3, 5)
    adapter.subscribe("SYM7", "NSE", 3, 20)
    adapter.subscribe("SYM8", "NSE", 2)
    first = connect(adapter, world)
    wait_until(lambda: sender_idle(adapter) and len(world.posted_ids()) == 2)

    adapter.unsubscribe("SYM7", "NSE", 3)
    assert list(adapter.subscriptions) == ["SYM8_NSE_2"]
    assert [body["xtsMessageCode"] for _, body in world.puts] == [1502]

    # A reconnect replays the book without the dropped symbol.
    first.drop()
    connect(adapter, world, count=2)
    wait_until(lambda: world.posted_ids("token-2") == ["8"] and sender_idle(adapter))
