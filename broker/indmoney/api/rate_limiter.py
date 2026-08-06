"""
Shared rate limiting and 429-retry helpers for all IndMoney (INDstocks) REST calls.

Documented limits (broker-api-docs/indstocks-api-docs/03-conventions.md):

    Order APIs        10 req/s   -            placement / modify / cancel
    Data APIs          5 req/s   100,000/day  instruments, historical
    Quote APIs         5 req/s   100,000/day  full / ltp / depth
    Non-Trading APIs  15 req/s   100,000/day  profile, funds, order & trade book
    Token generation   1 req/60s -            NOT paced here, see below

Pacing state MUST live in one module-level place that every importer shares.
Services construct a fresh ``BrokerData(auth_token)`` per request, so anything
kept on ``self`` is discarded on every call and paces nothing against
concurrent requests (the same lesson recorded in
broker/definedge/api/rate_limiter.py).

Before this module, each call site had its own local loop delay - 0.3s between
quote batches, 0.25s between historical chunks. Those hold *within* one call and
do nothing across threads: an option-chain load (an 82-symbol quote batch), a
position-book LTP refresh and an order placement can each look well-behaved
while collectively breaching 5/s. That is what produced the observed
``429 on /market/historical/1day`` retries, each costing a full second of
backoff plus a wasted request against the daily quota.

``POST /generate/token`` is deliberately NOT routed through here. It allows one
request per 60 seconds and 5 wrong TOTP codes trigger a 15-minute lockout, so
the right response to a throttle there is to fail loudly rather than sleep and
retry - see broker/indmoney/api/auth_api.py.
"""

import threading
import time
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from utils.logging import get_logger

logger = get_logger(__name__)

_IST = ZoneInfo("Asia/Kolkata")

# Documented ceiling in requests/second, per category.
_DOCUMENTED_RATE = {
    "order": 10.0,
    "data": 5.0,
    "quote": 5.0,
    "non_trading": 15.0,
}

# Pace at 80% of the documented ceiling, as broker/fyers/api/rate_limiter.py
# does (8 req/s against a documented 10). The headroom absorbs clock jitter and
# the fact that the broker measures a rolling window from its own clock, not
# ours - hitting the ceiling exactly is how you still collect a 429.
_HEADROOM = 0.8
_RATE_PER_SECOND = {k: v * _HEADROOM for k, v in _DOCUMENTED_RATE.items()}

# Daily request cap. Order APIs have no documented daily limit.
_DAILY_CAP = 100_000
_DAILY_CAPPED_BUCKETS = ("data", "quote", "non_trading")
_DAILY_WARN_FRACTION = 0.8

MAX_RETRIES = 3
BASE_BACKOFF = 1.0  # seconds; doubled per attempt when no Retry-After is sent
MAX_BACKOFF = 30.0

_lock = threading.Lock()
_next_free = {}  # bucket -> earliest monotonic time a request may go out
_daily = {}  # bucket -> (ist_date, count)
_warned = set()  # (bucket, ist_date, threshold) already logged

# Exact paths that place or change an order. Everything else under /order* is a
# read (order details, fills, books) and belongs to the Non-Trading bucket,
# which is what the docs mean by "Order History".
_ORDER_WRITE_PATHS = frozenset(
    {
        "/order",
        "/order/modify",
        "/order/cancel",
        "/smart/order",
        "/smart/order/modify",
        "/smart/order/cancel",
    }
)


def classify(url, method="GET"):
    """
    Map a request to its documented rate-limit category.

    Method matters: ``POST /order`` places an order (10/s) while ``GET /order``
    reads one back (15/s).
    """
    path = urlparse(url).path.rstrip("/") or "/"
    verb = str(method or "GET").upper()

    if path.startswith("/market/quotes"):
        return "quote"
    if path.startswith("/market/historical") or path.startswith("/market/instruments"):
        return "data"
    if verb == "POST" and path in _ORDER_WRITE_PATHS:
        return "order"
    # /margin is not categorised in the docs. Treat it as a Data API: it is the
    # stricter of the plausible buckets, and it is called in a loop (one request
    # per basket leg), which is exactly where under-throttling would bite.
    if path.startswith("/margin"):
        return "data"
    return "non_trading"


