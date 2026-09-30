"""The smart-order position cache and per-symbol lock, written once.

A smart order reads the open position for a symbol, works out the order that
takes it to the target size, and places it. Every broker plugin carries its own
copy of the two pieces that make that safe when orders arrive together:

* a **position book cache**, so a burst of smart orders does not fetch the
  whole position book once per order, invalidated after each order so the next
  one sees the fill; and
* a **per-symbol lock**, so two smart orders for one symbol run one after the
  other, each reading the position the previous one left.

The copies have two defects. The cache stores whatever its fetch returned even
when an order was placed, and the cache invalidated, while that fetch was in
flight, so the next order computes against the position from before the fill
and can repeat or reverse it. And the lock registry gains an entry for every
symbol ever traded and never loses one.

:class:`PositionBookCache` is built on ``LockedTTLCache.get_or_load``, whose
generation check returns an overlapping fetch to its own caller but never
caches it. :class:`SymbolLocks` is built on ``KeyedLocks``, whose registry only
holds the symbols in use.

**The wait for a symbol's lock is bounded only under the gthread worker**,
where a queue of smart orders behind one slow broker call would otherwise hold
a request thread each. Under eventlet and the development server it waits as
long as it takes, exactly as the per-broker copies do.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from utils import runtime
from utils.broker_backpressure import BusyResponse
from utils.keyed_locks import KeyedLocks
from utils.thread_safe_cache import LockedTTLCache

#: Longest a smart order waits for another on the same symbol, under gthread.
#: A module constant, not a setting.
SMART_ORDER_LOCK_WAIT_SECONDS = 30.0

#: How long a fetched position book is reused, in seconds.
POSITION_BOOK_TTL_SECONDS = 1.0

#: What a trader sees when a smart order gave up waiting for its symbol.
SMART_ORDER_BUSY_MESSAGE = (
    "Another smart order for {symbol} is still being placed, and this one "
    "waited too long for it to finish. Check your positions, then try again."
)

_DEFAULT = object()


class PositionBookCache:
    """A short-lived cache of the position book, one entry per auth token.

    Args:
        ttl: Seconds a fetched book is reused.
        maxsize: Most tokens held at once. One user has one token a day, so
            this is a ceiling against leaks rather than a working size.
    """

    def __init__(self, ttl: float = POSITION_BOOK_TTL_SECONDS, maxsize: int = 64):
        self._cache = LockedTTLCache(maxsize=maxsize, ttl=ttl)

    def get(self, auth: str, fetch: Callable[[], Any]) -> Any:
        """Return the cached book for ``auth``, calling ``fetch`` on a miss.

        A fetch that was in flight when :meth:`invalidate` ran is returned to
        its caller but not cached, so the next order fetches afresh.
        """
        return self._cache.get_or_load(auth, fetch)

    def invalidate(self, auth: str) -> None:
        """Drop the cached book for ``auth``. Call it after placing an order."""
        self._cache.invalidate(auth)

    def __len__(self) -> int:
        return len(self._cache)


class SymbolLocks:
    """Serialise smart orders per (symbol, exchange, product).

    Args:
        max_wait: Seconds to wait for the symbol under the gthread worker.
            Defaults to ``SMART_ORDER_LOCK_WAIT_SECONDS``. Ignored under
            eventlet and the development server, which wait without limit.
        name: A label for logs and diagnostics.
    """

    def __init__(self, max_wait: float | None = _DEFAULT, name: str = "smart-order"):  # type: ignore[assignment]
        self._max_wait = SMART_ORDER_LOCK_WAIT_SECONDS if max_wait is _DEFAULT else max_wait
        self._locks = KeyedLocks(reentrant=False, name=name)

    def effective_wait(self) -> float | None:
        """The wait that applies now: the bound under gthread, else None."""
        if not runtime.gthread_active():
            return None
        return self._max_wait

    @contextmanager
    def hold(self, symbol: str, exchange: str, product: str) -> Iterator[bool]:
        """Hold the lock for one symbol for the body of a ``with`` block.

        Yields:
            True while holding it. False when the bounded wait ran out; the
            body must then return :meth:`busy` instead of placing an order.
        """
        key = f"{symbol}:{exchange}:{product}"
        with self._locks.try_hold(key, timeout=self.effective_wait()) as acquired:
            yield acquired

    @staticmethod
    def busy(symbol: str) -> tuple[BusyResponse, dict, None]:
        """The order API return tuple for a smart order that gave up waiting."""
        return (
            BusyResponse(429),
            {"status": "error", "message": SMART_ORDER_BUSY_MESSAGE.format(symbol=symbol)},
            None,
        )

    def __len__(self) -> int:
        """How many symbols are held or waited on right now."""
        return len(self._locks)


__all__ = [
    "POSITION_BOOK_TTL_SECONDS",
    "SMART_ORDER_BUSY_MESSAGE",
    "SMART_ORDER_LOCK_WAIT_SECONDS",
    "PositionBookCache",
    "SymbolLocks",
]
