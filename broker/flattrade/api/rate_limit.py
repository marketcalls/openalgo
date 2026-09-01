"""Shared request pacing for every Flattrade HTTP entry point.

Flattrade documents two separate ceilings
(broker-api-docs/flattrade-api-docs/14-rate-limits.md):

    order endpoints      10 req/sec   and   40 req/min
    non-order endpoints  40 req/sec   and  200 req/min

Before this module the dual sliding-window limiter lived inside
broker/flattrade/api/data.py and was reachable only from that file's
``get_api_response``. Everything else — order_api.py (which has its own
``get_api_response``, plus place/modify/cancel), funds.py and margin_api.py —
issued unpaced requests, so the orderbook/positions/funds polling that the UI
does continuously was never counted against either window, and
``close_all_positions`` / ``cancel_all_orders_api`` fired their per-order calls
in a bare ``for`` loop that can breach the 10/sec order limit outright. Both
limiters now live here and every Flattrade caller shares them, which is the only
way a shared window can actually be shared.

Two limiters, not one: the order ceiling is four times tighter, so pacing order
placement against the data window would let a burst of orders through, while
pacing quote fetches against the order window would throttle them pointlessly.

**Adaptive clamping.** The documented numbers are the ceiling for a
fully-provisioned account, not a promise about yours. Flattrade provisions some
accounts lower and reports it only in the rejection text:

    "Invalid Input : Order Recieved 11 in a current second exceeds Limit 10 for user"

``note_rate_limit_rejection`` parses that ``Limit N`` and clamps the offending
window for the rest of the process, so the retry that follows is not just a
slower repeat of a request the account was never allowed to make. The clamp only
ever ratchets downward, and is reported once at WARNING when it moves.
"""

from __future__ import annotations

import asyncio
import os
import re
import threading
import time
from collections import deque

from utils.logging import get_logger

logger = get_logger(__name__)


def _env_int(name: str, default: int, ceiling: int) -> int:
    """Read a positive int from the environment, bounded by `ceiling`.

    `ceiling` is the highest figure Flattrade publishes for that window
    (14-rate-limits.md). An override exists so a higher-tier account is not
    pinned to the conservative default, but nothing legitimate sits above the
    published table, and an override that does is a typo (a stray zero on
    "380") that would silently disable the pacing this module exists to
    provide. Clamp rather than trust, and say so.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        logger.warning(f"{name}={raw!r} is not an integer; using {default}")
        return default
    if value < 1:
        logger.warning(f"{name}={value} must be >= 1; using {default}")
        return default
    if value > ceiling:
        logger.warning(
            f"{name}={value} is above Flattrade's published ceiling of {ceiling}; "
            f"using {ceiling}. Nothing is provisioned above the published table, "
            "so this is almost certainly a typo."
        )
        return ceiling
    return value


# Flattrade's own rejection text, e.g.
#   "Order Recieved 11 in a current second exceeds Limit 10 for user"
# (the broker's spelling of "Received" is reproduced, not corrected — it is
# matched case-insensitively and only "exceeds Limit N" is actually captured).
_LIMIT_IN_MESSAGE = re.compile(r"exceeds\s+limit\s+(\d+)", re.IGNORECASE)
_PER_SECOND_HINT = re.compile(r"current\s+second", re.IGNORECASE)
_PER_MINUTE_HINT = re.compile(r"current\s+minute", re.IGNORECASE)


class SlidingWindowLimiter:
    """Dual rolling-window limiter: bursts to the per-second cap, hard-capped
    on both windows.

    Reservation happens inside the lock; sleeping is the caller's job, outside
    the lock, so concurrent threads queue without serializing on the lock.

    The deque holds reserved call timestamps in non-decreasing order (each new
    reservation is >= the previous by construction: a full window pushes the new
    slot past entries the previous reservation also sat behind). The earliest
    permissible slot is:

      - now, if neither window is full at that instant;
      - 1s after the Nth-most-recent reservation when the per-second window is
        full (that entry must age out of the rolling second first);
      - 60s after the Mth-most-recent reservation when the per-minute window is
        full;

    whichever is latest. Entries older than 60s can no longer constrain any
    future slot and are purged.
    """

    def __init__(self, name: str, max_per_second: int, max_per_minute: int):
        self.name = name
        self.max_per_second = max_per_second
        self.max_per_minute = max_per_minute
        self._lock = threading.Lock()
        self._reserved: deque[float] = deque()

    def reserve(self) -> float:
        """Reserve the earliest slot satisfying both windows.

        Returns the seconds the caller must sleep before issuing its request.
        """
        with self._lock:
            now = time.time()
            while self._reserved and self._reserved[0] <= now - 60.0:
                self._reserved.popleft()

            slot = now
            if len(self._reserved) >= self.max_per_second:
                slot = max(slot, self._reserved[-self.max_per_second] + 1.0)
            if len(self._reserved) >= self.max_per_minute:
                slot = max(slot, self._reserved[-self.max_per_minute] + 60.0)

            self._reserved.append(slot)
            return slot - now

    def acquire(self) -> None:
        """Block until this caller's reserved slot arrives."""
        sleep_time = self.reserve()
        if sleep_time > 0:
            logger.debug(
                f"Rate limiting ({self.name}): sleeping {sleep_time:.2f}s "
                "before Flattrade API call"
            )
            time.sleep(sleep_time)

    async def acquire_async(self) -> None:
        """Same reservation, awaiting asyncio.sleep so the loop is not blocked."""
        sleep_time = self.reserve()
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)

    def clamp_per_second(self, limit: int) -> bool:
        """Lower the per-second cap to `limit`. Ratchets down only.

        Returns True when the cap actually moved.
        """
        with self._lock:
            if limit < 1 or limit >= self.max_per_second:
                return False
            previous = self.max_per_second
            self.max_per_second = limit
        logger.warning(
            f"Flattrade reported a per-second limit of {limit} for the {self.name} "
            f"endpoints; lowering the local cap from {previous} to {limit} for the "
            "rest of this process. Set FLATTRADE_MAX_PER_SECOND to pin this "
            "explicitly and avoid the first rejection."
        )
        return True

    def clamp_per_minute(self, limit: int) -> bool:
        """Lower the per-minute cap to `limit`. Ratchets down only."""
        with self._lock:
            if limit < 1 or limit >= self.max_per_minute:
                return False
            previous = self.max_per_minute
            self.max_per_minute = limit
        logger.warning(
            f"Flattrade reported a per-minute limit of {limit} for the {self.name} "
            f"endpoints; lowering the local cap from {previous} to {limit} for the "
            "rest of this process."
        )
        return True


