"""Shared rate limiting and retry helpers for all TradeSmart (Noren) API calls.

TradeSmart does not have one global budget. ``/GetQuotes`` is capped at 100
requests **per second**, while the remaining data endpoints stay on the older
per-user, per-minute allowance of 120 (the backend rejects the 121st with
``stat=Not_Ok`` and an emsg like "Order Recieved 141 in a current minute exceeds
Limit 120 for user"). Pacing both from a single gate would either throttle
quotes to a fraction of what the broker now allows, or let history calls run
60x over their ceiling, so each class gets its own gate.

State is module level, exactly as in ``broker.fyers.api.rate_limiter`` and for
the same reason: services construct a fresh ``BrokerData(auth_token)`` per
request (see ``services/option_chain_service.py``,
``services/oi_tracker_service.py``), so any pacing state kept on ``self`` is
discarded on every call and paces nothing against concurrent requests.

Each gate reserves its slot under the lock and sleeps outside it. Holding a
lock across ``time.sleep`` would serialise every waiter behind the sleeper and
turn a 100/sec allowance back into a queue.
"""

import threading
import time

# Documented quotes cap is 100 req/sec. Paced at ~90/sec, mirroring the ~20%
# headroom Fyers uses, to absorb clock jitter and the fact that several
# BrokerData instances can be issuing quote calls concurrently.
QUOTES_MIN_INTERVAL = 1.0 / 90.0

# Everything else - history (/EODChartData, /TPSeries) and any future endpoint
# - stays on the per-minute allowance. 0.55s/req is ~109/min, under the 120/min
# ceiling.
DEFAULT_MIN_INTERVAL = 0.55

#: Endpoints that bill against the per-second quotes budget. get_depth is here
#: too: TradeSmart has no separate depth endpoint, so it calls /GetQuotes and
#: is charged at the same rate.
QUOTES_ENDPOINTS = frozenset({"/GetQuotes"})

MAX_RETRIES = 3
BASE_BACKOFF = 2.0  # seconds; exponential when the broker reports a limit hit


class _Gate:
    """One independent budget: its own lock, its own clock."""

    def __init__(self, interval: float):
        self.interval = interval
        self._lock = threading.Lock()
        self._last_call = 0.0

    def wait(self) -> None:
        sleep_time = 0.0
        with self._lock:
            now = time.time()
            elapsed = now - self._last_call
            if elapsed < self.interval:
                sleep_time = self.interval - elapsed
            # Reserve this caller's slot before releasing, so concurrent
            # callers space out instead of all measuring against the same
            # stale timestamp and firing together.
            self._last_call = now + sleep_time
        if sleep_time > 0:
            time.sleep(sleep_time)


_QUOTES_GATE = _Gate(QUOTES_MIN_INTERVAL)
_DEFAULT_GATE = _Gate(DEFAULT_MIN_INTERVAL)


def gate_for(endpoint: str | None) -> _Gate:
    """The budget ``endpoint`` bills against.

    Anything unclassified, including ``None``, gets the slower per-minute gate,
    so an endpoint added later is paced conservatively rather than being
    silently granted the per-second allowance.
    """
    return _QUOTES_GATE if endpoint in QUOTES_ENDPOINTS else _DEFAULT_GATE


def interval_for(endpoint: str | None) -> float:
    """Minimum spacing between two calls to ``endpoint``."""
    return gate_for(endpoint).interval


def apply_rate_limit(endpoint: str | None = None) -> None:
    """Block until it is safe to issue another call to ``endpoint``.

    The two budgets are independent, so a burst of quotes must not delay a
    history call and vice versa.

    Args:
        endpoint: Noren path, e.g. ``"/GetQuotes"``.
    """
    gate_for(endpoint).wait()


def is_rate_limit_error(response) -> bool:
    """Whether TradeSmart is reporting a rate-limit rejection.

    Noren answers with ``stat=Not_Ok`` and an emsg naming the breached limit,
    e.g. "Invalid Input :  Order Recieved 141 in a current minute exceeds Limit
    120 for user". Matched on the phrase rather than the number so a changed
    ceiling is still recognised.
    """
    if not isinstance(response, dict):
        return False
    if response.get("stat") != "Not_Ok":
        return False
    emsg = response.get("emsg", "") or ""
    return "exceeds limit" in emsg.lower()


def retry_delay(attempt: int) -> float:
    """Backoff before retrying a rate-limited call: 2s, 4s, 8s."""
    return BASE_BACKOFF * (2**attempt)
