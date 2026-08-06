"""
Shared rate limiting and 429-retry helpers for all Zerodha (Kite) API calls.

Zerodha publishes a **per-endpoint-class** cap rather than one global budget
(zerodha-api-docs/19-api-reference.md -> "Rate Limits"):

    Quote        1 / second
    Historical   3 / second
    Orders      10 / second
    Others      10 / second

Quote at 1/sec is the tightest limit of any broker OpenAlgo supports, and it is
what /gammadensity, the option chain and the OI tracker all lean on hardest.
Note that the cap counts *requests*, not instruments: /quote carries up to 500
instruments per call and /quote/ltp up to 1000, and a full batch costs the same
one unit as a single symbol. Batching is therefore about the per-call cap, and
pacing is about the per-second cap; they are independent.

The pacing state is module-level for the same reason it is in the Fyers
limiter: services construct a fresh ``BrokerData(auth_token)`` for every
request (services/quotes_service.py, option_chain_service.py, and others), so
anything kept on ``self`` is discarded before the next call and paces nothing.
The previous implementation slept between batches *inside* one
``get_multiquotes`` call, which meant a single call of 500 symbols or fewer was
never throttled at all, and two calls arriving in the same second both fired
immediately.

Unlike Fyers, the classes here do not share a budget, so each keeps its own
clock: a burst of quote calls must not delay order placement.
"""

import threading
import time

from utils.logging import get_logger

logger = get_logger(__name__)

BASE_URL = "https://api.kite.trade"

# Documented limits, paced slightly under to leave room for clock jitter and
# for the network putting two requests on the wire closer than they were sent.
LIMITS = {
    "quote": 1.05,       # 1/sec documented; 1.05s between calls
    "historical": 0.35,  # 3/sec documented
    "order": 0.11,       # 10/sec documented
    "other": 0.11,       # 10/sec documented
}

MAX_RETRIES = 3
BASE_BACKOFF = 1.0  # seconds; 1, 2, 4 when the response carries no hint

_lock = threading.Lock()
_last_call: dict[str, float] = dict.fromkeys(LIMITS, 0.0)


def category_for(endpoint: str) -> str:
    """
    Which documented limit an endpoint falls under.

    Derived from the path rather than passed by each caller, so a new call site
    is paced correctly without anyone remembering to classify it.
    """
    path = (endpoint or "").split("?", 1)[0]

    # Historical is checked first: its path also contains "/instruments".
    if "/instruments/historical" in path:
        return "historical"
    if path.startswith("/quote") or "/quote" in path:
        return "quote"
    if path.startswith("/orders") or path.startswith("/trades") or "/gtt" in path:
        return "order"
    return "other"


def apply_rate_limit(endpoint: str) -> None:
    """
    Block until it is safe to make this call.

    The timestamp is advanced to the *scheduled* time rather than to now, so
    concurrent threads queue behind one another instead of all measuring the
    same idle gap and firing together.
    """
    key = category_for(endpoint)
    interval = LIMITS[key]

    with _lock:
        now = time.time()
        elapsed = now - _last_call[key]
        sleep_for = interval - elapsed if elapsed < interval else 0.0
        _last_call[key] = now + sleep_for

    if sleep_for > 0:
        time.sleep(sleep_for)


def is_rate_limited(response_data: dict | None, status_code: int | None = None) -> bool:
    """
    Whether a response is a rate-limit rejection.

    Kite answers with HTTP 429, but it also returns 200 carrying
    ``{"status": "error", "message": "Too many requests"}`` and
    ``error_type: "NetworkException"``, which is what the reported failure
    showed. Both forms have to count, or the retry never triggers on the one
    users actually hit.
    """
    if status_code == 429:
        return True
    if not isinstance(response_data, dict):
        return False
    if response_data.get("status") != "error":
        return False
    message = str(response_data.get("message", "")).lower()
    return "too many request" in message or "rate limit" in message


def retry_delay(headers, attempt: int, endpoint: str) -> float:
    """
    How long to wait before retrying a rate-limited call.

    Prefers a ``Retry-After`` header when the gateway sends one, otherwise
    backs off exponentially from a floor of one full interval for that class,
    so a quote retry never comes back inside the 1-second window.
    """
    if headers:
        retry_after = headers.get("Retry-After") or headers.get("retry-after")
        if retry_after:
            try:
                return max(float(retry_after), 0.05)
            except (TypeError, ValueError):
                pass

    floor = LIMITS[category_for(endpoint)]
    return max(floor, BASE_BACKOFF * (2**attempt))


def request(client, method: str, url: str, **kwargs):
    """
    Issue a Kite request through the limiter, retrying rate-limit rejections.

    Returns ``(response, data)``, where ``data`` is the parsed JSON body or
    ``None`` when the body was not JSON. It is handed back rather than left to
    the caller because the retry loop has already parsed it once, and a
    500-instrument quote body is not worth decoding twice.

    Callers keep their own error handling: this only adds pacing and retries,
    and returns the final response either way so nothing changes shape.
    """
    endpoint = url[len(BASE_URL) :] if url.startswith(BASE_URL) else url
    path = endpoint.split("?", 1)[0]
    send = getattr(client, method.lower())

    response = None
    data = None
    for attempt in range(MAX_RETRIES + 1):
        apply_rate_limit(endpoint)
        response = send(url, **kwargs)

        try:
            data = response.json()
        except Exception:  # noqa: BLE001 - a rejection page need not be JSON
            data = None

        if not is_rate_limited(data, response.status_code):
            return response, data

        if attempt >= MAX_RETRIES:
            logger.warning(
                "Zerodha rate limit on %s persisted after %d retries", path, MAX_RETRIES
            )
            return response, data

        wait = retry_delay(response.headers, attempt, endpoint)
        logger.info(
            "Zerodha rate limited on %s, retrying in %.2fs (attempt %d/%d)",
            path,
            wait,
            attempt + 1,
            MAX_RETRIES,
        )
        time.sleep(wait)

    return response, data
