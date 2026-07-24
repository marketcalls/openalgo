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
"""

import threading
import time

_lock = threading.Lock()
_last_call_time = 0.0

# Tightest documented cap across categories is 10 req/sec; pace at ~8 req/sec
# (0.125s) to leave headroom for clock jitter and for data/order/funds calls
# sharing the same process-wide pacer concurrently.
MIN_INTERVAL = 0.125

MAX_RETRIES = 3
BASE_BACKOFF = 1.0  # seconds; exponential fallback when no Retry-After header: 1, 2, 4


def apply_rate_limit():
    """Block the calling thread until it is safe to make another IIFL Capital API call.

    Shared process-wide (module-level lock + timestamp) so every caller
    across broker.iiflcapital.api paces against the same clock, regardless
    of how many separate BrokerData/order_api/funds calls -- or threads
    inside a single ThreadPoolExecutor fanout -- are in flight at once.
    """
    global _last_call_time
    with _lock:
        now = time.time()
        elapsed = now - _last_call_time
        sleep_time = MIN_INTERVAL - elapsed if elapsed < MIN_INTERVAL else 0
        _last_call_time = now + sleep_time

    if sleep_time > 0:
        time.sleep(sleep_time)


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
    """
    if status_code == 429:
        return True

    text = (message or "").lower()
    return any(
        hint in text
        for hint in ("rate limit", "too many request", "try after some time")
    )
