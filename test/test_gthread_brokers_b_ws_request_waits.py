"""Quote and depth requests that wait on a broker WebSocket, under gthread.

Motilal, Pocketful, Nubra and Tradejini answer quote and depth requests by
subscribing on a WebSocket and waiting seconds for the data; mstock opens a
socket per depth request with a 10 second timeout on every step. Each wait
holds the request's thread. Under eventlet that thread is a greenlet and costs
nothing; under the gthread worker it is one of a fixed pool.

Under gthread only:

* at most ``_FEED_WAITERS_MAX`` requests per broker wait on its feed at once;
  the next waits at most the data ceiling for a place and is then refused with
  a plain sentence (Nubra falls back to its REST API instead, as it does when
  its feed is down);
* an mstock quote gives up after a deadline instead of 10 seconds per step.

Under eventlet and the dev server nothing is capped. No network: the gated
methods are refused before they run, and mstock's socket is a fake.
"""

from __future__ import annotations

import importlib
import threading
import time

import pytest

from utils import runtime
from utils.broker_backpressure import BrokerBusyError

GATED = {
    "motilal": ("broker.motilal.api.data", "get_depth", ("SBIN", "NSE")),
    "pocketful": ("broker.pocketful.api.data", "_get_quotes_compact", ("SBIN", "NSE")),
    "tradejini": ("broker.tradejini.api.data", "get_quotes", ("SBIN", "NSE")),
}


@pytest.fixture
def gthread(monkeypatch):
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)


@pytest.fixture
def not_gthread(monkeypatch):
    monkeypatch.setattr(runtime, "gthread_active", lambda: False)


class AllPlacesTaken:
    """Take every place on a module's feed gate for the duration of a block."""

    def __init__(self, module):
        self.module = module

    def __enter__(self):
        for _ in range(self.module._FEED_WAITERS_MAX):
            assert self.module._feed_waiters.acquire(timeout=1)
        return self

    def __exit__(self, *exc):
        for _ in range(self.module._FEED_WAITERS_MAX):
            self.module._feed_waiters.release()


def _module(name, monkeypatch):
    module = importlib.import_module(name)
    monkeypatch.setattr(module, "max_queue_wait", lambda kind="data": 0.2)
    return module


def _assert_plain_sentence(message: str):
    assert message[0].isupper() and message.endswith(".")
    for jargon in ("429", "HTTP", "gthread", "semaphore", "Exception"):
        assert jargon not in message


@pytest.mark.parametrize("broker", sorted(GATED))
def test_a_full_feed_refuses_the_next_request_under_gthread(broker, gthread, monkeypatch):
    name, method, args = GATED[broker]
    module = _module(name, monkeypatch)
    # No __init__: a request that got past the gate would fail on the first
    # attribute it touched, long before any network call.
    data = module.BrokerData.__new__(module.BrokerData)

    with AllPlacesTaken(module):
        started = time.monotonic()
        with pytest.raises(BrokerBusyError) as refused:
            getattr(data, method)(*args)
        assert time.monotonic() - started < 2.0

    _assert_plain_sentence(str(refused.value))


@pytest.mark.parametrize("broker", sorted(GATED))
def test_the_real_methods_are_gated(broker):
    name, method, _ = GATED[broker]
    module = importlib.import_module(name)
    assert hasattr(getattr(module.BrokerData, method), "__wrapped__")


@pytest.mark.parametrize("broker", sorted(GATED))
def test_nothing_is_capped_outside_gthread(broker, not_gthread, monkeypatch):
    name, _, _ = GATED[broker]
    module = _module(name, monkeypatch)
    calls = []
    gated = module._feed_gated()(lambda: calls.append(1) or "ok")

    with AllPlacesTaken(module):
        assert gated() == "ok"
    assert calls == [1]


@pytest.mark.parametrize("broker", sorted(GATED))
def test_a_place_is_returned_even_when_the_request_fails(broker, gthread, monkeypatch):
    name, _, _ = GATED[broker]
    module = _module(name, monkeypatch)

    @module._feed_gated()
    def failing():
        raise RuntimeError("broker went away")

    for _ in range(module._FEED_WAITERS_MAX + 2):
        with pytest.raises(RuntimeError):
            failing()
    with AllPlacesTaken(module):
        pass  # every place is free again


