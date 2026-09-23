"""Pocketful's in-process feed: one heartbeat per socket, and shared instruments.

pocketful/api/data.py drives one module-level socket in pocketfulwebsocket.py
from every quote and depth request. Two defects lived there:

* on_open started a heartbeat thread per connection that looped forever, so
  every reconnect left the previous one running against a dead socket: a
  leaked green thread under eventlet, a leaked OS thread under gthread.
* every unsubscribe rebound the shared stores to {} and unsubscribed at the
  broker, so a request finishing early stopped the feed for another request
  still waiting on the same instrument.

A request alone on the feed sees exactly what it saw before: its unsubscribe
reaches the broker and the stores are emptied.
"""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest

from broker.pocketful.api import pocketfulwebsocket as feed


class FakeSocket:
    def __init__(self):
        self.sock = SimpleNamespace(connected=True)
        self.sent: list[dict] = []
        self.keep_running = True

    def send(self, message):
        self.sent.append(json.loads(message))


@pytest.fixture
def socket(monkeypatch):
    fake = FakeSocket()
    monkeypatch.setattr(feed, "websock", fake)
    monkeypatch.setattr(feed, "ws_connected", True)
    monkeypatch.setattr(feed, "_subscribers", {})
    monkeypatch.setattr(feed, "dtlmktdata_dict", {})
    monkeypatch.setattr(feed, "detailed_marketdata_response", {})
    monkeypatch.setattr(feed, "snpqtdata_dict", {})
    monkeypatch.setattr(feed, "snapquote_marketdata_response", {})
    return fake


def _payload(token, exchange=1):
    return {"exchangeCode": exchange, "instrumentToken": token}


def _tick(token, exchange=1):
    return {"instrument_token": token, "exchange_code": exchange, "last_traded_price": 100}


def _unsubscribes(fake):
    return [message for message in fake.sent if message["a"] == "unsubscribe"]


# --- heartbeat ----------------------------------------------------------------


def _heartbeats():
    return [t for t in threading.enumerate() if t.name == "pocketful-hb" and t.is_alive()]


def test_a_reconnect_leaves_exactly_one_heartbeat(monkeypatch):
    real_sleep = time.sleep
    monkeypatch.setattr(feed.time, "sleep", lambda seconds: real_sleep(0.005))
    monkeypatch.setattr(feed, "ws_connected", True)
    first, second = FakeSocket(), FakeSocket()
    try:
        monkeypatch.setattr(feed, "websock", first)
        feed.on_open(first)
        monkeypatch.setattr(feed, "websock", second)  # run_socket replaced it
        feed.on_open(second)
        feed.on_open(second)  # a second on_open for one socket starts nothing

        deadline = time.monotonic() + 2
        while len(_heartbeats()) > 1 and time.monotonic() < deadline:
            real_sleep(0.01)
        alive = _heartbeats()
        assert len(alive) == 1, f"{len(alive)} heartbeat threads alive"
        assert second.sent, "the current socket still gets its heartbeat"
    finally:
        monkeypatch.setattr(feed, "websock", None)
    deadline = time.monotonic() + 2
    while _heartbeats() and time.monotonic() < deadline:
        real_sleep(0.01)
    assert _heartbeats() == [], "a heartbeat outlived its socket"


def test_a_heartbeat_stops_when_its_socket_stops_running(monkeypatch):
    real_sleep = time.sleep
    monkeypatch.setattr(feed.time, "sleep", lambda seconds: real_sleep(0.005))
    monkeypatch.setattr(feed, "ws_connected", True)
    only = FakeSocket()
    monkeypatch.setattr(feed, "websock", only)
    feed.on_open(only)
    assert len(_heartbeats()) == 1
    only.keep_running = False  # run_forever returned
    deadline = time.monotonic() + 2
    while _heartbeats() and time.monotonic() < deadline:
        real_sleep(0.01)
    assert _heartbeats() == []


# --- shared instruments ---------------------------------------------------------


def test_a_request_alone_unsubscribes_and_clears_as_before(socket):
    client = feed.PocketfulSocket("C1", "tok")
    client.subscribe_detailed_marketdata(_payload(11))
    feed.dtlmktdata_dict["11_1"] = _tick(11)
    feed.detailed_marketdata_response = _tick(11)

    client.unsubscribe_detailed_marketdata(_payload(11))

    assert _unsubscribes(socket) == [{"a": "unsubscribe", "v": [[1, 11]], "m": "marketdata"}]
    assert feed.dtlmktdata_dict == {} and feed.detailed_marketdata_response == {}


def test_a_shared_instrument_stays_subscribed_until_its_last_request_leaves(socket):
    first, second = feed.PocketfulSocket("C1", "tok"), feed.PocketfulSocket("C1", "tok")
    first.subscribe_detailed_marketdata(_payload(11))
    second.subscribe_detailed_marketdata(_payload(11))
    feed.detailed_marketdata_response = _tick(11)

    first.unsubscribe_detailed_marketdata(_payload(11))
    assert _unsubscribes(socket) == [], "the second request is still waiting on it"
    assert feed.detailed_marketdata_response == _tick(11)

    second.unsubscribe_detailed_marketdata(_payload(11))
    assert len(_unsubscribes(socket)) == 1
    assert feed.detailed_marketdata_response == {}


def test_releasing_one_instrument_keeps_another_requests_data(socket):
    first, second = feed.PocketfulSocket("C1", "tok"), feed.PocketfulSocket("C1", "tok")
    first.subscribe_snapquote_data(_payload(11))
    second.subscribe_snapquote_data(_payload(22))
    feed.snpqtdata_dict.update({"11_1": _tick(11), "22_1": _tick(22)})
    feed.snapquote_marketdata_response = _tick(22)

    first.unsubscribe_snapquote_data(_payload(11))

    assert _unsubscribes(socket) == [{"a": "unsubscribe", "v": [[1, 11]], "m": "full_snapquote"}]
    assert "22_1" in feed.snpqtdata_dict and "11_1" not in feed.snpqtdata_dict
    assert feed.snapquote_marketdata_response == _tick(22), "another request's tick survives"


def test_a_batch_release_unsubscribes_only_what_nobody_else_holds(socket):
    first, second = feed.PocketfulSocket("C1", "tok"), feed.PocketfulSocket("C1", "tok")
    first.subscribe_multiple_detailed_marketdata([_payload(11), _payload(22)])
    second.subscribe_detailed_marketdata(_payload(22))

    first.unsubscribe_multiple_detailed_marketdata([_payload(11), _payload(22)])

    assert _unsubscribes(socket) == [{"a": "unsubscribe", "v": [[1, 11]], "m": "marketdata"}]
    second.unsubscribe_detailed_marketdata(_payload(22))
    assert _unsubscribes(socket)[-1]["v"] == [[1, 22]]
    assert feed._subscribers == {}


def test_concurrent_requests_on_one_instrument_release_it_once(socket):
    count = 8
    barrier = threading.Barrier(count)
    errors: list[BaseException] = []

    def request():
        try:
            client = feed.PocketfulSocket("C1", "tok")
            barrier.wait(5)
            client.subscribe_detailed_marketdata(_payload(11))
            client.unsubscribe_detailed_marketdata(_payload(11))
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=request) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    assert errors == []
    assert feed._subscribers == {}
    assert 1 <= len(_unsubscribes(socket)) <= count