# Non-order defaults are set from OBSERVED enforcement, not from the published
# table, because the two disagree.
#
# 14-rate-limits.md publishes 40/sec and 200/min. A live account on 2026-09-01
# was rejected at both a much lower per-second and per-minute ceiling, and the
# rejection text named them:
#
#   "Invalid Input :  Order Recieved 11 in a current second exceeds Limit 10 for user"
#
# giving 10/sec and 120/min. Those are exactly the figures TradeSmart — the same
# Noren backend — publishes for its general budget
# (broker/tradesmart/api/rate_limiter.py: 10/sec, 120/min), which is strong
# evidence that 10/120 is the Noren platform's native shape and that the 40/200
# in Flattrade's docs describes a higher provisioning tier rather than the
# default one.
#
# Defaulting to the published 38/190 meant the adaptive clamp below had to
# discover the truth by being rejected, and since the clamp is process-local
# every restart paid that rejection again (observed twice in one morning:
# "lowering the local cap from 38 to 10" at 11:13 and again at 11:22 after a
# restart). Starting at the real ceiling costs nothing on a correctly
# provisioned account beyond throughput that account was never going to get,
# and costs a burst of failed quotes on every other one.
#
# 9/110 rather than 10/120: the same margin TradeSmart uses, for clock skew
# between our rolling windows and however Noren measures theirs.
#
# Accounts on the higher tier (see 01-introduction.md, "More Than 10 Orders Per
# Second") should raise these with FLATTRADE_MAX_PER_SECOND /
# FLATTRADE_MAX_PER_MINUTE — the clamp only ever ratchets down, so a raised cap
# is still protected by it.
DATA_LIMITER = SlidingWindowLimiter(
    "data",
    max_per_second=_env_int("FLATTRADE_MAX_PER_SECOND", 9, ceiling=40),
    max_per_minute=_env_int("FLATTRADE_MAX_PER_MINUTE", 110, ceiling=200),
)

