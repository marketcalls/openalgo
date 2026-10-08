"""
Shared rate limiting and 429-retry helpers for all Groww API calls.

Groww limits requests by API type, and APIs of one type share the limit
(broker-api-docs/groww-api-docs/01-introduction.md, "Rate limits"):

    Orders          create, modify, cancel order               10/s   250/min
    Live Data       quote, LTP, OHLC                            10/s   300/min
    Non Trading     order status/list, trades, positions,       20/s   500/min
                    holdings, margin
    Authentication  generate access token                        5/s    30/min

Historical candles are not in that table. Bursts of about ten requests were
refused with HTTP 429 on 2026-10-07, so history is paced on its own at one
request a second.

Like Dhan, each type has its own clock, so a burst of quotes never delays an
order. Like Fyers, the clocks are module level: services build a fresh
BrokerData per request, so pacing state kept on an instance would pace
nothing. Calls are spaced by the per-minute figure, which also keeps them
under the per-second one.
"""

import threading
import time
from email.utils import parsedate_to_datetime

from utils.broker_backpressure import BrokerBusyError, cap_server_delay, check_queue_wait

# Seconds between two calls of one type: 60 / per-minute limit.
MIN_INTERVAL = {
    "order": 60 / 250,
    "live": 60 / 300,
    "non_trading": 60 / 500,
    "auth": 60 / 30,
    "history": 1.0,
}

MAX_RETRIES = 3
BASE_BACKOFF = 1.0  # seconds; exponential fallback when Groww gives no Retry-After: 1, 2, 4

_lock = threading.Lock()
# time.monotonic() of each type's last booked slot; only deltas are used, so a
# wall-clock (NTP) step cannot stall callers or let a burst through
_last_call_time = dict.fromkeys(MIN_INTERVAL, 0.0)


def _queue_kind(category):
    """The utils.broker_backpressure kind: orders get the order bound."""
    return "order" if category == "order" else "data"


def apply_rate_limit(category):
    """Block until another call of ``category`` may be made.

    Every caller books the slot after the last one, so a burst queues. Under
    the gthread worker a caller whose slot is further away than
    ``utils.broker_backpressure.max_queue_wait`` is refused before it books
    anything; under eventlet and the dev server there is no bound.

    Args:
        category: "order", "live", "non_trading", "auth" or "history".

    Raises:
        BrokerBusyError: Under gthread, when the slot is too far away.
    """
    interval = MIN_INTERVAL[category]
    with _lock:
        now = time.monotonic()
        elapsed = now - _last_call_time[category]
        sleep_time = interval - elapsed if elapsed < interval else 0
        check_queue_wait(sleep_time, _queue_kind(category))
        _last_call_time[category] = now + sleep_time

    if sleep_time > 0:
        time.sleep(sleep_time)


def retry_delay(headers, attempt, category):
    """How long to wait before retrying a 429: Groww's Retry-After if it sent
    one, else 1, 2, 4 seconds.

    Raises:
        BrokerBusyError: Under gthread, when the wait is longer than a request
            may be held.
    """
    delay = BASE_BACKOFF * (2**attempt)
    retry_after = (headers or {}).get("Retry-After") or (headers or {}).get("retry-after")
    if retry_after:
        try:
            delay = max(float(retry_after), 0.05)
        except ValueError:
            # Retry-After may also be an HTTP date (RFC 9110 10.2.3)
            try:
                delay = max(parsedate_to_datetime(retry_after).timestamp() - time.time(), 0.05)
            except (TypeError, ValueError, OverflowError):
                pass
    if cap_server_delay(delay, _queue_kind(category)) is None:
        raise BrokerBusyError(
            "Groww asked OpenAlgo to slow down for longer than a request can be held. "
            "This request was not retried. Try again in a minute.",
            retry_after=delay,
        )
    return delay


def groww_request(client, method, url, category, **kwargs):
    """Make one paced Groww API call, retrying while Groww answers HTTP 429.

    Retrying a refused order is safe: Groww rejects a repeated
    order_reference_id (GA007), and a 429 means the order was not taken.

    Args:
        client: The shared httpx client.
        method: "GET", "POST", "PUT" or "DELETE".
        url: Full Groww URL.
        category: Rate-limit type, see MIN_INTERVAL.
        **kwargs: Passed to client.request (headers, params, json, timeout).

    Returns:
        The last response, a 429 only when every retry was refused.
    """
    response = None
    for attempt in range(MAX_RETRIES + 1):
        apply_rate_limit(category)
        response = client.request(method, url, **kwargs)
        if response.status_code != 429 or attempt == MAX_RETRIES:
            return response
        time.sleep(retry_delay(response.headers, attempt, category))
    return response
