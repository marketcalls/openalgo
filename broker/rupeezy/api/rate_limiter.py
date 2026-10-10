# broker/rupeezy/api/rate_limiter.py
#
# Per-category request pacing for the Vortex REST API.
#
# Vortex publishes independent limits per endpoint class (docs, Rate Limit
# column of each page):
#   quotes   /data/quotes (up to 1000 tickers)        1/sec
#   history  /data/history                            1/sec
#   account  /user/*                                  1/sec
#   trading  regular + GTT orders, books              10/sec
#
# State is module-level (services call these functions per request, so pacing
# kept on an instance would pace nothing), the slot is reserved inside the
# lock and the sleep happens outside it. Each category runs a little under its
# documented cap to leave headroom for clock jitter.
#
# Under the gthread worker a wait longer than the shared ceiling is refused
# with BrokerBusyError before the slot is booked (utils/broker_backpressure);
# under eventlet and the dev server the wait is unbounded, as before.

import threading
import time

from utils.broker_backpressure import check_queue_wait

_INTERVALS = {
    "quotes": 1.05,
    "history": 1.05,
    "account": 1.05,
    "trading": 0.11,
}

_lock = threading.Lock()
_next_slot = dict.fromkeys(_INTERVALS, 0.0)


def wait_for_slot(category, kind="data"):
    """Block until the next request slot for `category` is due.

    Raises:
        BrokerBusyError: gthread worker only, when the turn is further away
            than the ceiling for `kind` ("data" or "order"). Nothing is booked.
    """
    interval = _INTERVALS[category]
    with _lock:
        now = time.monotonic()
        slot = max(now, _next_slot[category])
        check_queue_wait(slot - now, kind)
        _next_slot[category] = slot + interval
    delay = slot - now
    if delay > 0:
        time.sleep(delay)


def category_for(method, endpoint):
    """Map a Vortex request to its rate-limit category."""
    if endpoint.startswith("/data/quotes"):
        return "quotes"
    if endpoint.startswith("/data/history"):
        return "history"
    if endpoint.startswith("/user/"):
        return "account"
    return "trading"
