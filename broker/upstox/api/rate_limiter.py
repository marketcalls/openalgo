"""Shared request pacing and 429 handling for every Upstox REST entry point.

Upstox publishes two independent budgets, each governed by THREE simultaneous
rolling windows (broker-api-docs/upstox-api-docs/04-rate-limits.md):

    Order placement APIs   10 req/sec    500 req/min    2000 req/30min
    (Place, Modify, Cancel, Multi Order, GTT Order; regular algos)

    Standard APIs          50 req/sec    500 req/min    2000 req/30min
    (holdings, positions, funds, historical candles, quotes, margin, ...)

That is Dhan's shape (independent per-category budgets) and Flattrade's shape
(a rolling window per published ceiling) at the same time, so this module is
both: a limiter per category, each holding a deque of reserved slots and each
honouring all three of its windows at once.

Payout and Apply-IPO carry their own, much tighter tables (Payout Request is
10/min with no per-second allowance; Apply IPO is 1/sec). OpenAlgo calls
neither endpoint family, so they are deliberately omitted rather than folded
into the standard budget -- doing that would drag every quote fetch down to a
withdrawal endpoint's ceiling.

Why two categories and not one shared pacer: the per-second caps differ 5x. A
single pacer set at 10/sec would throttle a 500-symbol option-chain fetch to a
fifth of what Upstox actually allows it, and one set at 50/sec would blow
straight through the order cap the moment cancel_all_orders_api loops.

Why three windows and not the lowest average: 2000 requests per 1800 seconds
averages ~1.1 req/sec. Collapsing the windows into that average is exactly the
mistake that made Flattrade's history fetch take ~25s for 45 symbols (issue
#1663) -- it forbids bursting entirely, when Upstox is happy to serve a burst
at the per-second cap so long as the longer budgets are respected. Reserving
the latest slot that satisfies all three windows permits the burst and still
holds the sustained rate down.

State is module level, not on BrokerData. Services build a fresh
``BrokerData(auth_token)`` per request (services/option_chain_service.py,
services/oi_tracker_service.py, ...), so pacing state kept on an instance is
reset away on every call and paces nothing at all against concurrent requests.
That was a real production bug on Fyers. Every Upstox caller -- data.py,
order_api.py, gtt_api.py, funds.py, margin_api.py -- imports the same two
limiters here, which is the only way a shared budget can actually be shared.

Three outbound calls under broker/upstox/ are deliberately NOT paced, so the
omissions are a decision on record rather than a gap:

  - api/auth_api.py POST /v2/login/authorization/token. A login endpoint, in
    neither published table, issued once per day when the daily token is
    exchanged. Pacing it would only add latency to the one call a user waits on.
  - streaming/upstox_client.py and streaming/upstox_order_adapter.py fetch a
    websocket authorize URL on every (re)connect. Under gunicorn+eventlet the
    websocket proxy is a separate CHILD PROCESS (see CLAUDE.md), so importing
    these limiters there would create a second, independent set of counters --
    the appearance of sharing with none of the substance. One handshake per
    connect is far below any of the six windows anyway.
  - database/master_contract_db.py downloads
    assets.upstox.com/market-quote/instruments/exchange/complete.json.gz --
    a static file on a different host, not an API endpoint.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque

from utils.logging import get_logger

logger = get_logger(__name__)

# Longest window Upstox publishes. Reserved slots older than this can no longer
# constrain any future slot, so they are purged on every reservation -- which is
# what keeps the deque bounded (see SlidingWindowLimiter.reserve).
LONGEST_WINDOW = 1800.0


def _env_int(name: str, default: int, ceiling: int) -> int:
    """Read a positive int from the environment, bounded by `ceiling`.

    `ceiling` is the highest figure Upstox publishes for that window
    (04-rate-limits.md). The override exists for the SEBI-registered algo tier,
    which the same table grants 50 orders/sec instead of 10; OpenAlgo does not
    track a user's registration status, so an operator who holds that
    registration opts in explicitly. Nothing legitimate sits above the
    published table, and an override that does is a typo that would silently
    disable the pacing this module exists to provide. Clamp rather than trust.
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
            f"{name}={value} is above Upstox's published ceiling of {ceiling}; "
            f"using {ceiling}."
        )
        return ceiling
    return value


