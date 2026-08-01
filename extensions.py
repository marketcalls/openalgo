import threading

from flask_socketio import SocketIO


class SerializedSocketIO(SocketIO):
    """SocketIO with server-originated emits serialized by a process-wide lock.

    python-socketio states in ``socketio/server.py`` that ``emit()`` is not
    thread safe: "If multiple threads are emitting at the same time to the same
    client, then messages composed of multiple packets may end up being sent in
    an incorrect sequence. Use standard concurrency solutions (such as a Lock
    object) to prevent this situation."

    OpenAlgo emits from ~123 call sites across ~46 files, driven by the EventBus
    pool, APScheduler jobs, order-update threads, bot threads and request
    handlers. Under eventlet those producers were cooperatively scheduled and
    could not truly interleave. Under gthread they can.

    Serializing here rather than at each call site means every existing emit is
    covered without touching any of them, and an emit added later is covered by
    default. The lock is reentrant, so a handler that emits while an emit is in
    progress on the same thread does not deadlock.
    """

    _emit_lock = threading.RLock()

    # Instrumentation for the open question in the plan (GT-A1-04): the library
    # warning is specific to *multi-packet* messages, and multiplicity comes
    # from binary attachments rather than payload size. Counting binary emits
    # tells us whether the lock can later be narrowed, instead of guessing.
    _emit_count = 0
    _binary_emit_count = 0

    @classmethod
    def _has_binary(cls, data) -> bool:
        """True when a payload carries bytes, which is what splits packets."""
        if isinstance(data, (bytes, bytearray, memoryview)):
            return True
        if isinstance(data, dict):
            return any(cls._has_binary(v) for v in data.values())
        if isinstance(data, (list, tuple)):
            return any(cls._has_binary(v) for v in data)
        return False

    @classmethod
    def emit_stats(cls) -> dict:
        """Emit counters, for the packet-multiplicity evidence in GT-A1-04."""
        with cls._emit_lock:
            return {"emits": cls._emit_count, "binary_emits": cls._binary_emit_count}

    def emit(self, event, *args, **kwargs):
        with self._emit_lock:
            type(self)._emit_count += 1
            if args and self._has_binary(args[0]):
                type(self)._binary_emit_count += 1
            return super().emit(event, *args, **kwargs)


# Disable eventlet to prevent greenlet threading errors
# This fixes concurrent order placement issues in Docker
# Added error handling for disconnected sessions
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
