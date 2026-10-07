"""
Shared rate limiting and 429-retry helpers for all IIFL Capital API calls.

IIFL documents per-endpoint-CLASS limits rather than one shared global budget
(see broker-api-docs/iiflcapital-api-docs/15-rate-limits.md): Market Quotes,
Market Depth, and Historical Data are capped at 10 req/sec; Open Interest is
10 req/sec (20 req/sec once the session is registered for >10 orders/sec);
Order placement/modification/cancellation is 10 req/sec (20 registered);
Order Book/Trade Book/Cancel-All are 3 req/sec; Limits (funds) and
Pre-order Margin/SPAN Exposure are 10 req/sec (20 registered). OpenAlgo does
not currently track a user's registration tier, so this module paces every
IIFL call against a single shared, conservative floor -- the tightest
documented cap (10 req/sec) with headroom, rather than maximizing per-category
throughput. A future refinement could split data/order/funds into separate
limiter instances if that throughput ceiling becomes a real constraint; for
the bug this fixes (silent OI data loss from an unthrottled concurrent burst)
one shared limiter is the correct, low-risk fix.

`broker/iiflcapital/api/data.py`, `order_api.py`, and `funds.py` each build
their own httpx request internally rather than sharing one call site, and
BrokerData/order_api helpers are constructed fresh per request (see
services/option_chain_service.py, services/oi_tracker_service.py, etc.), so
any rate-limit state kept on an instance would reset away on every call and
never actually pace anything against concurrent requests. `_fetch_openinterest_map`
in data.py fans a 60-leg option chain out across up to 32 concurrent threads --
without a process-wide pacer that burst blows straight through IIFL's 10/sec
Open Interest cap, and `_fetch_openinterest` swallows any resulting failure
and returns 0, so throttled legs silently show as zero OI instead of erroring
out. Keeping pacing state at module level here means every caller across all
three files shares the same clock regardless of how many instances or threads
are in flight at once.

Bounded waits under the gthread worker. Under eventlet and the dev server a
caller waits for its slot however far back in the queue it is, exactly as
before. Under gthread each waiting caller holds one of a fixed number of request
threads, so two changes apply there and only there:

* a caller whose slot is further away than
  ``utils.broker_backpressure.max_queue_wait(kind)`` is refused with
  BrokerBusyError, and books nothing, so it delays nobody after it; and
* order placement, modification and cancellation (``kind="order"``) are paced
  on a clock of their own, as IIFL documents a separate 10 req/sec cap for
  them, so an order never waits behind an option chain's open interest fan-out
  and is never refused because of one.
"""

import math
import threading
import time

from utils import runtime
from utils.broker_backpressure import BrokerBusyError, max_queue_wait
from utils.logging import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()
_last_call_time = 0.0
# Order writes' own clock. Used only under the gthread worker; everywhere else
# every call shares _last_call_time, as it always has.
_last_order_call_time = 0.0

# Tightest documented cap across categories is 10 req/sec; pace at ~8 req/sec
# (0.125s) to leave headroom for clock jitter and for data/order/funds calls
# sharing the same process-wide pacer concurrently.
MIN_INTERVAL = 0.125

MAX_RETRIES = 3
BASE_BACKOFF = 1.0  # seconds; exponential fallback when no Retry-After header: 1, 2, 4


def apply_rate_limit(kind: str = "data"):
    """Block the calling thread until it is safe to make another IIFL Capital API call.

    Shared process-wide (module-level lock + timestamp) so every caller
    across broker.iiflcapital.api paces against the same clock, regardless
    of how many separate BrokerData/order_api/funds calls -- or threads
    inside a single ThreadPoolExecutor fanout -- are in flight at once.

    Args:
        kind: ``"order"`` for order placement, modification and cancellation,
            ``"data"`` for everything else. It only matters under the gthread
            worker (see the module docstring).

    Raises:
        BrokerBusyError: Only under the gthread worker, when the caller's slot
            is further away than the ceiling for ``kind``. Nothing is booked.
    """
    global _last_call_time, _last_order_call_time
    ceiling = max_queue_wait(kind)
    own_clock = kind == "order" and runtime.gthread_active()
    with _lock:
        now = time.time()
        last = _last_order_call_time if own_clock else _last_call_time
        elapsed = now - last
        sleep_time = MIN_INTERVAL - elapsed if elapsed < MIN_INTERVAL else 0
        refused = ceiling is not None and sleep_time > ceiling
        if not refused:
            if own_clock:
                _last_order_call_time = now + sleep_time
            else:
                _last_call_time = now + sleep_time

    if refused:
        logger.warning(
            f"IIFL Capital pacing ({kind}) refused a request whose turn was "
            f"{sleep_time:.1f}s away (limit {ceiling:.0f}s under gthread)"
        )
        raise busy_error(sleep_time, kind)

    if sleep_time > 0:
        time.sleep(sleep_time)


def busy_error(wait: float, kind: str) -> BrokerBusyError:
    """The refusal for a request whose turn would come ``wait`` seconds from now."""
    what = "This order was not sent" if kind == "order" else "This request was not sent"
    seconds = max(1, math.ceil(wait))
    return BrokerBusyError(
        "IIFL Capital allows only a few requests each second, and OpenAlgo already "
        f"has more waiting than it can send in time. {what}. Try again in about "
        f"{seconds} seconds.",
        retry_after=wait,
    )


def retry_delay_from_headers(headers, attempt):
    """Compute how long to wait before retrying a 429.

    IIFL's docs (checked 12-error-codes.md, 02-request-response-structure.md,
    16-faq.md) do not document a specific rate-limit-exceeded response body
    or header, so this prefers the standard `Retry-After` header (universal
    HTTP convention) when the broker sends one, and otherwise falls back to
    exponential backoff.
    """
    retry_after = headers.get("Retry-After") or headers.get("retry-after")
    if retry_after:
        try:
            return max(float(retry_after), 0.05)
        except ValueError:
            pass

    return BASE_BACKOFF * (2**attempt)


def is_rate_limited(status_code: int, message: str = "") -> bool:
    """Detect a rate-limit rejection from an IIFL Capital response.

    HTTP 429 is the primary, reliable signal. As a defensive fallback (IIFL
    has no documented rate-limit error code), also treat a response message
    containing a rate-limit or retry hint as retryable -- this substring
    match covers IIFL's generic EC003 "Something went wrong, please try
    after some time" error, the closest documented analogue.

    Retryable means a read may be retried. An order write that gets this
    answer is never resent (see order_api._request): EC003 can arrive after
    IIFL accepted the order.
    """
    if status_code == 429:
        return True

    text = (message or "").lower()
    return any(
        hint in text
        for hint in ("rate limit", "too many request", "try after some time")
    )
