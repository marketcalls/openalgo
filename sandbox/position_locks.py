# sandbox/position_locks.py
"""One sandbox order at a time per position.

Several paths read a sandbox position and then place an order sized from what
they read: closing a position, the auto square-off, a smart order working out
how far it is from its target, a CNC sell checked against the shares held, a
GTT leg firing. Two of them on the same position, both reading it before
either order lands, act on the same snapshot: two closers reverse the position
instead of flattening it, two smart orders for position size 0 both sell the
whole quantity, two CNC sells of the same shares both pass the check.

Each of those paths holds this lock for its position from the read through
the order it places. The locks are per position (user, symbol, exchange,
product), so unrelated symbols never wait on each other, and reentrant, so a
closer that holds its position's lock can place the order that takes it again.

**Which lock.** The per-key locks are stdlib locks from
``utils.keyed_locks.KeyedLocks``: green under eventlet, where every caller is a
greenlet, and real under gthread and on the development server. They are held
across the order's quote fetch, which is why they must not be real locks
under eventlet. A real OS thread (the agent, the Telegram bot) must reach
these paths through ``utils.real_threading.run_on_hub`` under eventlet.

**How long a caller waits.** Under the gthread worker a caller waits at most
:data:`POSITION_LOCK_WAIT_SECONDS` and is then told to try again, so a stuck
order cannot park request threads indefinitely. Everywhere else (eventlet, the
development server) it waits as long as it takes, exactly as before, because
refusing an order is something a trader notices.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from utils.keyed_locks import KeyedLocks, LockBusy
from utils.logging import get_logger
from utils.runtime import gthread_active

logger = get_logger(__name__)

#: How long an order waits for another order on the same position, under the
#: gthread worker only. A fixed constant, not a setting.
POSITION_LOCK_WAIT_SECONDS = 30.0

_position_locks = KeyedLocks(reentrant=True, name="sandbox-position")


def position_key(user_id, exchange, symbol, product) -> tuple:
    """The key a position's lock is held under.

    Exchange and product are upper-cased the way order placement normalises
    them, so a smart order and the order it places agree on the key.
    """
    return (str(user_id), str(symbol), str(exchange or "").upper(), str(product or "").upper())


def position_wait_seconds() -> float | None:
    """The wait allowed for a position's lock: bounded only under gthread."""
    return POSITION_LOCK_WAIT_SECONDS if gthread_active() else None


@contextmanager
def position_lock(user_id, exchange, symbol, product) -> Iterator[None]:
    """Hold the lock for one sandbox position for the body of a ``with`` block.

    Args:
        user_id: The position's owner.
        exchange: Exchange code.
        symbol: OpenAlgo symbol.
        product: CNC, NRML or MIS.

    Raises:
        LockBusy: Under gthread only, when another order on the same position
            held it for longer than :data:`POSITION_LOCK_WAIT_SECONDS`.
    """
    with _position_locks.hold(
        position_key(user_id, exchange, symbol, product), timeout=position_wait_seconds()
    ):
        yield


def position_busy_response(symbol) -> tuple[bool, dict, int]:
    """What a caller refused by a busy position lock returns, in the sandbox's shape."""
    return (
        False,
        {
            "status": "error",
            "message": (
                f"Another order for {symbol} is still being processed. Try again in a moment."
            ),
            "mode": "analyze",
        },
        409,
    )


def holds_position_lock(key_of: Callable[..., tuple | None]):
    """Run a method holding the lock of the position its arguments name.

    Args:
        key_of: Called with the method's own arguments; returns
            ``(user_id, exchange, symbol, product)``, or None when they do not
            name a position (the method then runs unlocked and rejects them).

    Returns:
        A decorator. The wrapped method returns :func:`position_busy_response`
        when the lock could not be had in time; any other outcome is its own.
    """

    def decorator(method):
        @functools.wraps(method)
        def wrapper(*args, **kwargs):
            key = key_of(*args, **kwargs)
            if key is None:
                return method(*args, **kwargs)
            lock = position_lock(*key)
            try:
                lock.__enter__()
            except LockBusy:
                logger.warning(
                    f"Sandbox order for {key[2]} ({key[1]}, {key[3]}) refused: another "
                    f"order on the same position held it for {POSITION_LOCK_WAIT_SECONDS}s"
                )
                return position_busy_response(key[2])
            try:
                return method(*args, **kwargs)
            finally:
                lock.__exit__(None, None, None)

        return wrapper

    return decorator


def held_position_count() -> int:
    """How many positions are locked or waited on right now (diagnostics, tests)."""
    return len(_position_locks)


__all__ = [
    "POSITION_LOCK_WAIT_SECONDS",
    "LockBusy",
    "held_position_count",
    "holds_position_lock",
    "position_busy_response",
    "position_key",
    "position_lock",
    "position_wait_seconds",
]
