"""
Event Bus - Lightweight in-process pub/sub for decoupling order side-effects.

Single thread pool dispatches all subscriber callbacks asynchronously.
Subscribers are registered at app startup and fire for every published event.
"""

import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class Event:
    """Base event class. All events inherit from this."""

    topic: str = ""


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

    def __init__(self, workers: int = 10, max_pending: int = DEFAULT_MAX_PENDING):
        self._subscribers: dict[str, list] = defaultdict(list)
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="eventbus")
        self._max_pending = max_pending
        self._pending = 0
        self._dropped = 0

    def subscribe(self, topic: str, callback, name: str = "") -> None:
        """Register a callback for a topic. Callback receives the Event object."""
        with self._lock:
            self._subscribers[topic].append(callback)
        cb_name = name or getattr(callback, "__name__", str(callback))
        logger.debug(f"EventBus: subscribed '{cb_name}' to '{topic}'")

    def unsubscribe(self, topic: str, callback) -> None:
        """Remove a callback from a topic."""
        with self._lock:
            try:
                self._subscribers[topic].remove(callback)
            except ValueError:
                pass

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
            callbacks = list(self._subscribers.get(event.topic, []))

        for cb in callbacks:
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
                continue

            # The slot is reserved above, so it must be returned on every path
            # that fails to hand work to the executor - not just the expected
            # RuntimeError from a shut-down pool. A slot leaked here is
            # permanent, and enough of them wedge the bus closed for the life of
            # the worker.
            submitted = False
            try:
                self._executor.submit(self._safe_call, cb, event)
                submitted = True
            except RuntimeError:
                pass  # Executor already shut down (interpreter teardown).
            finally:
                if not submitted:
                    with self._lock:
                        self._pending -= 1

    def _safe_call(self, cb, event: Event) -> None:
        """Execute a callback with error isolation."""
        try:
            cb(event)
        except Exception:
            cb_name = getattr(cb, "__name__", str(cb))
            logger.exception(f"EventBus subscriber '{cb_name}' failed on '{event.topic}'")
        finally:
            with self._lock:
                self._pending -= 1

    def stats(self) -> dict:
        """Current queue depth and lifetime drop count, for health reporting."""
        with self._lock:
            return {
                "pending": self._pending,
                "max_pending": self._max_pending,
                "dropped": self._dropped,
            }


# Global singleton
bus = EventBus()
