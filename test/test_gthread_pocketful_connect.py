"""Pocketful: connecting the shared feed socket never holds the lock while waiting.

pocketful/api/data.py drives one module-level socket from every quote and depth
request, and ``PocketfulSocket.run_socket`` connects it. It used to do all of it
under ``ws_connect_lock``: close a stale socket, sleep a second, open the new
one and wait up to five seconds for the broker. Every other request that needed
the feed queued on the lock for that whole time, each holding its own thread,
which under gthread is one of a fixed pool.

The connection now has a state of its own. The lock is held to read and claim
it; the caller that claims it connects with the lock released, and a caller
arriving meanwhile waits for that same connection rather than opening a
second one. A caller whose awaited connection failed tries once more, as it did
when it queued on the lock and then found nothing connected.
"""

from __future__ import annotations

import threading
import time

import pytest

from broker.pocketful.api import pocketfulwebsocket as feed


class FakeApp:
    """A websocket.WebSocketApp stand-in: answers after a delay, or never."""

    def __init__(self, answers_after: float | None):
        self.answers_after = answers_after
        self.closed = False
        self.keep_running = True
        self.sock = None
        self.on_open = None

    def run_forever(self):
        if self.answers_after is None:
            return
        time.sleep(self.answers_after)
        if not self.closed:
            feed.on_open(self)

    def close(self):
        self.closed = True
        self.keep_running = False


@pytest.fixture
def clean_feed(monkeypatch):
    monkeypatch.setattr(feed, "websock", None)
    monkeypatch.setattr(feed, "ws_connected", False)
    monkeypatch.setattr(feed, "_connect_attempt", None)
    monkeypatch.setattr(feed, "heartbeat_thread", lambda client_socket: None)
    monkeypatch.setattr(feed, "_STALE_CLOSE_PAUSE", 0.05)
    monkeypatch.setattr(feed, "_CONNECT_POLL_SECONDS", 0.05)
    monkeypatch.setattr(feed, "_CONNECT_POLLS", 20)
    yield
    current = feed.websock
    if current is not None:
        current.keep_running = False


def _client(apps: list[FakeApp], opened: list[FakeApp]):
    """A PocketfulSocket whose connections come from ``apps``, in order."""
    client = feed.PocketfulSocket("C1", "tok")

    def connect(url):
        app = apps.pop(0)
        opened.append(app)
        return app

    client._connect = connect
    return client


def test_the_lock_is_free_while_a_connection_is_being_made(clean_feed):
    """THE DEFECT. Another request must be able to take the lock mid-connect.

    On the old code the connecting caller held ``ws_connect_lock`` for the
    whole wait, so this acquire timed out.
    """
    opened: list[FakeApp] = []
    client = _client([FakeApp(answers_after=0.6)], opened)
    result = {}
    connecting = threading.Thread(target=lambda: result.update(ok=client.run_socket()))
    connecting.start()

    deadline = time.monotonic() + 2
    while not opened and time.monotonic() < deadline:
        time.sleep(0.01)
    assert opened, "the connection never started"

    got = feed.ws_connect_lock.acquire(timeout=0.2)
    assert got, "ws_connect_lock was held while waiting for the broker"
    feed.ws_connect_lock.release()

    connecting.join(5)
    assert result["ok"] is True


def test_a_second_request_waits_for_the_connection_under_way(clean_feed):
    """Only one socket is opened, and both callers see it connected."""
    opened: list[FakeApp] = []
    client = _client([FakeApp(answers_after=0.4), FakeApp(answers_after=0.0)], opened)
    results: list[bool] = []
    barrier = threading.Barrier(2)

    def call():
        barrier.wait()
        results.append(client.run_socket())

    threads = [threading.Thread(target=call) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)

    assert results == [True, True]
    assert len(opened) == 1, "a second socket was opened beside the one connecting"
    assert feed._connect_attempt is None


def test_a_waiting_request_tries_again_when_the_connection_fails(clean_feed, monkeypatch):
    """As before: a caller that found no connection after the first attempt tries itself."""
    monkeypatch.setattr(feed, "_CONNECT_POLLS", 6)
    opened: list[FakeApp] = []
    client = _client([FakeApp(answers_after=None), FakeApp(answers_after=0.0)], opened)
    first = {}
    owner = threading.Thread(target=lambda: first.update(ok=client.run_socket()))
    owner.start()
    deadline = time.monotonic() + 2
    while not opened and time.monotonic() < deadline:
        time.sleep(0.01)

    second = client.run_socket()
    owner.join(5)

    assert first["ok"] is False
    assert second is True
    assert len(opened) == 2


def test_a_stale_socket_is_closed_and_replaced(clean_feed, monkeypatch):
    stale = FakeApp(answers_after=None)
    monkeypatch.setattr(feed, "websock", stale)
    monkeypatch.setattr(feed, "ws_connected", False)
    opened: list[FakeApp] = []
    client = _client([FakeApp(answers_after=0.0)], opened)

    assert client.run_socket() is True
    assert stale.closed is True
    assert feed.websock is opened[0]


def test_a_live_connection_is_reused(clean_feed, monkeypatch):
    live = FakeApp(answers_after=None)
    monkeypatch.setattr(feed, "websock", live)
    monkeypatch.setattr(feed, "ws_connected", True)
    opened: list[FakeApp] = []
    client = _client([], opened)

    assert client.run_socket() is True
    assert opened == []
    assert live.closed is False


def test_a_connection_that_raises_releases_its_waiters(clean_feed):
    client = feed.PocketfulSocket("C1", "tok")

    def broken(url):
        raise OSError("no route")

    client._connect = broken
    assert client.run_socket() is False
    assert feed._connect_attempt is None
    assert feed.ws_connect_lock.acquire(timeout=0.1)
    feed.ws_connect_lock.release()
