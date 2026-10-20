"""Core findings from the gthread review.

core-02. The gthread drain watcher closed the browser sessions with
Engine.IO's ``disconnect()``, which closes each one with ``wait=True`` and so
joins that session's queue. A polling session whose client is not reading, a
sleeping tab or one that has already taken its close packet, never finishes
that queue, so the watcher blocked on the first such session for good and the
sessions after it were never closed by it. It now closes each session without
waiting, as the launcher's own stop drain does.
"""

from __future__ import annotations

import threading

import engineio
from engineio import socket as eio_socket

from utils import shutdown


def _session(server, sid):
    session = eio_socket.Socket(server, sid)
    session.connected = True
    server.sockets[sid] = session
    return session


def test_an_idle_polling_session_does_not_hold_the_watcher(monkeypatch):
    from extensions import socketio

    server = engineio.Server(async_mode="threading")
    idle = _session(server, "idle")
    other = _session(server, "other")
    monkeypatch.setattr(socketio, "server", type("S", (), {"eio": server})(), raising=False)

    result = {}
    done = threading.Event()

    def watcher():
        result["closed"] = shutdown.close_socketio_sessions()
        done.set()

    threading.Thread(target=watcher, daemon=True).start()

    assert done.wait(3), "closing the sessions blocked on an idle polling session"
    assert result["closed"] == 2
    assert idle.closed and other.closed


def test_a_session_that_cannot_be_closed_does_not_stop_the_rest(monkeypatch):
    from extensions import socketio

    closed = []

    class Broken:
        def close(self, wait=True):
            raise RuntimeError("already gone")

    class Fine:
        def close(self, wait=True):
            closed.append(wait)

    class Eio:
        sockets = {"a": Broken(), "b": Fine()}

    monkeypatch.setattr(socketio, "server", type("S", (), {"eio": Eio()})(), raising=False)

    assert shutdown.close_socketio_sessions() == 1
    assert closed == [False]
