"""Accounting, admission and a stop signal for long-lived responses.

Under the gthread worker every open SSE stream and every Socket.IO transport
holds one worker thread for as long as it lives, so they are the largest term
in the thread budget and the one that decides whether a new request gets a
thread at all. Under eventlet each is a greenlet and costs almost nothing,
which is why nothing here refuses anything by itself: callers pass a ``limit``
only when ``utils.runtime.gthread_active()`` is true (see :func:`enforced_limit`),
so the eventlet worker and the dev server behave exactly as before.

Three things live here:

* **Counting.** :func:`admit` counts one stream and returns a
  :class:`StreamTicket`, or None when ``limit`` streams of that kind are
  already open. :func:`track_stream` is the context-manager form for a stream
  that cannot be refused.
* **Releasing.** A ticket must be released exactly once however the stream
  ends, so :meth:`StreamTicket.release` is idempotent and a view registers it
  twice: ``response.call_on_close(ticket.release)`` and in the generator's
  ``finally``. Both are needed because a generator that is never iterated (the
  client left before the first byte) never runs its ``finally``.
* **Stopping.** At shutdown every stream should end inside the graceful
  window. Generators check :func:`should_stop` at least every few seconds and
  return when it is true, or sleep through :func:`wait_stop`.

Kinds name a class of stream (``"python_strategy_sse"``, ``"mcp_sse"``), never
a connection. At most ``MAX_KINDS`` are tracked; any more fold into one bucket
so a caller passing a per-client id cannot grow this without bound.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from utils import real_threading, runtime
from utils.logging import get_logger

logger = get_logger(__name__)

MAX_KINDS = 32
_OVERFLOW = "_other"

#: A warning is logged once when free threads fall below this.
HEADROOM_WARNING = 8

#: Set when streams should end: at shutdown, by utils.shutdown. Real, because a
#: real OS thread may be the one to set it. Read it through should_stop(),
#: which also sees a drain requested from a signal handler.
STOP = real_threading.Event()

#: Set by request_drain(), which a signal handler calls. A plain assignment:
#: a signal handler must not take a lock, and Event.set() takes one.
_drain_requested = False

# A real lock, so a ticket can be released from any thread in any runtime.
# Nothing is done under it but dict arithmetic, so a greenlet never waits on it
# for longer than that.
_lock = real_threading.Lock()
_open: dict[str, int] = {}
_peak: dict[str, int] = {}
_headroom_warned = False
_overflow_warned = False


class StreamTicket:
    """One admitted stream. Release it exactly once; extra calls are ignored."""

    __slots__ = ("kind", "_released")

    def __init__(self, kind: str):
        self.kind = kind
        self._released = False

    @property
    def released(self) -> bool:
        return self._released

    def release(self) -> None:
        """Count the stream as closed. Safe to call any number of times."""
        with _lock:
            if self._released:
                return
            self._released = True
            _open[self.kind] = max(0, _open.get(self.kind, 1) - 1)

    def __repr__(self) -> str:
        return f"StreamTicket({self.kind!r}, released={self._released})"


def _bucket(kind: str) -> str:
    """The key to count ``kind`` under. Call with _lock held."""
    if kind in _open or len(_open) < MAX_KINDS:
        return kind
    return _OVERFLOW


def _warn_overflow(kind: str) -> None:
    global _overflow_warned
    if _overflow_warned:
        return
    _overflow_warned = True
    logger.warning(
        f"More than {MAX_KINDS} kinds of stream are being counted; counting "
        f"{kind!r} with the rest. A kind should name a class of stream, not a "
        "connection."
    )


def admit(kind: str, limit: int | None = None) -> StreamTicket | None:
    """Count one long-lived response of ``kind``, unless ``limit`` are open.

    Args:
        kind: The class of stream.
        limit: The most of this kind allowed open at once, or None for no
            limit. Pass :func:`enforced_limit` of your cap, so the cap applies
            only under the gthread worker.

    Returns:
        A ticket to release when the stream ends, or None when refused.
    """
    with _lock:
        bucket = _bucket(kind)
        current = _open.get(bucket, 0)
        if limit is not None and current >= limit:
            ticket = None
        else:
            current += 1
            _open[bucket] = current
            if current > _peak.get(bucket, 0):
                _peak[bucket] = current
            ticket = StreamTicket(bucket)
    if bucket != kind:
        _warn_overflow(kind)
    return ticket


@contextmanager
def track_stream(kind: str) -> Iterator[StreamTicket]:
    """Count one stream that cannot be refused, for the body of a ``with``.

    Wrap the generator body, not the route: the thread is held for as long as
    the generator runs. The count is released in a ``finally`` because a
    disconnecting client raises out of the generator, which is the common exit.
    """
    ticket = admit(kind, None)
    try:
        yield ticket  # type: ignore[misc]
    finally:
        ticket.release()  # type: ignore[union-attr]


def enforced_limit(limit: int | None) -> int | None:
    """Return ``limit`` under the gthread worker and None everywhere else."""
    return limit if runtime.gthread_active() else None


def request_drain() -> None:
    """Ask every stream to end. Signal-safe: one assignment, no lock, no I/O."""
    global _drain_requested
    _drain_requested = True


def should_stop() -> bool:
    """Return True when streams should end (a drain or shutdown is under way)."""
    return _drain_requested or STOP.is_set()


def wait_stop(timeout: float, poll: float = 0.25) -> bool:
    """Sleep up to ``timeout`` seconds, returning early if streams should end.

    Uses ``time.sleep`` in short steps, which yields under eventlet and blocks
    only the calling thread elsewhere, so it is safe from a streaming
    generator in any runtime. Do not call ``STOP.wait()`` from a greenlet: it
    is a real Event, and a blocking wait on it stops the eventlet hub.

    Returns:
        True if streams should end.
    """
    deadline = time.monotonic() + max(0.0, timeout)
    while not should_stop():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(poll, remaining))
    return True


def snapshot() -> dict[str, dict[str, int]]:
    """Open and peak counts per kind: ``{kind: {"open": n, "peak": n}}``."""
    with _lock:
        kinds = set(_open) | set(_peak)
        return {kind: {"open": _open.get(kind, 0), "peak": _peak.get(kind, 0)} for kind in kinds}


def stream_counts() -> dict[str, Any]:
    """Open and peak counts with totals, in the shape the admin report reads."""
    with _lock:
        active = dict(_open)
        peak = dict(_peak)
    return {
        "active": active,
        "peak": peak,
        "total_active": sum(active.values()),
        "total_peak": sum(peak.values()),
    }


def open_streams() -> int:
    """How many counted streams are open right now."""
    with _lock:
        return sum(_open.values())


def reset_peaks() -> None:
    """Clear the high-water marks, for example at the start of a soak window."""
    with _lock:
        _peak.clear()
        for kind, count in _open.items():
            if count:
                _peak[kind] = count


def socketio_connection_count() -> int | None:
    """How many Engine.IO sessions the Socket.IO server holds, or None if unknown."""
    try:
        from extensions import socketio

        return len(socketio.server.eio.sockets)
    except Exception:
        return None


def thread_budget() -> dict[str, int | None]:
    """How much of the gthread worker's thread pool long-lived work holds.

    Returns:
        ``{"threads", "streams", "socketio", "headroom"}``. Under eventlet and
        the dev server there is no pool, so ``threads`` and ``headroom`` are
        None. A warning is logged once when headroom first drops below
        ``HEADROOM_WARNING``.
    """
    global _headroom_warned

    threads = runtime.configured_threads()
    streams = open_streams()
    sockets = socketio_connection_count()
    headroom = None
    if threads is not None:
        headroom = threads - streams - (sockets or 0)
        if headroom < HEADROOM_WARNING and not _headroom_warned:
            _headroom_warned = True
            logger.warning(
                f"Only {headroom} of {threads} web server threads are free: "
                f"{streams} live streams and {sockets or 0} browser connections "
                "hold the rest. Close unused OpenAlgo tabs, or raise the thread "
                "count, if pages start loading slowly."
            )
    return {"threads": threads, "streams": streams, "socketio": sockets, "headroom": headroom}


def _reset_for_tests() -> None:
    """Clear every counter and the stop signal. Tests only."""
    global _drain_requested, _headroom_warned, _overflow_warned
    with _lock:
        _open.clear()
        _peak.clear()
    _drain_requested = False
    _headroom_warned = False
    _overflow_warned = False
    STOP.clear()


__all__ = [
    "MAX_KINDS",
    "STOP",
    "StreamTicket",
    "admit",
    "enforced_limit",
    "open_streams",
    "request_drain",
    "reset_peaks",
    "should_stop",
    "snapshot",
    "socketio_connection_count",
    "stream_counts",
    "thread_budget",
    "track_stream",
    "wait_stop",
]
