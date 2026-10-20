"""One bounded-wait policy and one exception for broker request pacing.

Every broker plugin paces its requests to stay inside the broker's published
rate limits, and today every one of them does it by making the caller wait for
as long as the queue in front of it takes. Under eventlet that wait is a green
sleep and costs nothing but time. Under the gthread worker it holds one of a
fixed number of request threads for the whole wait, and a burst (a basket, an
option chain refresh, a strategy firing on every symbol at once) can park all
of them behind one slow broker, at which point the whole app stops answering.

So under gthread a wait has a ceiling. A caller whose turn would come later
than the ceiling is refused at once with :class:`BrokerBusyError`, whose text
is a sentence a trader can act on, instead of sleeping. Under eventlet and the
development server there is no ceiling: :func:`max_queue_wait` returns None and
every helper here behaves as the unbounded wait it replaces.

The ceilings are module constants, not settings. OpenAlgo adds exactly one
configuration key for the gthread worker (``OPENALGO_WORKER_CLASS``).

Limiters use it in one of three ways:

* A limiter that books a future slot calls :func:`check_queue_wait` with the
  wait it computed **before** booking the slot, so a refused caller leaves no
  reservation behind to delay everyone after it.
* A limiter that waits on a lock uses :func:`acquire_bounded`.
* A retry loop honouring a broker's ``Retry-After`` passes the delay through
  :func:`cap_server_delay` and stops retrying on None.
"""

from __future__ import annotations

import threading
from typing import Any

from utils import runtime

#: Longest a market-data request may wait for its turn under gthread, seconds.
BROKER_MAX_QUEUE_WAIT_SECONDS = 10.0

#: Longest an order request (and a positions read inside a smart order) may
#: wait for its turn under gthread, seconds. An order sent long after the
#: trader decided is worse than a refusal the caller can retry.
BROKER_MAX_ORDER_QUEUE_WAIT_SECONDS = 10.0

_CEILINGS = {
    "data": BROKER_MAX_QUEUE_WAIT_SECONDS,
    "order": BROKER_MAX_ORDER_QUEUE_WAIT_SECONDS,
}

#: What a trader sees when a request is refused for waiting too long.
BROKER_BUSY_MESSAGE = (
    "OpenAlgo is pacing requests to stay within your broker's rate limit, and "
    "this one would have had to wait too long for its turn. Try again in a few "
    "seconds."
)


class BrokerBusyError(Exception):
    """A broker request was refused because its turn would come too late.

    ``str(error)`` is the trader-facing sentence. ``retry_after`` is the wait
    that was refused, in seconds, when known.
    """

    def __init__(self, message: str | None = None, retry_after: float | None = None):
        super().__init__(message or BROKER_BUSY_MESSAGE)
        self.retry_after = retry_after
        _note_refusal()


#: The same class under the name the rate-limiter partition asked for.
RateLimitBusy = BrokerBusyError


class BusyResponse:
    """Stands in for an HTTP response in an order API's ``(res, data, id)`` tuple.

    Services read ``res.status`` (and some ``res.status_code``) to decide what
    to return, so a refusal made before any HTTP call still needs both.
    """

    def __init__(self, status: int = 429):
        self.status = status
        self.status_code = status
        _note_refusal()

    def __repr__(self) -> str:
        return f"BusyResponse({self.status})"


# -- Knowing that a call was refused before it was sent -----------------------
#
# A service answers a refusal with HTTP 429 and a sentence, but so does a broker
# that throttled a request it may already have accepted, and only the first
# proves that nothing reached the broker. A caller that must know which (the
# Action Center, to offer an order back for approval) records refusals on its
# own thread while it calls the service. Refusals happen only under gthread.

_refusals = threading.local()


def _note_refusal() -> None:
    counter = getattr(_refusals, "counter", None)
    if counter is not None:
        counter[0] += 1


class RefusalRecorder:
    """Counts the refusals made on the calling thread between start and stop."""

    def __init__(self) -> None:
        self._counter = [0]
        self._outer = None

    def start(self) -> RefusalRecorder:
        self._outer = getattr(_refusals, "counter", None)
        _refusals.counter = self._counter
        return self

    def stop(self) -> None:
        _refusals.counter = self._outer

    @property
    def refused(self) -> bool:
        """True when a request was refused before it was sent."""
        return self._counter[0] > 0


def _check_kind(kind: str) -> str:
    if kind not in _CEILINGS:
        raise ValueError(f"unknown broker queue kind {kind!r}; use 'data' or 'order'")
    return kind


def max_queue_wait(kind: str = "data") -> float | None:
    """Return the longest wait allowed for ``kind``, or None for no limit.

    Args:
        kind: ``"data"`` or ``"order"``.

    Returns:
        The ceiling in seconds under the gthread worker; None (wait as long as
        it takes, as before) under eventlet and the development server.
    """
    _check_kind(kind)
    if not runtime.gthread_active():
        return None
    return _CEILINGS[kind]


def check_queue_wait(wait_seconds: float, kind: str = "data") -> None:
    """Refuse a wait longer than the ceiling for ``kind``.

    Call it with the computed wait before booking a slot, so a refused caller
    leaves no reservation behind.

    Raises:
        BrokerBusyError: ``wait_seconds`` exceeds :func:`max_queue_wait`.
    """
    ceiling = max_queue_wait(kind)
    if ceiling is not None and wait_seconds > ceiling:
        raise BrokerBusyError(retry_after=wait_seconds)


def cap_server_delay(seconds: float, kind: str = "data") -> float | None:
    """Pass a broker-requested delay through the ceiling for ``kind``.

    Returns:
        ``seconds`` when it is within the ceiling or there is none; None when
        the broker asked for longer, meaning: stop retrying and surface
        :data:`BROKER_BUSY_MESSAGE`.
    """
    ceiling = max_queue_wait(kind)
    if ceiling is not None and seconds > ceiling:
        return None
    return seconds


def acquire_bounded(lock: Any, kind: str = "data") -> bool:
    """Acquire ``lock`` within the ceiling for ``kind``.

    Returns:
        True once held. False when the ceiling ran out first (never without a
        ceiling, where this waits as long as it takes).
    """
    ceiling = max_queue_wait(kind)
    if ceiling is None:
        return lock.acquire()
    return lock.acquire(timeout=ceiling)


def busy_response(message: str | None = None, status: int = 429) -> tuple[BusyResponse, dict, None]:
    """An order API return tuple for a request refused before it was sent."""
    return (
        BusyResponse(status),
        {"status": "error", "message": message or BROKER_BUSY_MESSAGE},
        None,
    )


__all__ = [
    "BROKER_BUSY_MESSAGE",
    "BROKER_MAX_ORDER_QUEUE_WAIT_SECONDS",
    "BROKER_MAX_QUEUE_WAIT_SECONDS",
    "BrokerBusyError",
    "BusyResponse",
    "RateLimitBusy",
    "RefusalRecorder",
    "acquire_bounded",
    "busy_response",
    "cap_server_delay",
    "check_queue_wait",
    "max_queue_wait",
]
