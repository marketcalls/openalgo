"""A thread-safe TTL cache whose fills cannot undo an invalidation.

cachetools documents that its caches are not thread-safe and that shared
access must be synchronised by the caller. A ``TTLCache`` is not a plain dict:
it keeps a linked list for expiry order, and two threads mutating it at once
can corrupt that list, which surfaces as a spurious KeyError, a wrong value or
an exception from inside cachetools. Under eventlet that could not happen,
because no cache operation yields; under the gthread worker it can.

Locking each operation is not the whole problem. The read-through pattern

    value = cache.get(key)
    if value is None:
        value = load_from_database()   # slow, outside any lock
        cache[key] = value

has a window between the load and the store. If a writer commits a change and
invalidates the key inside that window, the store puts the value read before
the change back into the cache, and every reader after it sees the stale value
until the TTL runs out. For the analyzer-mode and order-mode caches that is an
order sent to the wrong destination.

:meth:`LockedTTLCache.get_or_load` closes it with a generation counter. The
generation is read before the loader runs, every :meth:`invalidate` and
:meth:`clear` bumps it, and the fill is stored only if the generation has not
moved. A load that overlapped an invalidation is still returned to its own
caller, which asked before the change, but it is never cached. Writers must
call :meth:`invalidate` strictly after their commit.

The lock is a real one from ``utils.real_threading``, because real OS threads
(the websocket loop, the Telegram bot) read some of these caches too. Its
critical section is dict work only, so a greenlet never waits on it for more
than microseconds, and loaders always run outside it.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Hashable
from typing import Any

from cachetools import TTLCache

from utils import real_threading

#: Returned by nothing and stored by nothing: marks "no value" where None is a
#: legitimate cached value.
MISSING = object()


class LockedTTLCache(TTLCache):
    """A ``TTLCache`` whose every operation runs under one reentrant lock.

    Reentrant because cachetools calls back into the mapping during expiry
    and eviction (``popitem`` calls ``pop``), which would deadlock a plain lock.

    Iteration (``iter``, ``keys``, ``values``, ``items``) works on a snapshot
    taken under the lock, so a caller's loop body never runs while holding it
    and an entry expiring mid-loop cannot raise.

    Use :meth:`invalidate` rather than ``pop`` or ``del`` to drop an entry a
    writer has made stale: only invalidation stops an in-flight fill from
    putting it back.
    """

    def __init__(
        self,
        maxsize: int,
        ttl: float,
        timer: Callable[[], float] = time.monotonic,
        getsizeof: Callable[[Any], int] | None = None,
    ):
        super().__init__(maxsize, ttl, timer=timer, getsizeof=getsizeof)
        self.lock = real_threading.RLock()
        self._generation = 0

    # -- Mapping protocol, each under the lock -------------------------------

    def __getitem__(self, key):
        with self.lock:
            return super().__getitem__(key)

    def __setitem__(self, key, value):
        with self.lock:
            super().__setitem__(key, value)

    def __delitem__(self, key):
        with self.lock:
            super().__delitem__(key)

    def __contains__(self, key):
        with self.lock:
            return super().__contains__(key)

    def __len__(self):
        with self.lock:
            return super().__len__()

    def __iter__(self):
        with self.lock:
            return iter(list(super().__iter__()))

    def __repr__(self):
        with self.lock:
            return super().__repr__()

    def keys(self):
        """Keys present now, as a list."""
        with self.lock:
            return list(super().__iter__())

    def values(self):
        """Values present now, as a list."""
        return list(self.snapshot().values())

    def items(self):
        """(key, value) pairs present now, as a list."""
        return list(self.snapshot().items())

    def get(self, key, default=None):
        """Atomic read. Prefer this over ``key in cache`` then ``cache[key]``."""
        with self.lock:
            value = super().get(key, MISSING)
        return default if value is MISSING else value

    def pop(self, key, default=None):
        """Remove ``key`` and return its value, or ``default``. Never raises."""
        with self.lock:
            try:
                return super().pop(key, default)
            except KeyError:
                return default

    def popitem(self):
        with self.lock:
            return super().popitem()

    def setdefault(self, key, default=None):
        with self.lock:
            return super().setdefault(key, default)

    def clear(self):
        """Drop every entry. Counts as an invalidation of all of them."""
        with self.lock:
            super().clear()
            self._generation += 1

    def expire(self, time=None):
        with self.lock:
            return super().expire(time)

    # -- Invalidation-aware fills ----------------------------------------------

    @property
    def generation(self) -> int:
        """Bumped by every invalidate() and clear(). Read it before a load."""
        with self.lock:
            return self._generation

    def fill(self, key: Hashable, value: Any, generation: int) -> bool:
        """Store ``value`` only if nothing was invalidated since ``generation``.

        Args:
            key: The cache key.
            value: The loaded value.
            generation: :attr:`generation` as read before the load started.

        Returns:
            True if stored, False if an invalidation made the value stale.
        """
        with self.lock:
            if generation != self._generation:
                return False
            super().__setitem__(key, value)
            return True

    def get_or_load(
        self,
        key: Hashable,
        loader: Callable[[], Any],
        *,
        should_cache: Callable[[Any], bool] | None = None,
    ) -> Any:
        """Return the cached value for ``key``, loading and filling it on a miss.

        The loader runs outside the lock, so it may do database or network
        work. Two callers missing at once may both load; each gets its own
        result. A load that overlapped an :meth:`invalidate` is returned to its
        caller but not stored.

        Args:
            key: The cache key.
            loader: Called with no arguments on a miss.
            should_cache: Optional predicate; a loaded value it rejects (an
                empty or error result, say) is returned but not stored.

        Returns:
            The cached or freshly loaded value.
        """
        with self.lock:
            value = super().get(key, MISSING)
            generation = self._generation
        if value is not MISSING:
            return value
        value = loader()
        if should_cache is None or should_cache(value):
            self.fill(key, value, generation)
        return value

    def invalidate(self, key: Hashable = None) -> None:
        """Drop one key, or every key when ``key`` is None, and stop stale fills.

        Call it after the writer's commit, never before: an invalidation that
        runs first leaves a window in which a reader can load the old row and
        store it with a fresh generation.
        """
        with self.lock:
            if key is None:
                super().clear()
            else:
                try:
                    super().pop(key, None)
                except KeyError:
                    pass
            self._generation += 1

    def invalidate_where(self, predicate: Callable[[Hashable], bool]) -> int:
        """Drop every key for which ``predicate(key)`` is true.

        The predicate runs under the lock, so it must be a cheap, pure function
        of the key.

        Returns:
            How many entries were dropped.
        """
        with self.lock:
            doomed = [key for key in list(super().__iter__()) if predicate(key)]
            for key in doomed:
                try:
                    super().pop(key, None)
                except KeyError:
                    pass
            self._generation += 1
            return len(doomed)

    def snapshot(self) -> dict:
        """A plain dict copy of the live (unexpired) entries."""
        with self.lock:
            result = {}
            for key in list(super().__iter__()):
                value = super().get(key, MISSING)
                if value is not MISSING:
                    result[key] = value
            return result


__all__ = ["MISSING", "LockedTTLCache"]
