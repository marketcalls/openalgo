"""Thread-safe TTL cache for the gthread migration (gate A3).

cachetools documents that its cache classes are **not** thread-safe and that
shared access must be synchronized by the caller. Nothing in OpenAlgo did that:
12 modules held 26 ``TTLCache`` instances with no lock at all.

Under eventlet that was survivable because cache operations never yielded, so
two of them could not interleave. Under gthread they can, and a ``TTLCache`` is
not a plain dict -- it maintains an internal linked list for expiry ordering.
Concurrent mutation can corrupt that structure, which surfaces as a spurious
KeyError, a wrong value, or an exception from inside cachetools itself.

``auth_db`` is the sharpest case: it caches auth records, feed tokens, broker
selection, API-key verification results and order mode, all of which are read on
the live order path.

Compound sequences
------------------
Locking each operation stops corruption, but ``if key in cache: cache[key]`` is
still two operations, and a TTL entry can expire between them. Use
``LockedTTLCache.get()``, which is atomic, or hold ``cache.lock`` across the
whole sequence.
"""

import threading

from cachetools import TTLCache

_MISSING = object()


class LockedTTLCache(TTLCache):
    """A ``TTLCache`` whose every operation is serialized by a reentrant lock.

    The lock is reentrant because cachetools calls back into the mapping
    during expiry, which would deadlock a plain ``Lock``.

    ``lock`` is public so callers can make a multi-step sequence atomic:

        with cache.lock:
            if key not in cache:
                cache[key] = expensive()
            return cache[key]
    """

    def __init__(self, maxsize, ttl, *args, **kwargs):
        super().__init__(maxsize, ttl, *args, **kwargs)
        self.lock = threading.RLock()

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
        # Iterate a snapshot: holding the lock across a caller's loop body
        # would invite deadlock, and cachetools expires entries during
        # iteration anyway.
        with self.lock:
            return iter(list(super().__iter__()))

    def get(self, key, default=None):
        """Atomic read. Prefer this over ``key in cache`` then ``cache[key]``."""
        with self.lock:
            value = super().get(key, _MISSING)
        return default if value is _MISSING else value

    def pop(self, key, *args):
        with self.lock:
            return super().pop(key, *args)

    def popitem(self):
        with self.lock:
            return super().popitem()

    def setdefault(self, key, default=None):
        with self.lock:
            return super().setdefault(key, default)

    def clear(self):
        with self.lock:
            super().clear()

    def expire(self, time=None):
        with self.lock:
            return super().expire(time)