class SlidingWindowLimiter:
    """Triple rolling-window limiter: bursts to the per-second cap, hard-capped
    on all three windows.

    Reservation happens inside the lock; sleeping is the caller's job, outside
    the lock, so concurrent green threads queue without serializing on it.

    The deque holds reserved call timestamps in non-decreasing order (each new
    reservation is >= the previous by construction: a full window pushes the new
    slot past entries the previous reservation also sat behind). The earliest
    permissible slot is:

      - now, if no window is full at that instant;
      - 1s after the Nth-most-recent reservation when the per-second window is
        full (that entry must age out of the rolling second first);
      - 60s after the Mth-most-recent reservation when the per-minute window is
        full;
      - 1800s after the Kth-most-recent reservation when the 30-minute window
        is full;

    whichever is latest.

    Memory: purging runs on every reservation, before anything else, so the
    deque can never hold more than the 30-minute cap plus whatever has been
    reserved into the future -- a few thousand floats at the published 2000,
    and it shrinks again the moment traffic stops. There is no path that
    appends without first purging.
    """

    def __init__(
        self,
        name: str,
        max_per_second: int,
        max_per_minute: int,
        max_per_30min: int,
    ):
        self.name = name
        self.max_per_second = max_per_second
        self.max_per_minute = max_per_minute
        self.max_per_30min = max_per_30min
        self._lock = threading.Lock()
        self._reserved: deque[float] = deque()

    @property
    def windows(self) -> tuple[tuple[int, float], ...]:
        """(cap, span) for each published window, tightest span first."""
        return (
            (self.max_per_second, 1.0),
            (self.max_per_minute, 60.0),
            (self.max_per_30min, LONGEST_WINDOW),
        )

    def reserve(self) -> float:
        """Reserve the earliest slot satisfying all three windows.

        Returns the seconds the caller must sleep before issuing its request.
        """
        with self._lock:
            now = time.time()
            # Purge first, always: entries older than the longest window cannot
            # constrain any future slot, and this is what bounds the deque.
            while self._reserved and self._reserved[0] <= now - LONGEST_WINDOW:
                self._reserved.popleft()

            slot = now
            for cap, span in self.windows:
                if len(self._reserved) >= cap:
                    slot = max(slot, self._reserved[-cap] + span)

            self._reserved.append(slot)
            return slot - now

    def acquire(self) -> None:
        """Block until this caller's reserved slot arrives.

        ``time.sleep`` is deliberate: under gunicorn+eventlet the stdlib is
        monkey-patched, so this yields the hub to other green threads rather
        than blocking the single worker. The sleep is outside the lock.
        """
        sleep_time = self.reserve()
        if sleep_time > 0:
            logger.debug(
                f"Rate limiting ({self.name}): sleeping {sleep_time:.3f}s "
                "before Upstox API call"
            )
            time.sleep(sleep_time)

    def depth(self) -> int:
        """Number of reservations currently tracked. Diagnostics and tests."""
        with self._lock:
            return len(self._reserved)


# Headroom, and why these numbers.
#
# The per-second window gets the widest margin (~20% on orders, 10% on
# standard) because it is the window a burst trips first and the one where
# skew between our time.time() and however Upstox aligns its own bucket
# boundaries actually matters: a burst landing either side of a second
# boundary can be counted twice against one bucket. Fyers paces 8 against 10
# for the same reason; Flattrade 38 against 40.
#
# The minute and 30-minute windows get 5%. They are long enough that clock
# skew is noise, and they are the windows that bound sustained throughput --
# the 30-minute budget already averages only ~1.1 req/sec, so cutting it
# harder buys nothing and costs real work. 5% is enough to absorb the
# streaming/order-update poller and any other module drawing on the same
# account budget.
ORDER_LIMITER = SlidingWindowLimiter(
    "order",
    max_per_second=_env_int("UPSTOX_ORDER_MAX_PER_SECOND", 8, ceiling=50),
    max_per_minute=_env_int("UPSTOX_ORDER_MAX_PER_MINUTE", 475, ceiling=500),
    max_per_30min=_env_int("UPSTOX_ORDER_MAX_PER_30MIN", 1900, ceiling=2000),
)

