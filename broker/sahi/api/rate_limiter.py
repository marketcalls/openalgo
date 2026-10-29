"""
Shared rate limiting and 429-retry helpers for all Sahi API calls.

Sahi gives every endpoint its own budget per user, over a per-second and a
per-minute window (broker-api-docs/sahi-api-docs, Conventions, "Rate limits"):

    Endpoint                                   /second  /minute
    place, modify, cancel order (shared)           10      250
    order book, order detail, order trades          5      250
    positions                                       5      250
    holdings                                        5      250
    funds                                           1        -
    order margin, basket margin (shared)            5      250
    profile                                         1        -
    marketdata/ltp                                  1        -
    marketdata/quotes                               1        -
    marketdata/candles                              2      250
    marketdata/optionchain                          2      120
    marketdata/optionchain/expiries                 5      250

Every row is its own counter, so each category here has its own clock and a
burst of quotes never delays an order. The token endpoint on the auth host is
limited separately and its figure is not published; logins are paced at one
every two seconds.

Each category keeps the times of the calls it has booked and books the
earliest slot both of its windows allow, so a burst runs at the per-second
rate until the per-minute budget is used (the flattrade pattern). The state is
module level: services build a fresh BrokerData per request, so state kept on
an instance would pace nothing. Every window is paced a little under Sahi's
figure to leave room for clock jitter.

A refused call carries a Retry-After header in whole seconds, which is honoured
before retrying.
"""

import threading
import time
from collections import deque
from email.utils import parsedate_to_datetime

from utils.broker_backpressure import BrokerBusyError, cap_server_delay, check_queue_wait

# (calls, window seconds) pairs per category. A one-per-second endpoint is
# paced at one per 1.05 s.
LIMITS = {
    "order_write": ((9, 1.0), (240, 60.0)),
    "order_read": ((4, 1.0), (240, 60.0)),
    "positions": ((4, 1.0), (240, 60.0)),
    "holdings": ((4, 1.0), (240, 60.0)),
    "funds": ((1, 1.05),),
    "margin": ((4, 1.0), (240, 60.0)),
    "profile": ((1, 1.05),),
    "ltp": ((1, 1.05),),
    "quotes": ((1, 1.05),),
    "candles": ((2, 1.05), (240, 60.0)),
    "optionchain": ((2, 1.05), (115, 60.0)),
    "expiries": ((4, 1.0), (240, 60.0)),
    "auth": ((1, 2.0),),
}

MAX_RETRIES = 3
BASE_BACKOFF = 1.0  # seconds; exponential fallback when Sahi gives no Retry-After: 1, 2, 4

_lock = threading.Lock()
# time.monotonic() of the calls each category has booked, oldest first. Only
# the newest `calls` entries of the longest window can constrain a new slot.
_booked = {category: deque() for category in LIMITS}


def _queue_kind(category):
    """The utils.broker_backpressure kind: order writes get the order bound."""
    return "order" if category == "order_write" else "data"


def _next_slot(category, now):
    """Earliest monotonic time a new call of ``category`` may start."""
    booked = _booked[category]
    longest = max(window for _, window in LIMITS[category])
    while booked and booked[0] <= now - longest:
        booked.popleft()
    # Never before a slot already booked, so the deque stays in time order.
    slot = max(now, booked[-1]) if booked else now
    for calls, window in LIMITS[category]:
        if len(booked) >= calls:
            # The call `calls` places back must have left the window first.
            slot = max(slot, booked[-calls] + window)
    return slot


def apply_rate_limit(category):
    """Block until another call of ``category`` may be made.

    Under the gthread worker a caller whose slot is further away than
    ``utils.broker_backpressure.max_queue_wait`` is refused before it books
    anything; under eventlet and the dev server there is no bound.

    Raises:
        BrokerBusyError: Under gthread, when the slot is too far away.
    """
    with _lock:
        now = time.monotonic()
        slot = _next_slot(category, now)
        sleep_time = slot - now
        check_queue_wait(sleep_time, _queue_kind(category))
        _booked[category].append(slot)

    if sleep_time > 0:
        time.sleep(sleep_time)


def retry_delay(headers, attempt, category):
    """How long to wait before retrying a 429: Sahi's Retry-After if it sent
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
            "Sahi asked OpenAlgo to slow down for longer than a request can be held. "
            "This request was not retried. Try again in a minute.",
            retry_after=delay,
        )
    return delay


def sahi_request(client, method, url, category, **kwargs):
    """Make one paced Sahi API call, retrying while Sahi answers HTTP 429.

    Retrying a refused order is safe: a 429 is decided before the order
    reaches risk checks or the exchange, so nothing was placed.

    Args:
        client: The shared httpx client.
        method: "GET", "POST", "PUT" or "DELETE".
        url: Full Sahi URL.
        category: Rate-limit category, see LIMITS.
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
