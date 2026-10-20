"""
Shared rate limiting and 429-retry helpers for all Delta Exchange API calls.

Delta does not throttle by requests-per-second like Fyers or Dhan. Every REST
endpoint carries a **weight**, and the weights consumed are deducted from a
quota of 10000 units per fixed 5-minute window (see
delta-api-docs/04-rate-limits.md). Exceeding it returns HTTP 429 with
``X-RATE-LIMIT-RESET`` holding the milliseconds left until the window resets —
Delta does **not** send ``Retry-After``.

Two independent buckets, because Delta throttles "unauthenticated api requests
by IP address and authenticated requests by user ID". Public market data
(tickers, order book, candles, products) is sent unauthenticated by this
integration and therefore cannot exhaust the quota that order placement needs.

Verified live 2026-08-12 against ``GET /v2/rate_limits/quota``, which reports
``current_quota`` (units *consumed* this window, counting up) and
``remaining_time_in_milliseconds``: 20 distinct ticker calls moved the counter
by exactly 60, matching the documented weight of 3, and the quota endpoint
itself costs 3.

State is module-level rather than per-instance because services construct a
fresh ``BrokerData(auth_token)`` per request (see
services/option_chain_service.py, services/oi_tracker_service.py), so anything
kept on ``self`` is discarded before it can pace the next caller.
"""

import threading
import time

from broker.deltaexchange.api.baseurl import BASE_URL
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Buckets. Delta throttles unauthenticated traffic by IP and authenticated
# traffic by user id, so they never draw down each other's quota.
PUBLIC  = "public"
PRIVATE = "private"

WINDOW_SECONDS = 300.0    # Delta resets the quota every fixed 5 minutes
FULL_QUOTA     = 10000

# Spend at most 90% of the documented quota. The headroom absorbs the drift
# between Delta's fixed window and the floating one tracked here, and leaves
# room for order placement when a data poller is running hot.
BUDGET = int(FULL_QUOTA * 0.9)

# Longest a caller will be parked waiting for the window to reset. A reset can
# be almost 5 minutes out; blocking a web request that long is worse than
# failing it, so past this the call raises and the caller surfaces the error.
MAX_WAIT_SECONDS = 30.0

MAX_RETRIES  = 3
BASE_BACKOFF = 1.0   # seconds; fallback ladder when no reset header: 1, 2, 4

# Sleeps allowed inside one consume() call before giving up. A window reset
# frees the whole budget, so one wait is normally enough; the cap stops a
# clock jump or a contended bucket from parking a caller indefinitely.
_MAX_SLEEPS = 2

# Endpoint weights, longest prefix wins. Anything unlisted costs 1 unit.
# Method-specific entries are keyed (method, prefix) and take precedence.
_WEIGHTS_BY_METHOD = {
    ("POST",   "/v2/orders/batch"):  25,   # Batch Order Apis
    ("PUT",    "/v2/orders/batch"):  25,
    ("DELETE", "/v2/orders/batch"):  25,
    ("POST",   "/v2/orders"):         5,   # Place Order
    ("PUT",    "/v2/orders"):         5,   # Edit Order
    ("DELETE", "/v2/orders"):         5,   # Delete Order
}

_WEIGHTS = {
    "/v2/orders/history":            10,   # Get Order History
    "/v2/fills":                     10,   # Get Fills
    "/v2/wallet/transactions":       10,   # Get Txn Logs
    "/v2/positions/change_margin":    5,   # Add Position Margin
    "/v2/products":                   3,   # Get Products
    "/v2/tickers":                    3,   # Get Tickers
    "/v2/l2orderbook":                3,   # Get Orderbook
    "/v2/history/candles":            3,   # OHLC Candles
    "/v2/history/sparklines":         3,
    "/v2/orders":                     3,   # Get Open Orders (GET)
    "/v2/positions":                  3,   # Get Open Positions
    "/v2/wallet/balances":            3,   # Get Balances
    "/v2/rate_limits/quota":          3,   # measured; the meter costs too
}