@pytest.mark.parametrize("broker", sorted(GATED))
def test_a_nested_gated_call_does_not_take_a_second_place(broker, gthread, monkeypatch):
    name, _, _ = GATED[broker]
    module = _module(name, monkeypatch)

    @module._feed_gated()
    def inner():
        return "inner"

    @module._feed_gated()
    def outer():
        # Leave exactly one place free: the one outer holds must be enough.
        for _ in range(module._FEED_WAITERS_MAX - 1):
            assert module._feed_waiters.acquire(timeout=1)
        try:
            return inner()
        finally:
            for _ in range(module._FEED_WAITERS_MAX - 1):
                module._feed_waiters.release()

    assert outer() == "inner"


def test_concurrent_requests_never_exceed_the_cap(gthread, monkeypatch):
    module = _module("broker.motilal.api.data", monkeypatch)
    monkeypatch.setattr(module, "max_queue_wait", lambda kind="data": 5.0)
    inside = 0
    peak = 0
    lock = threading.Lock()

    @module._feed_gated()
    def wait_on_feed():
        nonlocal inside, peak
        with lock:
            inside += 1
            peak = max(peak, inside)
        time.sleep(0.05)
        with lock:
            inside -= 1

    threads = [threading.Thread(target=wait_on_feed) for _ in range(30)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert 1 < peak <= module._FEED_WAITERS_MAX


# --- Nubra falls back to REST instead of refusing ----------------------------------


def test_nubra_uses_rest_when_its_feed_is_full(gthread, monkeypatch):
    module = _module("broker.nubra.api.data", monkeypatch)
    data = module.BrokerData("tok")
    monkeypatch.setattr(
        module.BrokerData, "get_websocket", lambda *a, **k: pytest.fail("feed used while full")
    )
    monkeypatch.setattr(module.BrokerData, "_get_quotes_via_rest", lambda self, s, e: {"ltp": 7.0})
    monkeypatch.setattr(module.BrokerData, "_get_depth_via_rest", lambda self, s, e: {"ltp": 8.0})

    with AllPlacesTaken(module):
        assert data.get_quotes("SBIN", "NSE") == {"ltp": 7.0}
        assert data.get_depth("SBIN", "NSE") == {"ltp": 8.0}


# --- mstock: a deadline per quote ------------------------------------------------


class SlowSocket:
    """Answers every read with a text frame after its timeout, never a quote."""

    def __init__(self, timeout):
        self.timeout = timeout
        self.reads = 0
        self.settimeouts: list[float] = []

    def settimeout(self, seconds):
        self.settimeouts.append(seconds)
        self.timeout = seconds

    def send(self, message):
        pass

    def recv(self):
        self.reads += 1
        time.sleep(min(self.timeout, 0.2))
        return "heartbeat"

    def close(self):
        pass


@pytest.fixture
def mstock(monkeypatch):
    import websocket

    from broker.mstock.api import mstockwebsocket

    sockets = []

    def create_connection(url, sslopt=None, timeout=None):
        sockets.append(SlowSocket(timeout))
        return sockets[-1]

    monkeypatch.setattr(websocket, "create_connection", create_connection)
    client = mstockwebsocket.MstockWebSocket.__new__(mstockwebsocket.MstockWebSocket)
    client.ws_url = "wss://example.invalid"
    client.auth_token = "tok"
    return mstockwebsocket, client, sockets


def test_mstock_quote_gives_up_at_its_deadline_under_gthread(mstock, gthread, monkeypatch):
    module, client, sockets = mstock
    monkeypatch.setattr(module, "_GTHREAD_QUOTE_DEADLINE", 0.3)
    monkeypatch.setattr(module, "_GTHREAD_STEP_TIMEOUT", 0.2)

    started = time.monotonic()
    assert client.fetch_quote("2885", 1) is None
    assert time.monotonic() - started < 1.5
    assert sockets[0].settimeouts and max(sockets[0].settimeouts) <= 0.2
    assert sockets[0].reads < 4


def test_mstock_quote_keeps_its_timeouts_outside_gthread(mstock, not_gthread):
    module, client, sockets = mstock

    assert client.fetch_quote("2885", 1) is None

    assert sockets[0].settimeouts == [], "no deadline outside gthread"
    assert sockets[0].reads == 4, "the login read and all three quote reads, as before"