STANDARD_LIMITER = SlidingWindowLimiter(
    "standard",
    max_per_second=_env_int("UPSTOX_MAX_PER_SECOND", 45, ceiling=50),
    max_per_minute=_env_int("UPSTOX_MAX_PER_MINUTE", 475, ceiling=500),
    max_per_30min=_env_int("UPSTOX_MAX_PER_30MIN", 1900, ceiling=2000),
)

_LIMITERS = {"order": ORDER_LIMITER, "standard": STANDARD_LIMITER}


def apply_rate_limit(category: str = "standard") -> None:
    """Block the caller until it is safe to issue an Upstox request.

    ``category`` is "order" for Place/Modify/Cancel/Multi-Order/GTT and
    "standard" for everything else -- including the order book, trade book,
    positions and holdings reads, which are Standard APIs despite living in
    order_api.py. An unknown category falls back to the standard budget with a
    warning rather than silently going unpaced.
    """
    limiter = _LIMITERS.get(category)
    if limiter is None:
        logger.warning(f"Unknown Upstox rate-limit category {category!r}; using standard")
        limiter = STANDARD_LIMITER
    limiter.acquire()


MAX_RETRIES = 3
BASE_BACKOFF = 1.0  # seconds; exponential fallback when no Retry-After header: 1, 2, 4

# Upstox's documented rate-limit application error code (03b-error-codes.md).
RATE_LIMIT_ERROR_CODE = "UDAPI10005"


def retry_delay_from_headers(headers, attempt: int) -> float:
    """Compute how long to wait before retrying a 429.

    Checked 04-rate-limits.md, 03b-error-codes.md, 03a-response-structure.md
    and 03c-request-structure.md: Upstox documents the rate-limit *rejection*
    (HTTP 429, "You're requesting too many resources! Slow down!", plus the
    application error code UDAPI10005 "Rate limit threshold exceeded") but
    documents no ``Retry-After`` header and no rate-limit-specific response
    body beyond the standard ``errors[]`` envelope. There is no documented
    per-window hint either, so a rejection does not say which of the three
    windows was tripped.

    That absence is the useful finding: this reads the standard ``Retry-After``
    header anyway (universal HTTP convention, and free if Upstox ever starts
    sending it) and otherwise falls back to exponential backoff.
    """
    retry_after = None
    if headers is not None:
        try:
            retry_after = headers.get("Retry-After") or headers.get("retry-after")
        except AttributeError:
            retry_after = None
    if retry_after:
        try:
            return max(float(retry_after), 0.05)
        except (TypeError, ValueError):
            pass

    return BASE_BACKOFF * (2**attempt)


def is_rate_limited(status_code, body=None) -> bool:
    """Detect a rate-limit rejection from an Upstox response.

    HTTP 429 is the primary signal. Upstox also carries UDAPI10005 in its
    ``errors[]`` envelope, and data.py's ``get_api_response`` returns the
    parsed body without ever inspecting the status line, so the body is
    checked too -- otherwise a throttled quote fetch would be indistinguishable
    from any other error and would be retried by nobody.
    """
    if status_code == 429:
        return True

    if not isinstance(body, dict):
        return False
    if body.get("status") != "error":
        return False
    for err in body.get("errors") or []:
        if not isinstance(err, dict):
            continue
        code = err.get("error_code") or err.get("errorCode") or ""
        if str(code).upper() == RATE_LIMIT_ERROR_CODE:
            return True
    return False
