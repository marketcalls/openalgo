# broker/rupeezy/api/client.py
#
# One request helper for every authenticated Vortex REST call: shared pooled
# httpx client, Bearer auth, per-category pacing, and for reads (GET) only a
# bounded retry on 429 and one retry on a dead pooled connection. Writes are
# never retried: a broker can accept an order and still answer with an error,
# and a resent order could be placed twice.

import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from broker.rupeezy.api.baseurl import BASE_URL, get_rupeezy_headers
from broker.rupeezy.api.rate_limiter import category_for, wait_for_slot
from utils.broker_backpressure import cap_server_delay
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

_MAX_429_RETRIES = 2
_DEFAULT_TIMEOUT = 30

# A pooled connection Vortex dropped while idle hangs until the read timeout.
# Reads get a short first attempt and one retry on a fresh connection.
_READ_FIRST_TIMEOUT = 10
_RETRYABLE_READ_ERRORS = (httpx.TimeoutException, httpx.RemoteProtocolError, httpx.ConnectError)


class RupeezyAPIError(Exception):
    pass


def _retry_after_seconds(response, attempt):
    """Seconds a 429 asks us to wait: Retry-After as seconds or an HTTP date,
    else exponential backoff."""
    raw = (response.headers.get("Retry-After") or "").strip()
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            try:
                when = parsedate_to_datetime(raw)
                return max(0.0, (when - datetime.now(UTC)).total_seconds())
            except (TypeError, ValueError):
                pass
    return float(2**attempt)


def request(method, endpoint, auth, payload=None, params=None, timeout=_DEFAULT_TIMEOUT):
    """Call the Vortex REST API and return the raw httpx response.

    Does not raise on HTTP error status: Vortex returns a JSON
    {"status": "error", "code", "message"} body on 4xx, and callers need it.

    Raises:
        BrokerBusyError: gthread worker only, when the rate-limit queue would
            hold this request past the shared ceiling.
    """
    client = get_httpx_client()
    headers = get_rupeezy_headers(auth, with_json=payload is not None)
    url = f"{BASE_URL}{endpoint}"
    method = method.upper()
    category = category_for(method, endpoint)
    is_read = method == "GET"
    kind = "data" if is_read else "order"

    def send(attempt_timeout):
        wait_for_slot(category, kind)
        return client.request(
            method,
            url,
            headers=headers,
            json=payload,
            params=params,
            timeout=attempt_timeout,
        )

    if not is_read:
        return send(timeout)

    for attempt in range(_MAX_429_RETRIES + 1):
        try:
            response = send(min(timeout, _READ_FIRST_TIMEOUT))
        except _RETRYABLE_READ_ERRORS as e:
            logger.warning(f"Rupeezy {endpoint} read failed ({type(e).__name__}); retrying once")
            response = send(timeout)
        if response.status_code != 429 or attempt == _MAX_429_RETRIES:
            return response
        backoff = cap_server_delay(_retry_after_seconds(response, attempt), kind)
        if backoff is None:
            return response
        logger.warning(f"Rupeezy rate limited on {endpoint}; retrying in {backoff:.1f}s")
        time.sleep(backoff)
    return response


def request_json(method, endpoint, auth, payload=None, params=None, timeout=_DEFAULT_TIMEOUT):
    """Like request() but returns the decoded JSON body.

    A non-JSON body (gateway error page) becomes an OpenAlgo-style error dict
    so callers never crash on decode.
    """
    response = request(method, endpoint, auth, payload=payload, params=params, timeout=timeout)
    if response.is_success and not response.content:
        # e.g. 204 No Content on a delete: the call succeeded, there is no body.
        return {"status": "success"}
    try:
        data = response.json()
    except ValueError:
        logger.error(
            f"Rupeezy {endpoint} returned non-JSON (HTTP {response.status_code}): {response.text[:200]}"
        )
        return {
            "status": "error",
            "message": "Rupeezy returned an unexpected response. Please retry.",
        }
    if not response.is_success and isinstance(data, dict):
        data.setdefault("status", "error")
    return data