# Documented order ceiling is 10/sec and 40/min, which matches the observed
# per-second figure above, so the published numbers are kept here; 9/38 for the
# same margin.
ORDER_LIMITER = SlidingWindowLimiter(
    "order",
    max_per_second=_env_int("FLATTRADE_ORDER_MAX_PER_SECOND", 9, ceiling=10),
    max_per_minute=_env_int("FLATTRADE_ORDER_MAX_PER_MINUTE", 38, ceiling=40),
)


def is_rate_limit_error(response) -> bool:
    """Return True when a parsed Flattrade response is a rate-limit rejection."""
    if not isinstance(response, dict):
        return False
    if response.get("stat") != "Not_Ok":
        return False
    emsg = str(response.get("emsg", ""))
    return "exceeds limit" in emsg.lower()


MAX_RATE_LIMIT_RETRIES = 3
RATE_LIMIT_BASE_DELAY = 2.0  # seconds, doubled per attempt: 2, 4, 8


def rate_limit_retry_delay(
    response,
    limiter: SlidingWindowLimiter,
    retry_count: int,
    context: str = "",
) -> float | None:
    """Clamp from a rejection and return how long to wait before retrying.

    Returns None when the response was not a rate-limit rejection, or when the
    retry budget is spent — in both cases the caller returns the response.

    The recursive re-issue stays at the call site because each one has a
    different signature and one of them is async; everything that was actually
    duplicated (detection, clamping, the attempt count, the backoff curve and
    the warning) lives here. Retry policy is now changed in one place instead
    of the five copies this replaced.

    Order endpoints deliberately do not use this: see clamp_from_response.
    """
    if not clamp_from_response(response, limiter):
        return None
    if retry_count >= MAX_RATE_LIMIT_RETRIES:
        logger.warning(
            f"Flattrade rate limit still hit after {MAX_RATE_LIMIT_RETRIES} "
            f"retries{f' on {context}' if context else ''}; giving up. "
            f"The {limiter.name} cap is now {limiter.max_per_second}/sec, "
            f"{limiter.max_per_minute}/min."
        )
        return None

    delay = RATE_LIMIT_BASE_DELAY * (2**retry_count)
    emsg = response.get("emsg") if isinstance(response, dict) else None
    logger.warning(
        f"Flattrade rate limit hit{f' on {context}' if context else ''} ({emsg}). "
        f"Retrying in {delay}s (attempt {retry_count + 1}/{MAX_RATE_LIMIT_RETRIES})"
    )
    return delay


def clamp_from_response(response, limiter: SlidingWindowLimiter) -> bool:
    """Learn from `response` if it is a rate-limit rejection.

    Returns True when it was one, so the caller can decide whether to retry.
    Combines the detect-then-clamp pair every Flattrade entry point needs, so a
    call site cannot pace its requests but forget to adapt (which is exactly
    what order_api.py, funds.py and margin_api.py did).

    Note for order endpoints: clamp, but do NOT auto-retry. A PlaceOrder that
    was rejected for rate is safe to retry, but this code cannot distinguish
    that from a response lost after the broker accepted it, and a duplicate
    order is far worse than a failed one. Read-only endpoints retry; order
    endpoints surface the error.
    """
    if not is_rate_limit_error(response):
        return False
    note_rate_limit_rejection(response, limiter)
    return True


def note_rate_limit_rejection(response, limiter: SlidingWindowLimiter) -> None:
    """Teach `limiter` the ceiling Flattrade just named in its rejection.

    A no-op unless the message actually carries a "Limit N", so an unparseable
    rejection simply leaves the configured caps alone.
    """
    if not isinstance(response, dict):
        return
    emsg = str(response.get("emsg", ""))
    match = _LIMIT_IN_MESSAGE.search(emsg)
    if not match:
        return
    try:
        limit = int(match.group(1))
    except (TypeError, ValueError):
        return

    # The message says which window it tripped. When it says neither, assume
    # per-second: that is the window a burst trips first, and clamping it also
    # holds the per-minute rate down.
    if _PER_MINUTE_HINT.search(emsg) and not _PER_SECOND_HINT.search(emsg):
        limiter.clamp_per_minute(limit)
    else:
        limiter.clamp_per_second(limit)
