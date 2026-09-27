"""Shared rate limiting and retry helpers for all TradeSmart (Noren) API calls.

Two budgets, because quotes and everything else are metered differently.

**Quotes** (``/GetQuotes``) are allowed 100 requests per second with no
per-minute ceiling, so they get their own bucket and are paced on the
per-second window alone.

**Everything else** -- orders, funds, margin, history -- shares ONE per-user
budget with two rolling windows: 10 requests per second and 120 requests per
minute. The backend rejects the offender with ``stat=Not_Ok`` and an emsg
naming the breached window, e.g.::

    Invalid Input :  Order Recieved 11 in a current second exceeds Limit 10 for user
    Invalid Input :  Order Recieved 121 in a current minute exceeds Limit 120 for user

State is module level, exactly as in ``broker.fyers.api.rate_limiter`` and for
the same reason: services construct a fresh ``BrokerData(auth_token)`` per
request (see ``services/option_chain_service.py``,
``services/oi_tracker_service.py``), so any pacing state kept on ``self`` is
discarded on every call and paces nothing against concurrent requests.

Each gate is burst-friendly, modelled on ``broker.flattrade.api.data``: it
reserves the earliest slot that satisfies its rolling window(s) rather than
spacing every call by a fixed interval, so a batch goes out at once and only
the call past the ceiling waits. The slot is reserved under the lock and slept
for outside it -- holding a lock across ``time.sleep`` would serialise every
waiter behind the sleeper and turn the allowance back into a queue.
"""

import threading
import time
from collections import deque

# Broker ceilings for the general budget are 10/sec and 120/min per user. We run
# under both as margin for clock skew between our rolling windows and however
# Noren measures theirs, and because order/fund/margin calls from other modules
# share the same quota.
TRADESMART_MAX_PER_SECOND = 8
TRADESMART_MAX_PER_MINUTE = 110

# Quotes are metered separately at 100/sec with no per-minute ceiling. Same
# clock-skew margin as above; ``None`` disables the per-minute window entirely.
TRADESMART_QUOTE_MAX_PER_SECOND = 90
TRADESMART_QUOTE_MAX_PER_MINUTE = None

# Endpoints billed against the quote budget rather than the general one.
QUOTE_ENDPOINTS = frozenset({"/GetQuotes"})

MAX_RETRIES = 3
BASE_BACKOFF = 2.0  # seconds; exponential when the broker reports a limit hit

_lock = threading.Lock()
_reserved_call_times: deque = deque()

_quote_lock = threading.Lock()
_reserved_quote_times: deque = deque()


def _reserve_slot(lock, reserved, max_per_second, max_per_minute) -> float:
    """Reserve the earliest slot satisfying the bucket's rolling window(s).

    Returns the seconds the caller must sleep before issuing its request.

    The deque holds reserved timestamps in non-decreasing order (each new
    reservation is >= the previous by construction). The earliest permissible
    slot is:

      - now, if neither window is full at that instant;
      - 1s after the Nth-most-recent reservation when the per-second window is
        full (that entry must age out of the rolling second first);
      - 60s after the Mth-most-recent reservation when the per-minute window is
        full;

    whichever is latest. ``max_per_minute=None`` means the bucket has no
    per-minute ceiling, in which case only the per-second window constrains the
    slot and entries older than a second are purged.

    Args:
        lock: the bucket's lock, held only while reserving (never across sleep).
        reserved: the bucket's deque of reserved timestamps.
        max_per_second: per-second ceiling.
        max_per_minute: per-minute ceiling, or ``None`` for no such window.
    """
    # Entries older than the widest window can no longer constrain any future
    # slot, so that horizon is how far back the deque needs to reach.
    horizon = 60.0 if max_per_minute is not None else 1.0

    with lock:
        now = time.time()
        while reserved and reserved[0] <= now - horizon:
            reserved.popleft()

        slot = now
        if len(reserved) >= max_per_second:
            slot = max(slot, reserved[-max_per_second] + 1.0)
        if max_per_minute is not None and len(reserved) >= max_per_minute:
            slot = max(slot, reserved[-max_per_minute] + 60.0)

        reserved.append(slot)
        return slot - now


def apply_rate_limit(endpoint: str | None = None) -> None:
    """Block until it is safe to issue another TradeSmart call.

    Args:
        endpoint: Noren path, e.g. ``"/GetQuotes"``. Quote endpoints are paced
            against their own 100/sec budget; every other endpoint bills
            against the shared 10/sec + 120/min per-user budget.
    """
    if endpoint in QUOTE_ENDPOINTS:
        sleep_time = _reserve_slot(
            _quote_lock,
            _reserved_quote_times,
            TRADESMART_QUOTE_MAX_PER_SECOND,
            TRADESMART_QUOTE_MAX_PER_MINUTE,
        )
    else:
        sleep_time = _reserve_slot(
            _lock,
            _reserved_call_times,
            TRADESMART_MAX_PER_SECOND,
            TRADESMART_MAX_PER_MINUTE,
        )

    if sleep_time > 0:
        time.sleep(sleep_time)


def is_rate_limit_error(response) -> bool:
    """Whether TradeSmart is reporting a rate-limit rejection.

    Noren answers with ``stat=Not_Ok`` and an emsg naming the breached limit,
    e.g. "Invalid Input :  Order Recieved 141 in a current minute exceeds Limit
    120 for user". Matched on the phrase rather than the number so a changed
    ceiling is still recognised.
    """
    if not isinstance(response, dict):
        return False
    if response.get("stat") != "Not_Ok":
        return False
    emsg = response.get("emsg", "") or ""
    return "exceeds limit" in emsg.lower()


def retry_delay(attempt: int) -> float:
    """Backoff before retrying a rate-limited call: 2s, 4s, 8s."""
    return BASE_BACKOFF * (2**attempt)
