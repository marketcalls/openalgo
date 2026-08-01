"""Bounded retry for SQLite snapshot conflicts (gthread gate A4).

The problem this solves, and the one it deliberately does *not*
--------------------------------------------------------------
WAL, ``synchronous=NORMAL`` and ``busy_timeout=15000`` are applied to every
connection by ``database/__init__.py``. ``busy_timeout`` handles plain
``SQLITE_BUSY`` (code 5): the writer waits for the lock and usually gets it.

It cannot handle ``SQLITE_BUSY_SNAPSHOT`` (code 517). That is raised when a
deferred transaction has already read, another connection committed since, and
this transaction now tries to write. SQLite returns immediately and never calls
the busy handler, because waiting cannot help -- the snapshot is stale. The only
fix is to *restart the transaction*, re-reading current state.

So the rule is asymmetric, and getting it backwards is worse than doing nothing:

* ``SQLITE_BUSY_SNAPSHOT`` -> retry, immediately, with a fresh session.
* ``SQLITE_BUSY`` -> do NOT retry. ``busy_timeout`` already waited 15 seconds.
  Three attempts would park a worker thread for 45 seconds, converting a brief
  contention spike into a thread-pool outage dressed up as resilience.

Two hard constraints on callers
-------------------------------
1. **The retried callable must re-read the state it modifies.** Replaying a
   delta computed from a stale read corrupts the value it is protecting. This
   is why the whole read-modify-write goes inside the callable rather than just
   the commit.
2. **No broker or network side effect may occur inside the boundary.** A retry
   re-runs everything in the callable; if that includes placing an order, the
   order is placed twice. Local transaction only.
"""

import functools
import random
import sqlite3
import time

from sqlalchemy.exc import OperationalError

from utils.logging import get_logger

logger = get_logger(__name__)

# Extended result codes. 517 == SQLITE_BUSY_SNAPSHOT (5 | (2 << 8)).
SQLITE_BUSY = 5
SQLITE_BUSY_SNAPSHOT = 517

DEFAULT_ATTEMPTS = 3
DEFAULT_MAX_SECONDS = 2.0


def _sqlite_error(exc: BaseException) -> sqlite3.Error | None:
    """Unwrap the DBAPI error SQLAlchemy wraps, if this is one."""
    if isinstance(exc, sqlite3.Error):
        return exc
    orig = getattr(exc, "orig", None)
    return orig if isinstance(orig, sqlite3.Error) else None


def is_snapshot_conflict(exc: BaseException) -> bool:
    """True only for SQLITE_BUSY_SNAPSHOT, never for plain SQLITE_BUSY.

    Both surface as the message "database is locked", which is why matching on
    the message would retry the case that must not be retried.
    """
    err = _sqlite_error(exc)
    if err is None:
        return False
    return getattr(err, "sqlite_errorcode", None) == SQLITE_BUSY_SNAPSHOT


def is_plain_busy(exc: BaseException) -> bool:
    """True for SQLITE_BUSY, which busy_timeout has already waited out."""
    err = _sqlite_error(exc)
    if err is None:
        return False
    return getattr(err, "sqlite_errorcode", None) == SQLITE_BUSY


def retry_on_snapshot_conflict(
    session_factory=None,
    attempts: int = DEFAULT_ATTEMPTS,
    max_seconds: float = DEFAULT_MAX_SECONDS,
):
    """Re-run an idempotent local transaction on a snapshot conflict.

    Args:
        session_factory: the module's ``scoped_session``. Its ``.remove()`` is
            called between attempts so the retry gets a genuinely new session,
            and therefore a new snapshot. Without this the retry would re-read
            the same stale data and fail identically.
        attempts: total tries, including the first.
        max_seconds: ceiling on cumulative backoff, so a retry can never park a
            worker thread for an unbounded time.

    The wrapped callable must re-read whatever it modifies and must not perform
    any broker or network side effect. See the module docstring.
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            started = time.monotonic()
            for attempt in range(1, attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except (OperationalError, sqlite3.Error) as exc:
                    if not is_snapshot_conflict(exc):
                        # Plain BUSY has already had its 15s; anything else is
                        # not a contention problem. Either way, do not retry.
                        raise
                    if attempt == attempts or (time.monotonic() - started) >= max_seconds:
                        logger.warning(
                            "Snapshot conflict in %s persisted after %d attempt(s)",
                            fn.__qualname__,
                            attempt,
                        )
                        raise

                    # Drop the session so the next attempt reads fresh state.
                    if session_factory is not None:
                        try:
                            session_factory.remove()
                        except Exception:
                            logger.exception("Failed to release session before retry")

                    # Small jittered pause: concurrent writers that retry in
                    # lockstep would simply collide again.
                    time.sleep(random.uniform(0.005, 0.02) * attempt)
                    logger.debug(
                        "Retrying %s after snapshot conflict (attempt %d/%d)",
                        fn.__qualname__,
                        attempt + 1,
                        attempts,
                    )
            raise AssertionError("unreachable")  # pragma: no cover

        return wrapper

    return decorator
