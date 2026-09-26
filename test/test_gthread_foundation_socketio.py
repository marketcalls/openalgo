"""SerializedSocketIO serialises emits, and emit_from_any_thread routes them.

python-socketio documents that concurrent emits to one client can interleave
the packets of a multi-packet (binary) message. Under the gthread worker and
the dev server emitters really are parallel, so every emit passes through one
lock; this proves the lock is held for each call and that no two calls ever
overlap, with the parent emit replaced by a recorder so no server is needed.

The eventlet side (no lock, and a real thread's emit handed to the hub) is
proved under a real hub in test_eventlet_cross_thread_locks.py.
"""

from __future__ import annotations

import threading

import pytest
from flask_socketio import SocketIO

import extensions
from extensions import SerializedSocketIO, emit_from_any_thread, socketio

THREADS = 16
EMITS = 500


def test_the_app_socketio_is_a_drop_in_subclass_with_the_same_settings():
    assert isinstance(socketio, SerializedSocketIO)
    assert isinstance(socketio, SocketIO)
    assert socketio.server_options["async_mode"] == "threading"
    assert socketio.server_options["ping_timeout"] == 60
    assert socketio.server_options["ping_interval"] == 25
    assert socketio.server_options["cors_allowed_origins"] == "*"


@pytest.fixture
def recorder(monkeypatch):
    state = {"inside": 0, "max_inside": 0, "calls": 0, "unlocked": 0}
    guard = threading.Lock()

    def fake_parent_emit(self, event, *args, **kwargs):
        with guard:
            state["inside"] += 1
            state["max_inside"] = max(state["max_inside"], state["inside"])
            state["calls"] += 1
            if not SerializedSocketIO._emit_lock._is_owned():
                state["unlocked"] += 1
        # A few bytecodes of "packet encoding" so an overlap has room to happen.
        sum(range(50))
        with guard:
            state["inside"] -= 1
        return None

    monkeypatch.setattr(SocketIO, "emit", fake_parent_emit)
    monkeypatch.setattr(SerializedSocketIO, "_emit_count", 0)
    monkeypatch.setattr(SerializedSocketIO, "_binary_emit_count", 0)
    return state


def test_concurrent_emits_never_overlap_and_are_all_counted(recorder):
    barrier = threading.Barrier(THREADS)

    def emitter(index):
        barrier.wait()
        for n in range(EMITS):
            socketio.emit("order_update", {"thread": index, "n": n})

    threads = [threading.Thread(target=emitter, args=(i,)) for i in range(THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)

    assert recorder["calls"] == THREADS * EMITS
    assert recorder["max_inside"] == 1, "two emits ran at the same time"
    assert recorder["unlocked"] == 0, "an emit ran without the lock"
    assert SerializedSocketIO.emit_stats() == {"emits": THREADS * EMITS, "binary_emits": 0}


def test_binary_payloads_are_counted_separately(recorder):
    socketio.emit("chart", {"png": b"\x89PNG"})
    socketio.emit("chart", [{"nested": [bytearray(b"x")]}])
    socketio.emit("plain", {"ok": True})
    assert SerializedSocketIO.emit_stats() == {"emits": 3, "binary_emits": 2}


def test_an_emit_from_inside_an_emit_does_not_deadlock(recorder, monkeypatch):
    """Reentrant: a handler that emits while an emit runs on the same thread."""
    outer = SocketIO.emit

    def nested(self, event, *args, **kwargs):
        if event == "outer":
            socketio.emit("inner", {})
        return outer(self, event, *args, **kwargs)

    monkeypatch.setattr(SocketIO, "emit", nested)
    socketio.emit("outer", {})
    assert recorder["calls"] == 2


def test_emit_from_any_thread_emits_directly_when_nothing_is_patched(monkeypatch):
    calls = []
    monkeypatch.setattr(
        extensions.socketio, "emit", lambda event, data, **kw: calls.append((event, data, kw))
    )
    thread = threading.Thread(
        target=emit_from_any_thread, args=("bot_status", {"running": True}), kwargs={"to": "room"}
    )
    thread.start()
    thread.join(5)
    assert calls == [("bot_status", {"running": True}, {"to": "room"})]