def apply_rate_limit(bucket):
    """
    Block until it is safe to issue another request in `bucket`.

    Each caller reserves the next slot under the module-level lock, so N
    concurrent threads queue behind one another instead of all seeing the same
    "last call" timestamp and firing together.

    What this guarantees: the *average* request rate stays at or below the paced
    rate. What it does not guarantee: an exact minimum gap between any two
    consecutive requests. Slots are reserved in order, but each caller then
    sleeps independently, so OS scheduling jitter can let one land slightly
    before the previous one's intended slot. Measured over 20 calls on 5
    threads, gaps dip to ~0.21s against a 0.25s target while the overall rate
    holds at 4.2/s.

    That wobble is what the 20% headroom absorbs - a 0.21s gap is 4.8 req/s
    instantaneous, still inside the documented 5/s ceiling. Enforcing an exact
    gap would mean holding a per-bucket lock across the sleep, which serialises
    the bucket and lets one slow request stall every other caller's pacing. The
    broker meters a rate, not individual gaps, so bounding the rate is the
    correct trade. broker/definedge, broker/dhan and broker/fyers all take the
    same approach.
    """
    rate = _RATE_PER_SECOND.get(bucket)
    if not rate:
        return
    min_interval = 1.0 / rate

    with _lock:
        now = time.monotonic()
        start = max(now, _next_free.get(bucket, 0.0))
        _next_free[bucket] = start + min_interval
        sleep_for = start - now

    # Sleep outside the lock so other threads can reserve their own slots.
    if sleep_for > 0:
        logger.debug(f"Rate limiting ({bucket}): sleeping {sleep_for:.3f}s before IndMoney call")
        time.sleep(sleep_for)


def _record_daily(bucket):
    """Count the request against the 100,000/day cap and warn as it is approached."""
    if bucket not in _DAILY_CAPPED_BUCKETS:
        return

    today = datetime.now(_IST).date()
    with _lock:
        day, count = _daily.get(bucket, (today, 0))
        if day != today:
            day, count = today, 0
        count += 1
        _daily[bucket] = (day, count)

    # Warn once per threshold per day rather than on every call past the line.
    threshold = None
    if count >= _DAILY_CAP:
        threshold = "cap"
    elif count >= _DAILY_CAP * _DAILY_WARN_FRACTION:
        threshold = "warn"
    if not threshold:
        return

    key = (bucket, today, threshold)
    with _lock:
        if key in _warned:
            return
        _warned.add(key)

    if threshold == "cap":
        logger.error(
            f"IndMoney {bucket} API daily cap reached: {count}/{_DAILY_CAP} requests "
            "today. Further calls are likely to be rejected until the IST day rolls over."
        )
    else:
        logger.warning(
            f"IndMoney {bucket} API daily usage at {count}/{_DAILY_CAP} requests today."
        )


def daily_usage():
    """Current per-bucket request counts for today (diagnostics)."""
    today = datetime.now(_IST).date()
    with _lock:
        return {
            bucket: (count if day == today else 0) for bucket, (day, count) in _daily.items()
        }


def retry_delay(headers, attempt):
    """How long to wait before retrying a 429, honouring Retry-After when sent."""
    retry_after = headers.get("Retry-After") or headers.get("retry-after")
    if retry_after:
        try:
            return min(max(float(retry_after), 0.05), MAX_BACKOFF)
        except (TypeError, ValueError):
            pass
    return min(BASE_BACKOFF * (2**attempt), MAX_BACKOFF)


def rate_limited_request(client, method, url, **kwargs):
    """
    Issue a paced IndMoney REST request, retrying on 429.

    Every IndMoney REST call should go through this helper so pacing and
    rate-limit retries are applied uniformly against one shared clock.

    Order writes are NEVER auto-retried. Placement, modification and
    cancellation are not idempotent and INDstocks offers no idempotency key, so
    a 429 that the broker had in fact accepted would be replayed as a second
    live order. Reconcile against the order book instead - the same rule the
    docs give for 5xx (14-errors: "Never blindly retry order placement").
    """
    bucket = classify(url, method)
    retries = 0 if bucket == "order" else MAX_RETRIES
    response = None

    for attempt in range(retries + 1):
        apply_rate_limit(bucket)
        _record_daily(bucket)
        response = client.request(str(method).upper(), url, **kwargs)

        if response.status_code != 429:
            break

        if attempt < retries:
            delay = retry_delay(response.headers, attempt)
            logger.warning(
                f"IndMoney rate limit hit (429) on {method} {url} [{bucket}]; "
                f"retry {attempt + 1}/{retries} in {delay:.2f}s"
            )
            time.sleep(delay)
        elif bucket == "order":
            logger.error(
                f"IndMoney rate limit hit (429) on {method} {url} [order]. NOT retried - "
                "an order write may have been accepted before the throttle. Check the "
                "order book before resubmitting."
            )

    if response is not None:
        # The rest of the codebase reads `.status`.
        response.status = response.status_code
    return response
