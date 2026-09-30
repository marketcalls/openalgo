"""One lock per key, with a registry that only holds the keys in use.

Serialising work per key (one smart order per symbol, one sandbox fill per
position, one save per OpenScript file) needs a lock per key. The hand-rolled
version is a module dict that gains an entry for every key ever seen and never
loses one, which in a worker that runs for weeks is a leak with the size of the
instrument universe.

:class:`KeyedLocks` refcounts each entry: a caller checks the entry out before
waiting on it and checks it back in after releasing, and the entry is dropped
when the last holder or waiter leaves. Its size is bounded by the keys that are
in use at this moment.

**Which lock is which.** The per-key locks are stdlib ``threading.Lock`` or
``RLock``: green under eventlet, real under gthread and the dev server. They
have to be, because their holders do database and broker I/O while holding
them, and a real lock held across a yielding call freezes the eventlet hub.
The registry is guarded by a real lock from ``utils.real_threading``, whose
critical section is dict work only.

**Rules for callers.**

* Under eventlet a real OS thread (the agent, the Telegram bot) must not take
  these locks directly; it reaches the code that does through
  ``utils.real_threading.run_on_hub``.
* Never hold two keys of one registry at once. Two callers taking the same two
  keys in opposite orders deadlock, and nothing here can detect it.
"""

from __future__ import annotations

import threading
from collections.abc import Hashable, Iterator
from contextlib import contextmanager

from utils import real_threading


class LockBusy(TimeoutError):
    """The lock for a key was not acquired within the allowed wait.

    ``str()`` is a plain sentence a service can pass on; ``key``, ``name`` and
    ``timeout`` carry the detail for logs.
    """

    def __init__(self, key: Hashable, name: str = "", timeout: float | None = None):
        super().__init__(
            "Another request for the same item is still being processed. "
            "Try again in a few seconds."
        )
        self.key = key
        self.name = name
        self.timeout = timeout


class _Entry:
    __slots__ = ("lock", "refs")

    def __init__(self, lock):
        self.lock = lock
        self.refs = 0


class KeyedLocks:
    """A registry of per-key locks that forgets a key once nobody needs it.

    Args:
        reentrant: Use ``RLock`` so the holder may take the same key again.
        name: A label for logs and diagnostics.
    """

    def __init__(self, reentrant: bool = False, name: str = ""):
        self.reentrant = reentrant
        self.name = name
        self._factory = threading.RLock if reentrant else threading.Lock
        self._registry_lock = real_threading.Lock()
        self._entries: dict[Hashable, _Entry] = {}

    def _check_out(self, key: Hashable) -> _Entry:
        with self._registry_lock:
            entry = self._entries.get(key)
            if entry is None:
                entry = _Entry(self._factory())
                self._entries[key] = entry
            entry.refs += 1
            return entry

    def _check_in(self, key: Hashable, entry: _Entry) -> None:
        with self._registry_lock:
            entry.refs -= 1
            if entry.refs <= 0 and self._entries.get(key) is entry:
                del self._entries[key]

    @staticmethod
    def _acquire(entry: _Entry, timeout: float | None) -> bool:
        if timeout is None:
            return entry.lock.acquire()
        if timeout <= 0:
            return entry.lock.acquire(blocking=False)
        return entry.lock.acquire(timeout=timeout)

    @contextmanager
    def try_hold(self, key: Hashable, timeout: float | None = None) -> Iterator[bool]:
        """Hold ``key`` if it can be had in time; yield whether it was.

        Args:
            key: Any hashable naming the thing to serialise on.
            timeout: Seconds to wait; None waits as long as it takes, 0 tries
                once.

        Yields:
            True while holding the lock, False if the wait ran out (the body
            then runs without it, and must not do the protected work).
        """
        entry = self._check_out(key)
        try:
            acquired = self._acquire(entry, timeout)
            try:
                yield acquired
            finally:
                if acquired:
                    entry.lock.release()
        finally:
            self._check_in(key, entry)

    @contextmanager
    def hold(self, key: Hashable, timeout: float | None = None) -> Iterator[None]:
        """Hold ``key`` for the body of a ``with`` block.

        Args:
            key: Any hashable naming the thing to serialise on.
            timeout: Seconds to wait; None waits as long as it takes, 0 tries
                once.

        Raises:
            LockBusy: The lock was not acquired within ``timeout``.
        """
        entry = self._check_out(key)
        try:
            if not self._acquire(entry, timeout):
                raise LockBusy(key, self.name, timeout)
            try:
                yield
            finally:
                entry.lock.release()
        finally:
            self._check_in(key, entry)

    def __len__(self) -> int:
        """How many keys are held or waited on right now."""
        with self._registry_lock:
            return len(self._entries)

    def __repr__(self) -> str:
        return f"KeyedLocks(name={self.name!r}, reentrant={self.reentrant}, keys={len(self)})"


__all__ = ["KeyedLocks", "LockBusy"]