DEFAULT_WEIGHT = 1

_lock = threading.Lock()
_state = {
    PUBLIC:  {"used": 0, "window_start": 0.0},
    PRIVATE: {"used": 0, "window_start": 0.0},
}


class DeltaRateLimitError(Exception):
    """Raised when the quota is spent and the reset is further out than MAX_WAIT_SECONDS."""


def endpoint_weight(endpoint: str, method: str = "GET") -> int:
    """Return the quota cost of one call to `endpoint`.

    `endpoint` is the path with no host and no query string, e.g. "/v2/tickers/BTCUSD".
    """
    path = (endpoint or "").split("?", 1)[0].rstrip("/")
    method = (method or "GET").upper()

    for (m, prefix), weight in _WEIGHTS_BY_METHOD.items():
        if m == method and (path == prefix or path.startswith(prefix + "/")):
            return weight

    best_weight = DEFAULT_WEIGHT
    best_len = -1
    for prefix, weight in _WEIGHTS.items():
        if (path == prefix or path.startswith(prefix + "/")) and len(prefix) > best_len:
            best_weight, best_len = weight, len(prefix)
    return best_weight


def _reset_if_window_elapsed(bucket: str, now: float) -> None:
    """Start a fresh window once 5 minutes have passed. Caller must hold _lock."""
    state = _state[bucket]
    if now - state["window_start"] >= WINDOW_SECONDS:
        state["used"] = 0
        state["window_start"] = now


def consume(endpoint: str, method: str = "GET", bucket: str = PUBLIC) -> None:
    """Account for one API call, blocking if this window's budget is spent.

    Raises DeltaRateLimitError when the window reset is further away than
    MAX_WAIT_SECONDS, so a caller fails cleanly instead of hanging for minutes.

    IMPORTANT: this can sleep, and Delta rejects any signature older than 5
    seconds ("SignatureExpired"). Authenticated callers must call this BEFORE
    building their HMAC headers, never between signing and sending.
    """
    weight = endpoint_weight(endpoint, method)
    probed = False
    slept = 0

    # Re-evaluated every pass: the reservation and the budget check have to
    # happen in the same locked section, or concurrent callers each decide
    # there is room, sleep, and then all add their weight on top of a budget
    # that only had space for one of them.
    while True:
        with _lock:
            now = time.time()
            _reset_if_window_elapsed(bucket, now)
            state = _state[bucket]

            if state["used"] + weight <= BUDGET:
                state["used"] += weight
                return

            wait = max(0.0, state["window_start"] + WINDOW_SECONDS - now)

        # Budget looks spent. Delta's window is fixed and ours floats, so
        # before parking anyone, spend 3 units asking the exchange where the
        # real window stands — it is often further along than the local view.
        #
        # Only for the public bucket: the quota endpoint is unauthenticated, so
        # it reports the IP allowance. Applying that answer to the per-user
        # bucket would hand back a quota the user may not have, and would undo
        # a 429 the exchange has already returned on an authenticated call.
        if bucket == PUBLIC and not probed:
            probed = True
            server = _fetch_server_quota(bucket)
            if server is not None:
                used, left = server
                with _lock:
                    state = _state[bucket]
                    state["used"] = used
                    state["window_start"] = time.time() - (WINDOW_SECONDS - left)
                continue   # re-check under the lock with the exchange's numbers

        if wait > MAX_WAIT_SECONDS or slept >= _MAX_SLEEPS:
            raise DeltaRateLimitError(
                f"Delta {bucket} rate-limit quota exhausted ({BUDGET} units in a "
                f"{int(WINDOW_SECONDS)}s window); resets in {wait:.0f}s"
            )

        logger.warning(
            "Delta %s quota exhausted; waiting %ss for the window to reset before %s",
            bucket, round(wait, 1), endpoint,
        )
        time.sleep(wait)
        slept += 1


