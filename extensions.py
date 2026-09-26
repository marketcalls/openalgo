import threading

from flask_socketio import SocketIO

from utils import real_threading
from utils.runtime import is_monkey_patched


class SerializedSocketIO(SocketIO):
    """SocketIO whose server-originated emits are serialised by one lock.

    python-socketio states in ``socketio/server.py`` that ``emit()`` is not
    thread safe: "If multiple threads are emitting at the same time to the same
    client, then messages composed of multiple packets may end up being sent in
    an incorrect sequence. Use standard concurrency solutions (such as a Lock
    object) to prevent this situation."

    OpenAlgo emits from well over a hundred call sites, driven by the event bus
    pool, APScheduler jobs, order-update threads, bot threads and request
    handlers. Under the gthread worker and the dev server those run truly in
    parallel, so every emit takes a plain ``threading.RLock`` here: covering
    every existing call site without touching one, and any added later by
    default. Reentrant, so a handler that emits while an emit is in progress on
    the same thread does not deadlock. The critical section is packet encoding
    and a queue put, which never block.

    **Under eventlet no lock is taken, as before.** Every green emitter is
    cooperatively scheduled and an emit never yields, so green emits cannot
    interleave. A lock there would be a green one, and the one emitter that is
    a real OS thread (the Telegram bot) would then be able to wedge itself on
    it for good. Real threads under eventlet emit through
    :func:`emit_from_any_thread` instead.

    Only multi-packet messages can interleave, and those come from binary
    attachments, not payload size, so binary emits are counted separately:
    if there are none, the lock could later be narrowed.
    """

    _emit_lock = threading.RLock()
    _stats_lock = real_threading.Lock()
    _emit_count = 0
    _binary_emit_count = 0

    @classmethod
    def _has_binary(cls, data, depth: int = 0) -> bool:
        """True when a payload carries bytes, which is what splits packets."""
        if isinstance(data, (bytes, bytearray, memoryview)):
            return True
        if depth >= 8:
            return False
        if isinstance(data, dict):
            return any(cls._has_binary(value, depth + 1) for value in data.values())
        if isinstance(data, (list, tuple)):
            return any(cls._has_binary(value, depth + 1) for value in data)
        return False

    @classmethod
    def emit_stats(cls) -> dict:
        """How many emits, and how many with binary attachments, since start."""
        with cls._stats_lock:
            return {"emits": cls._emit_count, "binary_emits": cls._binary_emit_count}

    @classmethod
    def _count(cls, binary: bool) -> None:
        with cls._stats_lock:
            cls._emit_count += 1
            if binary:
                cls._binary_emit_count += 1

    def emit(self, event, *args, **kwargs):
        self._count(bool(args) and self._has_binary(args[0]))
        if is_monkey_patched("thread"):
            return super().emit(event, *args, **kwargs)
        with self._emit_lock:
            return super().emit(event, *args, **kwargs)


# async_mode stays "threading" under every worker: Flask-SocketIO's eventlet
# mode would run its own server loop, which the gunicorn worker already is.
socketio = SerializedSocketIO(
    cors_allowed_origins="*",
    async_mode="threading",
    # engine.io defaults. The previous 10s/5s was too tight for the single
    # gunicorn+eventlet worker: when that one worker is busy (placing orders,
    # webhook signals, DB queries), the heartbeat green thread is starved and
    # can't answer within 10s, so engine.io drops the connection and the
    # browser enters a disconnect/reconnect loop. 60s/25s gives ~6x more grace
    # before a busy-but-alive connection is declared dead (#1419).
    ping_timeout=60,  # Time in seconds before considering the connection lost
    ping_interval=25,  # Interval in seconds between pings
    logger=False,  # Disable built-in logging to avoid noise from disconnection errors
    engineio_logger=False,  # Disable engine.io logging
)


def emit_from_any_thread(event, data, **kwargs) -> None:
    """Emit a Socket.IO event from any thread in any runtime.

    Under eventlet, a real OS thread (the Telegram bot, the agent) must not
    emit directly: the Socket.IO server's queues are green, and a real thread
    that touches them can be left waiting forever or wedge the hub. From such a
    thread the emit is handed to the hub with
    ``utils.real_threading.submit_to_hub`` and this returns at once. Everywhere
    else (the hub itself, the gthread worker, the dev server) it emits directly.

    Args:
        event: The Socket.IO event name.
        data: The payload.
        **kwargs: Passed to ``socketio.emit`` (``to``, ``namespace`` and so on).
    """
    if is_monkey_patched("thread") and not real_threading.on_hub_thread():
        real_threading.submit_to_hub(socketio.emit, event, data, **kwargs)
        return
    socketio.emit(event, data, **kwargs)
