"""The /python live status stream is bounded under gthread and ends on shutdown (hosts-07).

Each open /python tab holds one stream, and under the gthread worker a stream
holds one web server thread for as long as it lives: nothing capped how many,
none ever ended on its own, and a client that vanished was noticed only at the
next heartbeat. Under gthread only, streams are now admitted up to
PYTHON_STRATEGY_SSE_MAX and end after a lifetime with a reconnect hint. In every
runtime a stream ends once shutdown begins.

The slot a stream holds is released when the response is closed as well as
when its generator finishes, because a client that leaves before the first
byte never starts the generator.
"""

import threading
import time

import pytest
from flask import Flask

import utils.session
from blueprints import python_strategy as ps
from utils import stream_registry


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(utils.session, "is_session_valid", lambda: True)
    monkeypatch.setattr(ps, "PYTHON_STRATEGY_SSE_MAX", 4)
    monkeypatch.setattr(ps, "_SSE_POLL_SECONDS", 0.1)
    monkeypatch.setattr(ps, "_SHUTTING_DOWN", threading.Event())
    stream_registry._reset_for_tests()
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(ps.python_strategy_bp)
    yield app.test_client()
    stream_registry._reset_for_tests()


@pytest.fixture
def worker(monkeypatch):
    def choose(gthread: bool):
        monkeypatch.setattr(ps.runtime, "gthread_active", lambda: gthread)

    return choose


def _open(client):
    return client.get("/python/api/events", buffered=False)


def _open_streams() -> int:
    return stream_registry.snapshot().get(ps._SSE_KIND, {}).get("open", 0)


def test_gthread_admits_up_to_the_cap_and_refuses_the_next(client, worker):
    worker(True)
    streams = [_open(client) for _ in range(4)]
    assert all(s.status_code == 200 for s in streams)

    refused = _open(client)
    assert refused.status_code == 503
    assert "Too many windows" in refused.get_json()["message"]

    streams[0].close()
    again = _open(client)
    assert again.status_code == 200
    for s in streams[1:] + [again]:
        s.close()
    assert _open_streams() == 0


def test_a_client_that_leaves_before_the_first_byte_frees_its_slot(client, worker):
    worker(True)
    stream = _open(client)
    assert _open_streams() == 1
    # Never iterated: the generator never starts, so only the close releases.
    stream.close()
    assert _open_streams() == 0


def test_eventlet_and_the_dev_server_are_not_capped(client, worker):
    worker(False)
    streams = [_open(client) for _ in range(10)]
    assert all(s.status_code == 200 for s in streams)
    for s in streams:
        s.close()


def _drain(stream, sink):
    for chunk in stream.response:
        sink.append(chunk.decode() if isinstance(chunk, bytes) else chunk)


def test_every_stream_ends_when_shutdown_begins(client, worker):
    worker(False)
    streams = [_open(client) for _ in range(4)]
    sinks = [[] for _ in streams]
    readers = [
        threading.Thread(target=_drain, args=(s, sink), daemon=True)
        for s, sink in zip(streams, sinks, strict=True)
    ]
    for r in readers:
        r.start()
    time.sleep(0.3)
    assert all(r.is_alive() for r in readers)

    ps._SHUTTING_DOWN.set()
    deadline = time.monotonic() + 3
    for r in readers:
        r.join(max(0.0, deadline - time.monotonic()))

    assert not any(r.is_alive() for r in readers), "a stream kept its thread after shutdown"
    assert all(sink and "connected" in sink[0] for sink in sinks)
    for s in streams:
        s.close()
    assert _open_streams() == 0


def test_the_platform_wide_drain_also_ends_a_stream(client, worker):
    worker(False)
    stream = _open(client)
    sink = []
    reader = threading.Thread(target=_drain, args=(stream, sink), daemon=True)
    reader.start()
    time.sleep(0.2)
    stream_registry.request_drain()
    reader.join(3)
    assert not reader.is_alive()
    stream.close()


def test_under_gthread_a_stream_ends_after_its_lifetime_with_a_reconnect_hint(
    client, worker, monkeypatch
):
    worker(True)
    monkeypatch.setattr(ps, "_SSE_LIFETIME_SECONDS", 0.5)
    stream = _open(client)
    sink = []
    reader = threading.Thread(target=_drain, args=(stream, sink), daemon=True)
    reader.start()
    reader.join(5)

    assert not reader.is_alive()
    assert sink[-1] == "retry: 3000\n\n"
    stream.close()
    assert _open_streams() == 0


def test_outside_gthread_a_stream_has_no_lifetime(client, worker, monkeypatch):
    worker(False)
    monkeypatch.setattr(ps, "_SSE_LIFETIME_SECONDS", 0.2)
    stream = _open(client)
    sink = []
    reader = threading.Thread(target=_drain, args=(stream, sink), daemon=True)
    reader.start()
    time.sleep(1.0)
    assert reader.is_alive(), "the stream ended on its own outside gthread"
    ps._SHUTTING_DOWN.set()
    reader.join(3)
    assert not any("retry" in chunk for chunk in sink)
    stream.close()


def test_events_still_reach_an_open_stream(client, worker):
    worker(False)
    stream = _open(client)
    sink = []
    reader = threading.Thread(target=_drain, args=(stream, sink), daemon=True)
    reader.start()
    time.sleep(0.2)
    ps.broadcast_status_update("abc", "running", "Started")
    time.sleep(0.4)
    ps._SHUTTING_DOWN.set()
    reader.join(3)
    assert any('"strategy_id": "abc"' in chunk for chunk in sink)
    stream.close()
