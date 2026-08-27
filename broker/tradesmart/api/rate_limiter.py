"""Shared rate limiting and retry helpers for all TradeSmart (Noren) API calls.

TradeSmart bills every data call against ONE per-user budget with two rolling
windows: 10 requests per second and 120 requests per minute. The backend
rejects the offender with ``stat=Not_Ok`` and an emsg naming the breached
window, e.g.::

    Invalid Input :  Order Recieved 11 in a current second exceeds Limit 10 for user
    Invalid Input :  Order Recieved 121 in a current minute exceeds Limit 120 for user

Both of those were observed on ``/GetQuotes`` in the same option-chain request,
which is why quotes are NOT exempt from the per-minute window and do NOT get a
separate budget from history: the counters are per *user*, not per endpoint, so
one shared gate is the only thing that can keep the account under both ceilings.

State is module level, exactly as in ``broker.fyers.api.rate_limiter`` and for
the same reason: services construct a fresh ``BrokerData(auth_token)`` per
request (see ``services/option_chain_service.py``,
``services/oi_tracker_service.py``), so any pacing state kept on ``self`` is
discarded on every call and paces nothing against concurrent requests.

The gate is burst-friendly, modelled on ``broker.flattrade.api.data``: it
reserves the earliest slot that satisfies both rolling windows rather than
spacing every call by a fixed interval, so a 10-symbol batch goes out at once
and only the 11th waits. The slot is reserved under the lock and slept for
outside it -- holding a lock across ``time.sleep`` would serialise every waiter
behind the sleeper and turn a 10/sec allowance back into a queue.
"""

import threading
import time
from collections import deque

# Broker ceilings are 10/sec and 120/min per user. We run under both as margin
# for clock skew between our rolling windows and however Noren measures theirs,
# and because order/fund/margin calls from other modules share the same quota.
TRADESMART_MAX_PER_SECOND = 8
TRADESMART_MAX_PER_MINUTE = 110

MAX_RETRIES = 3
BASE_BACKOFF = 2.0  # seconds; exponential when the broker reports a limit hit

_lock = threading.Lock()
_reserved_call_times: deque = deque()


def _reserve_slot() -> float:
    """Reserve the earliest slot satisfying both rolling windows.

    Returns the seconds the caller must sleep before issuing its request.

    The deque holds reserved timestamps in non-decreasing order (each new
    reservation is >= the previous by construction). The earliest permissible
    slot is:

      - now, if neither window is full at that instant;
      - 1s after the Nth-most-recent reservation when the per-second window is
        full (that entry must age out of the rolling second first);
      - 60s after the Mth-most-recent reservation when the per-minute window is
        full;

    whichever is latest. Entries older than 60s can no longer constrain any
    future slot and are purged.
    """
    with _lock:
        now = time.time()
        while _reserved_call_times and _reserved_call_times[0] <= now - 60.0:
            _reserved_call_times.popleft()

        slot = now
        if len(_reserved_call_times) >= TRADESMART_MAX_PER_SECOND:
            slot = max(slot, _reserved_call_times[-TRADESMART_MAX_PER_SECOND] + 1.0)
        if len(_reserved_call_times) >= TRADESMART_MAX_PER_MINUTE:
            slot = max(slot, _reserved_call_times[-TRADESMART_MAX_PER_MINUTE] + 60.0)

        _reserved_call_times.append(slot)
        return slot - now


def apply_rate_limit(endpoint: str | None = None) -> None:
    """Block until it is safe to issue another TradeSmart call.

    Args:
        endpoint: Noren path, e.g. ``"/GetQuotes"``. Accepted for call-site
            readability and logging only -- every endpoint bills against the
            same per-user budget, so it does not change the pacing.
    """
    sleep_time = _reserve_slot()
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
