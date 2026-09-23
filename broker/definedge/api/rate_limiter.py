"""
Shared rate limiting and 429-retry helpers for all DefinedGe API calls.

DefinedGe's INTEGRATE API does not publish hard rate limits, but the broker
throttles bursty clients (observed on multi-quote and basket-order flows).
Pacing state MUST live in one module-level place that every importer shares --
services create a fresh BrokerData(auth_token) per request, so any state kept
on `self` is reset away on every call and never actually paces anything
against concurrent requests (same lesson as broker/fyers/api/rate_limiter.py).
"""

import threading
import time
from urllib.parse import urlparse

from utils.broker_backpressure import BrokerBusyError, cap_server_delay, check_queue_wait
from utils.logging import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()
_last_call_time = {}  # {bucket: timestamp} - one pacing clock per API host

# Pace at ~10 req/sec PER HOST. DefinedGe serves trading REST
# (integrate.definedgesecurities.com) and historical data
# (data.definedgesecurities.com) from separate hosts with independent
# throttles, so each gets its own bucket - an option chain load (quotes on the
# trade host + OI backfill on the data host) runs both streams concurrently
# without one starving the other.
MIN_INTERVAL = 0.1

MAX_RETRIES = 3
BASE_BACKOFF = 1.0  # seconds; exponential backoff when no Retry-After header: 1, 2, 4


def apply_rate_limit(bucket="trade", kind="data"):
    """Block the calling thread until it is safe to make another DefinedGe API call.

    Shared process-wide (module-level lock + per-bucket timestamp) so every
    caller across broker.definedge.api paces against the same clock for a given
    host, regardless of how many separate BrokerData/order_api calls are in
    flight at once.

    Every caller books the slot after the last one, so a burst on one host
    queues without limit, and order placement shares the trade host's clock.
    Under the gthread worker each queued caller holds a request thread, so one
    whose slot is further away than
    ``utils.broker_backpressure.max_queue_wait(kind)`` is refused before it
    books anything. Under eventlet and the dev server there is no bound.

    Args:
        bucket: The API host whose clock to pace against.
        kind: ``"data"``, or ``"order"`` for order placement and changes.

    Raises:
        BrokerBusyError: Under gthread, when the slot is too far away.
    """
    with _lock:
        now = time.time()
        elapsed = now - _last_call_time.get(bucket, 0.0)
        sleep_time = MIN_INTERVAL - elapsed if elapsed < MIN_INTERVAL else 0
        check_queue_wait(sleep_time, kind)
        _last_call_time[bucket] = now + sleep_time

    if sleep_time > 0:
        time.sleep(sleep_time)


def retry_delay(headers, attempt, kind="data"):
    """Compute how long to wait before retrying a 429, honoring Retry-After if sent.

    Under the gthread worker a Retry-After longer than ``max_queue_wait(kind)``
    is not slept: three retries of a 60 second Retry-After held a request
    thread for three minutes. The retry is abandoned instead.

    Raises:
        BrokerBusyError: Under gthread, when the broker asks for a longer wait
            than the bound.
    """
    delay = BASE_BACKOFF * (2**attempt)
    retry_after = headers.get("Retry-After") or headers.get("retry-after")
    if retry_after:
        try:
            delay = max(float(retry_after), 0.05)
        except ValueError:
            pass
    if cap_server_delay(delay, kind) is None:
        raise BrokerBusyError(
            "Definedge asked OpenAlgo to slow down and wait longer than a request "
            "can be held. This request was not retried. Try again in a minute.",
            retry_after=delay,
        )
    return delay


def rate_limited_request(client, method, url, *, wait_kind="data", **kwargs):
    """Make a paced HTTP request via the shared httpx client, retrying on 429.

    Every DefinedGe REST call should go through this helper so pacing and
    rate-limit retries are applied uniformly.

    Args:
        client: The shared httpx client.
        method: HTTP method.
        url: Full request URL; its host picks the pacing bucket.
        wait_kind: Which wait bound applies under the gthread worker:
            ``"data"``, or ``"order"`` for placing, changing or cancelling.
        **kwargs: Passed to ``client.request``.

    Raises:
        BrokerBusyError: Under gthread, when the wait for a slot, or a
            broker-requested retry delay, would exceed the bound.
    """
    bucket = urlparse(url).netloc or "trade"
    response = None
    for attempt in range(MAX_RETRIES + 1):
        apply_rate_limit(bucket, wait_kind)
        response = client.request(method, url, **kwargs)
        if response.status_code != 429:
            return response
        if attempt < MAX_RETRIES:
            delay = retry_delay(response.headers, attempt, wait_kind)
            logger.warning(
                f"DefinedGe rate limit hit (429) on {method} {url}; "
                f"retry {attempt + 1}/{MAX_RETRIES} in {delay:.2f}s"
            )
            time.sleep(delay)
    return response
