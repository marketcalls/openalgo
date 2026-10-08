# broker/rupeezy/api/client.py
#
# One request helper for every authenticated Vortex REST call: shared pooled
# httpx client, Bearer auth, per-category pacing, a bounded retry on 429, and
# one retry of a read (GET) that hits a dead pooled connection.

import time

import httpx

from broker.rupeezy.api.baseurl import BASE_URL, get_rupeezy_headers
from broker.rupeezy.api.rate_limiter import category_for, wait_for_slot
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

_MAX_429_RETRIES = 2
_DEFAULT_TIMEOUT = 30

# A pooled connection Vortex dropped while idle hangs until the read timeout
# (seen live: a position read waited the full 30s). Reads get a short first
# attempt and one retry on a fresh connection. Writes are never retried: a
# retried order could be placed twice.
_READ_FIRST_TIMEOUT = 10
_RETRYABLE_READ_ERRORS = (httpx.TimeoutException, httpx.RemoteProtocolError, httpx.ConnectError)


class RupeezyAPIError(Exception):
    pass


def request(method, endpoint, auth, payload=None, params=None, timeout=_DEFAULT_TIMEOUT):
    """Call the Vortex REST API and return the raw httpx response.

    Does not raise on HTTP error status: Vortex returns a JSON
    {"status": "error", "code", "message"} body on 4xx, and callers need it.
    """
    client = get_httpx_client()
    headers = get_rupeezy_headers(auth, with_json=payload is not None)
    url = f"{BASE_URL}{endpoint}"
    category = category_for(method, endpoint)

    is_read = method.upper() == "GET"

    def send(attempt_timeout):
        wait_for_slot(category)
        return client.request(
            method.upper(),
            url,
            headers=headers,
            json=payload,
            params=params,
            timeout=attempt_timeout,
        )

    for attempt in range(_MAX_429_RETRIES + 1):
        if is_read:
            try:
                response = send(min(timeout, _READ_FIRST_TIMEOUT))
            except _RETRYABLE_READ_ERRORS as e:
                logger.warning(
                    f"Rupeezy {endpoint} read failed ({type(e).__name__}); retrying once"
                )
                response = send(timeout)
        else:
            response = send(timeout)
        if response.status_code != 429 or attempt == _MAX_429_RETRIES:
            return response
        backoff = float(response.headers.get("Retry-After") or 2**attempt)
        logger.warning(f"Rupeezy rate limited on {endpoint}; retrying in {backoff:.1f}s")
        time.sleep(backoff)
    return response


def request_json(method, endpoint, auth, payload=None, params=None, timeout=_DEFAULT_TIMEOUT):
    """Like request() but returns the decoded JSON body.

    A non-JSON body (gateway error page) becomes an OpenAlgo-style error dict
    so callers never crash on decode.
    """
    response = request(method, endpoint, auth, payload=payload, params=params, timeout=timeout)
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
