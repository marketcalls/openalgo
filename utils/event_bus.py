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

    def __init__(self, workers: int = 10):
        self._subscribers: dict[str, list] = defaultdict(list)
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="eventbus")

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
        """Publish an event to all subscribers of its topic. Non-blocking."""
        with self._lock:
            callbacks = list(self._subscribers.get(event.topic, []))
        for cb in callbacks:
            self._executor.submit(self._safe_call, cb, event)

    def _safe_call(self, cb, event: Event) -> None:
        """Execute a callback with error isolation."""
        try:
            cb(event)
        except Exception:
            cb_name = getattr(cb, "__name__", str(cb))
            logger.exception(f"EventBus subscriber '{cb_name}' failed on '{event.topic}'")


# Global singleton
bus = EventBus()
