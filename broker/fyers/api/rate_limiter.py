"""
Shared rate limiting and 429-retry helpers for all Fyers API calls.

Fyers enforces a single global cap per API key across every REST endpoint --
order, data, quotes, depth, history, funds: 10 requests/second, 200/minute,
100000/day (see fyers-api-docs/FYERS_API_v3.md -> "Rate Limits"). Unlike Dhan,
which has independent per-endpoint-class limits (charts vs marketfeed), Fyers'
10 req/sec budget is shared process-wide, so pacing state MUST live in one
place that every module importing it sees -- not per BrokerData instance.

Services create a fresh BrokerData(auth_token) per request (see
services/option_chain_service.py, services/oi_tracker_service.py, etc.), so
any rate-limit state kept on `self` is reset away on every call and never
actually paces anything against concurrent requests. That was the root cause
of option-chain/depth bursts (many individual /data/depth calls for OI)
routinely exceeding the real 10 req/sec cap and getting HTTP 429'd.
"""

import threading
import time

from utils.broker_backpressure import BrokerBusyError, cap_server_delay, check_queue_wait

_lock = threading.Lock()
_last_call_time = 0.0

# Documented cap is 10 req/sec; pace at ~8 req/sec (0.125s) to leave headroom
# for clock jitter and for order/fund/margin calls sharing the same quota
# from other modules running concurrently in the same process.
MIN_INTERVAL = 0.125

MAX_RETRIES = 3
BASE_BACKOFF = 1.0  # seconds; exponential fallback when no Retry-After header: 1, 2, 4


def apply_rate_limit(kind="data"):
    """Block the calling thread until it is safe to make another Fyers API call.

    Shared process-wide (module-level lock + timestamp) so every caller
    across broker.fyers.api paces against the same clock, regardless of how
    many separate BrokerData/order_api calls are in flight at once.

    Every caller books the slot after the last one, so a burst queues without
    limit. Under the gthread worker each queued caller holds a request thread,
    so one whose slot is further away than
    ``utils.broker_backpressure.max_queue_wait(kind)`` is refused before it
    books anything. Under eventlet and the dev server there is no bound.

    Args:
        kind: ``"data"``, or ``"order"`` for order placement and changes.

    Raises:
        BrokerBusyError: Under gthread, when the slot is too far away.
    """
    global _last_call_time
    with _lock:
        now = time.time()
        elapsed = now - _last_call_time
        sleep_time = MIN_INTERVAL - elapsed if elapsed < MIN_INTERVAL else 0
        check_queue_wait(sleep_time, kind)
        _last_call_time = now + sleep_time

    if sleep_time > 0:
        time.sleep(sleep_time)


def retry_delay_from_headers(headers, attempt, kind="data"):
    """Compute how long to wait before retrying a 429.

    Fyers documents both `Retry-After` (seconds) and `X-Retry-After-Ms`
    (milliseconds) response headers on rate-limited requests -- prefer those
    over a blind exponential guess when present.

    The broker's delay is honoured as asked, except under the gthread worker
    when it is longer than ``max_queue_wait(kind)``: sleeping it there would
    hold a request thread for as long as the broker likes (three retries of a
    60 second Retry-After is three minutes), so the retry is abandoned instead.

    Raises:
        BrokerBusyError: Under gthread, when the broker asks for a longer wait
            than the bound.
    """
    delay = _requested_delay(headers, attempt)
    if cap_server_delay(delay, kind) is None:
        raise BrokerBusyError(
            "Fyers asked OpenAlgo to slow down and wait longer than a request "
            "can be held. This request was not retried. Try again in a minute.",
            retry_after=delay,
        )
    return delay


def _requested_delay(headers, attempt):
    retry_after_ms = headers.get("X-Retry-After-Ms") or headers.get("x-retry-after-ms")
    if retry_after_ms:
        try:
            return max(float(retry_after_ms) / 1000.0, 0.05)
        except ValueError:
            pass

    retry_after = headers.get("Retry-After") or headers.get("retry-after")
    if retry_after:
        try:
            return max(float(retry_after), 0.05)
        except ValueError:
            pass

    return BASE_BACKOFF * (2**attempt)
