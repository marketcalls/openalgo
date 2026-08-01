"""Tests for the serialized Socket.IO emit boundary (gthread PR-3, gate A1).

Covers GT-A1-01, GT-A1-02, GT-A1-03, GT-A1-04.

python-socketio documents that emit() is not thread safe: concurrent emits to
the same client can interleave a multi-packet message. Under eventlet the
producers could not truly interleave; under gthread they can. The boundary
lives in extensions.SerializedSocketIO so every one of the ~123 call sites is
covered without editing any of them.
"""

import threading
import time
from pathlib import Path

import pytest

from extensions import SerializedSocketIO, socketio

REPO = Path(__file__).resolve().parent.parent


class _RecordingSocketIO(SerializedSocketIO):
    """Captures interleaving by holding the 'send' open for a moment."""

    def __init__(self):
        # Deliberately skip SocketIO.__init__ -- we only exercise emit().
        self.calls = []
        self.overlaps = 0
        self._active = 0
        self._probe = threading.Lock()

    def _emit_super(self, event, *args, **kwargs):
        with self._probe:
            self._active += 1
            if self._active > 1:
                self.overlaps += 1
        time.sleep(0.002)  # widen the window an unlocked impl would lose
        with self._probe:
            self._active -= 1
        self.calls.append(event)


class _SerializedRecorder(_RecordingSocketIO):
    def emit(self, event, *args, **kwargs):
        with self._emit_lock:
            return self._emit_super(event, *args, **kwargs)


class _UnserializedRecorder(_RecordingSocketIO):
    """Models the pre-PR-3 behaviour, to prove the test can fail."""

    def emit(self, event, *args, **kwargs):
        return self._emit_super(event, *args, **kwargs)


def _hammer(sio, threads=12, per_thread=8):
    def worker(n):
        for i in range(per_thread):
            sio.emit(f"evt-{n}-{i}", {"seq": i})

    ts = [threading.Thread(target=worker, args=(n,)) for n in range(threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()


def test_serialized_emit_never_overlaps():
    sio = _SerializedRecorder()
    _hammer(sio)
    assert sio.overlaps == 0, f"{sio.overlaps} overlapping emits under the lock"
    assert len(sio.calls) == 12 * 8


def test_unserialized_emit_does_overlap():
    """The control: without the lock, concurrent emits do interleave.

    If this ever stops overlapping the test above proves nothing, so assert it
    explicitly rather than trusting it.
    """
    sio = _UnserializedRecorder()
    _hammer(sio)
    assert sio.overlaps > 0, "expected overlap without serialization"


def test_lock_is_reentrant():
    """A handler that emits during an emit on the same thread must not hang."""
    sio = _SerializedRecorder()
    with SerializedSocketIO._emit_lock:
        sio.emit("nested", {"ok": True})
    assert sio.calls == ["nested"]


def test_app_socketio_uses_the_boundary():
    assert isinstance(socketio, SerializedSocketIO)
    # async_mode only becomes an attribute after init_app(); before that it
    # lives in the stored constructor options.
    assert socketio.server_options.get("async_mode") == "threading"


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"a": 1}, False),
        ({"a": b"bytes"}, True),
        ([1, 2, {"b": bytearray(b"x")}], True),
        ("plain string", False),
        ({"nested": {"deep": [b"z"]}}, True),
    ],
)
def test_binary_detection_for_packet_evidence(payload, expected):
    """GT-A1-04: multiplicity comes from binary attachments, not payload size."""
    assert SerializedSocketIO._has_binary(payload) is expected


def test_emit_stats_counts_binary_separately(monkeypatch):
    """Exercise the real SerializedSocketIO.emit with the transport stubbed."""
    import flask_socketio

    sent = []
    monkeypatch.setattr(
        flask_socketio.SocketIO, "emit", lambda self, event, *a, **k: sent.append(event)
    )

    before = SerializedSocketIO.emit_stats()
    sio = object.__new__(SerializedSocketIO)  # no init: only emit() is exercised
    sio.emit("text", {"a": 1})
    sio.emit("binary", {"a": b"payload"})
    after = SerializedSocketIO.emit_stats()

    assert sent == ["text", "binary"]
    assert after["emits"] == before["emits"] + 2
    assert after["binary_emits"] == before["binary_emits"] + 1


def test_no_one_shot_emit_threads_remain():
    """GT-A1-03: spawning a thread just to call emit() is pure churn."""
    offenders = []
    for path in list((REPO / "services").rglob("*.py")) + list(
        (REPO / "blueprints").rglob("*.py")
    ):
        if "start_background_task" in path.read_text(encoding="utf-8"):
            offenders.append(path.relative_to(REPO).as_posix())
    assert offenders == [], f"start_background_task still used in {offenders}"


def test_subscriber_docstring_is_not_misleading():
    """GT-A1-02: the old comment asserted emit() was thread-safe. It is not."""
    text = (REPO / "subscribers" / "socketio_subscriber.py").read_text(encoding="utf-8")
    head = text[: text.index('"""', 3) + 3]
    assert "socketio.emit() is thread-safe" not in head
    assert "SerializedSocketIO" in head
