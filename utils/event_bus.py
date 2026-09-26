"""
Event Bus - Lightweight in-process pub/sub for decoupling order side-effects.

A shared thread pool dispatches subscriber callbacks asynchronously.
Subscribers are registered at app startup and fire for every published event.

**Two lanes.** Most subscribers are best-effort side effects (Socket.IO
refreshes, Telegram and WhatsApp alerts), and the default lane sheds them
under load rather than grow without bound. A subscriber on the money path
(the strategy book booking a fill, say) must not share that cap with a slow
alert sender, so ``subscribe(..., critical=True)`` puts it on a lane of its own
with a far larger cap, where an overflow is logged as an error every time
rather than sampled.

**Sessions are released after every callback.** The pool threads live for
the life of the worker and have no Flask request around them, so nothing else
removes the scoped sessions a callback opens. Left in place, a session's
identity map hands the next callback on that thread the rows it saw last
time, not the rows in the database.
"""

import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, NamedTuple

from utils.db_sessions import remove_all_scoped_sessions
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class Event:
    """Base event class. All events inherit from this."""

    topic: str = ""


class _Subscription(NamedTuple):
    callback: Any
    critical: bool
    name: str


class EventBus:
    """
    In-process event bus with topic-based routing and async dispatch.

    All subscriber callbacks run in a shared thread pool, never blocking the publisher.
    Thread-safe for concurrent subscribe/unsubscribe/publish.
    """

    #: Cap on callbacks queued-or-running at once. ThreadPoolExecutor's own work
    #: queue is unbounded (queue.SimpleQueue), so without this a publisher that
    #: outruns its subscribers grows the queue until the process is OOM-killed.
    #: Production is a single gunicorn worker that never restarts, so there is
    #: nothing to reclaim that memory (issue #1739).
    DEFAULT_MAX_PENDING = 1000

    #: The critical lane's cap and pool size. Larger, because what it carries
    #: must not be shed in a burst; still bounded, for the reason above.
    DEFAULT_CRITICAL_MAX_PENDING = 10000
    DEFAULT_CRITICAL_WORKERS = 4

    def __init__(
        self,
        workers: int = 10,
        max_pending: int = DEFAULT_MAX_PENDING,
        critical_workers: int = DEFAULT_CRITICAL_WORKERS,
        critical_max_pending: int = DEFAULT_CRITICAL_MAX_PENDING,
    ):
        self._subscribers: dict[str, list[_Subscription]] = defaultdict(list)
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="eventbus")
        self._max_pending = max_pending
        self._pending = 0
        self._dropped = 0
        # The critical lane's pool starts no threads until a critical callback
        # is first submitted, so a bus with no critical subscriber costs nothing.
        self._critical_executor = ThreadPoolExecutor(
            max_workers=critical_workers, thread_name_prefix="eventbus-critical"
        )
        self._critical_max_pending = critical_max_pending
        self._critical_pending = 0
        self._critical_dropped = 0

    def subscribe(self, topic: str, callback, name: str = "", critical: bool = False) -> None:
        """Register a callback for a topic. Callback receives the Event object.

        Args:
            topic: The topic to receive.
            callback: Called with the Event, on a pool thread.
            name: A label for logs.
            critical: Run on the critical lane, for subscribers whose work must
                not be shed under load (booking fills, order updates a strategy
                acts on). Default False keeps the best-effort lane.
        """
        cb_name = name or getattr(callback, "__name__", str(callback))
        with self._lock:
            self._subscribers[topic].append(_Subscription(callback, bool(critical), cb_name))
        lane = "critical" if critical else "default"
        logger.debug(f"EventBus: subscribed '{cb_name}' to '{topic}' ({lane} lane)")

    def unsubscribe(self, topic: str, callback) -> None:
        """Remove a callback from a topic."""
        with self._lock:
            subscriptions = self._subscribers[topic]
            for index, subscription in enumerate(subscriptions):
                if subscription.callback == callback:
                    del subscriptions[index]
                    break

    def publish(self, event: Event) -> None:
        """Publish an event to all subscribers of its topic.

        Never blocks the publisher, and never grows without bound: once
        ``max_pending`` callbacks are queued-or-running, further ones are
        dropped rather than queued. Shedding load is the right trade here -
        subscribers are best-effort side effects (logging, Socket.IO refreshes,
        alert delivery), so losing some beats losing the process. Blocking
        instead would push the stall back into the order path that published
        the event.
        """
        with self._lock:
            subscriptions = list(self._subscribers.get(event.topic, []))

        for subscription in subscriptions:
            if subscription.critical:
                self._dispatch_critical(subscription, event)
            else:
                self._dispatch_default(subscription, event)

    def _dispatch_default(self, subscription: _Subscription, event: Event) -> None:
        """Hand one callback to the best-effort lane, or shed it at the cap."""
        with self._lock:
            if self._pending >= self._max_pending:
                self._dropped += 1
                dropped = self._dropped
                admitted = False
            else:
                self._pending += 1
                admitted = True

        if not admitted:
            # Log the first drop and then sparsely: a saturated bus would
            # otherwise turn one incident into a second one in the log file.
            if dropped == 1 or dropped % 100 == 0:
                logger.warning(
                    f"EventBus at capacity ({self._max_pending} pending); dropped "
                    f"'{event.topic}' callback. {dropped} dropped since start."
                )
            return

        # The slot is reserved above, so it must be returned on every path
        # that fails to hand work to the executor - not just the expected
        # RuntimeError from a shut-down pool. A slot leaked here is
        # permanent, and enough of them wedge the bus closed for the life of
        # the worker.
        submitted = False
        try:
            self._executor.submit(self._safe_call, subscription.callback, event)
            submitted = True
        except RuntimeError:
            pass  # Executor already shut down (interpreter teardown).
        finally:
            if not submitted:
                with self._lock:
                    self._pending -= 1

    def _dispatch_critical(self, subscription: _Subscription, event: Event) -> None:
        """Hand one callback to the critical lane. An overflow is always logged."""
        with self._lock:
            if self._critical_pending >= self._critical_max_pending:
                self._critical_dropped += 1
                dropped = self._critical_dropped
                admitted = False
            else:
                self._critical_pending += 1
                admitted = True

        if not admitted:
            logger.error(
                f"EventBus critical lane at capacity ({self._critical_max_pending} "
                f"pending); '{subscription.name}' did not receive a '{event.topic}' "
                f"event. {dropped} critical callbacks dropped since start."
            )
            return

        submitted = False
        try:
            self._critical_executor.submit(self._safe_call_critical, subscription.callback, event)
            submitted = True
        except RuntimeError:
            logger.error(
                f"EventBus critical lane is shut down; '{subscription.name}' did not "
                f"receive a '{event.topic}' event."
            )
        finally:
            if not submitted:
                with self._lock:
                    self._critical_pending -= 1

    @staticmethod
    def _run_callback(cb, event: Event) -> None:
        """Call one subscriber, then release the sessions it opened on this thread."""
        try:
            cb(event)
        except Exception:
            cb_name = getattr(cb, "__name__", str(cb))
            logger.exception(f"EventBus subscriber '{cb_name}' failed on '{event.topic}'")
        finally:
            remove_all_scoped_sessions()

    def _safe_call(self, cb, event: Event) -> None:
        """Execute a best-effort callback with error isolation."""
        try:
            self._run_callback(cb, event)
        finally:
            with self._lock:
                self._pending -= 1

    def _safe_call_critical(self, cb, event: Event) -> None:
        """Execute a critical callback with error isolation."""
        try:
            self._run_callback(cb, event)
        finally:
            with self._lock:
                self._critical_pending -= 1

    def stats(self) -> dict:
        """Queue depth and lifetime drop counts per lane, for health reporting."""
        with self._lock:
            return {
                "pending": self._pending,
                "max_pending": self._max_pending,
                "dropped": self._dropped,
                "critical_pending": self._critical_pending,
                "critical_max_pending": self._critical_max_pending,
                "critical_dropped": self._critical_dropped,
            }


# Global singleton
bus = EventBus()
