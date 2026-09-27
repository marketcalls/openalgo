"""Shared rate limiting for AliceBlue REST calls.

AliceBlue publishes a concrete limit (17-rate-limits.md):

    Orders - NOT LIMITED. Placing a new order, Modifying an existing order,
    square off positions and Cancelling an order are all not limited.

    All other requests - Limited to 1800 requests per 15 minutes. This limit
    will be reset every 15 minutes to 1800 again.

That is a *quota over a window*, not a per-second cap, so this is a sliding
window rather than the fixed MIN_INTERVAL pacer used for brokers that throttle
bursts (compare broker/definedge/api/rate_limiter.py). 1800/900s averages 2
req/sec, but a burst of 100 quotes is perfectly legal as long as the trailing
15 minutes stays under budget - pacing everything to 0.5s apart would make an
option chain artificially slow for no reason the broker asked for.

Orders deliberately bypass this. Throttling an exit because a dashboard was
polling would be far worse than any quota error, and the broker does not limit
them anyway.

State is module-level because services construct a fresh BrokerData per
request, so anything kept on `self` paces nothing - the same lesson recorded in
the definedge and fyers limiters, and the reason the market-data WebSocket was
being rebuilt on every call before e47c5fdb2.
"""

import threading
import time
from collections import deque

from utils.logging import get_logger

logger = get_logger(__name__)

#: Straight from the broker's published limits.
WINDOW_SECONDS = 15 * 60
MAX_REQUESTS_PER_WINDOW = 1800

#: Leave a little of the budget unspent. The broker's window boundary and ours
#: will not line up exactly, and being throttled mid-session is worse than
#: being marginally slower.
SAFETY_MARGIN = 50

_lock = threading.Lock()
_request_times: deque = deque()


def _prune(now: float) -> None:
    """Drop timestamps that have fallen out of the trailing window."""
    cutoff = now - WINDOW_SECONDS
    while _request_times and _request_times[0] <= cutoff:
        _request_times.popleft()


def apply_rate_limit(is_order: bool = False) -> float:
    """Block until another non-order request fits inside the window.

    Returns the number of seconds slept, for logging and tests.

    Orders return immediately: the broker does not limit them, and delaying an
    exit to protect a quota would be the wrong trade.
    """
    if is_order:
        return 0.0

    budget = MAX_REQUESTS_PER_WINDOW - SAFETY_MARGIN

    with _lock:
        now = time.monotonic()
        _prune(now)

        if len(_request_times) < budget:
            _request_times.append(now)
            return 0.0

        # Window is full: wait for the oldest request to age out, then take
        # its place. Computed under the lock so concurrent callers queue in
        # order instead of all waking to the same slot.
        wait = (_request_times[0] + WINDOW_SECONDS) - now
        wait = max(wait, 0.0)
        _request_times.popleft()
        _request_times.append(now + wait)

    logger.warning(
        f"AliceBlue rate limit reached ({budget} requests in {WINDOW_SECONDS}s); "
        f"waiting {wait:.1f}s. Reduce polling frequency if this recurs."
    )
    time.sleep(wait)
    return wait


def remaining_quota() -> int:
    """Requests still available in the current trailing window."""
    with _lock:
        _prune(time.monotonic())
        return max(0, (MAX_REQUESTS_PER_WINDOW - SAFETY_MARGIN) - len(_request_times))


def reset() -> None:
    """Clear the window. For tests and for a fresh broker session."""
    with _lock:
        _request_times.clear()