def _fetch_server_quota(bucket: str) -> tuple[int, float] | None:
    """Read the authoritative quota. Returns (used_units, seconds_to_reset).

    Unauthenticated, so it reports the IP bucket; for the private bucket it is
    only a hint that the window has rolled over, which is still worth having.
    """
    try:
        resp = get_httpx_client().get(
            f"{BASE_URL}/v2/rate_limits/quota",
            headers={"Accept": "application/json"},
            timeout=5.0,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        used = int(data.get("current_quota", 0))
        left = float(data.get("remaining_time_in_milliseconds", 0)) / 1000.0
        # %s only — SensitiveDataFilter stringifies every log arg, so %d/%f
        # would raise and the line would print its raw format string.
        logger.info("Delta quota check (%s bucket): %s units used, resets in %ss",
                    bucket, used, round(left))
        return used, left
    except Exception as exc:
        logger.warning("Delta quota check failed: %s", exc)
        return None


def note_429(headers, bucket: str = PUBLIC) -> None:
    """Record that Delta rejected a call, so the next caller waits instead of piling on."""
    with _lock:
        state = _state[bucket]
        state["used"] = BUDGET
        reset = quota_reset_seconds(headers)
        if reset is not None:
            # Pin the local window to the exchange's, so the wait computed by
            # consume() matches when the quota actually comes back.
            state["window_start"] = time.time() - (WINDOW_SECONDS - reset)


def quota_reset_seconds(headers) -> float | None:
    """Seconds until the quota resets, from X-RATE-LIMIT-RESET (milliseconds).

    None when the header is absent or unparseable.
    """
    raw = None
    if headers:
        raw = headers.get("X-RATE-LIMIT-RESET") or headers.get("x-rate-limit-reset")
    if raw is None:
        return None
    try:
        return max(float(raw) / 1000.0, 0.0)
    except (TypeError, ValueError):
        return None


def server_requested_delay(headers) -> float | None:
    """The wait the server asked for, in seconds and UNCAPPED.

    Delta documents X-RATE-LIMIT-RESET (milliseconds until the window resets)
    and does not send Retry-After; Retry-After is still read in case that
    changes, and because a CDN or proxy in front of the API may send it.
    None when neither header is present or parseable.

    Callers use this to decide *whether* a retry is worth attempting, which is
    a different question from how long to sleep — see retry_delay_from_headers.
    """
    reset = quota_reset_seconds(headers)
    if reset is not None:
        return reset

    retry_after = headers.get("Retry-After") or headers.get("retry-after") if headers else None
    if retry_after:
        try:
            return max(float(retry_after), 0.0)
        except (TypeError, ValueError):
            pass

    return None


def retry_delay_from_headers(headers, attempt: int) -> float:
    """How long to sleep before retrying a 429, never more than MAX_WAIT_SECONDS.

    Every branch is capped, including Retry-After: a server or proxy asking for
    a ten-minute wait must not park a web request for ten minutes. When the
    requested wait exceeds the ceiling the caller should stop retrying rather
    than sleep the capped amount and try anyway — server_requested_delay()
    reports the uncapped figure for exactly that decision.
    """
    requested = server_requested_delay(headers)
    if requested is not None:
        return max(min(requested, MAX_WAIT_SECONDS), 0.05)

    return min(BASE_BACKOFF * (2**attempt), MAX_WAIT_SECONDS)


def snapshot() -> dict:
    """Current accounting, for logging and tests."""
    with _lock:
        now = time.time()
        return {
            bucket: {
                "used": state["used"],
                "budget": BUDGET,
                "resets_in": max(0.0, state["window_start"] + WINDOW_SECONDS - now),
            }
            for bucket, state in _state.items()
        }


def _reset_for_tests() -> None:
    with _lock:
        for state in _state.values():
            state["used"] = 0
            state["window_start"] = 0.0
