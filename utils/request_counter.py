"""How often each kind of broker data request was made in the last few minutes.

The status API (``/api/v1/status``) reports these counts so a trader can see
what is loading the broker: a chart polling quotes every second, a positions
page refreshing, a strategy fetching history in a loop. Each count is taken
where the request leaves for the broker (the ``*_with_auth`` service
functions), so it covers the REST API, the React pages, Flow, the strategy
module and the Python host alike.

Counts live in memory, one per-second bucket per kind, and only the last
``MAX_WINDOW_SEC`` seconds are kept, so the memory used is bounded no matter how
busy the broker is. They are per process and start empty on restart.
"""

from __future__ import annotations

import time
from collections import deque

from utils import real_threading

#: The longest window that can be asked for. Older buckets are dropped.
MAX_WINDOW_SEC = 300

#: The windows the status API reports, in seconds.
DEFAULT_WINDOWS = (60, 300)

#: Kinds always reported, with zero when nothing was counted.
KINDS = (
    "quotes",
    "multiquotes",
    "depth",
    "history",
    "positionbook",
    "orderbook",
    "tradebook",
    "holdings",
    "funds",
)

# A real lock, as in utils.stream_registry: only deque arithmetic is done under
# it, so no thread or greenlet waits on it for long.
_lock = real_threading.Lock()
# kind -> deque of [second, count], oldest first.
_buckets: dict[str, deque] = {kind: deque() for kind in KINDS}


def _prune(buckets: deque, now: int) -> None:
    oldest = now - MAX_WINDOW_SEC
    while buckets and buckets[0][0] <= oldest:
        buckets.popleft()


def record(kind: str, now: float | None = None) -> None:
    """Count one request of ``kind``. Unknown kinds are ignored."""
    second = int(time.monotonic() if now is None else now)
    with _lock:
        buckets = _buckets.get(kind)
        if buckets is None:
            return
        if buckets and buckets[-1][0] == second:
            buckets[-1][1] += 1
        else:
            buckets.append([second, 1])
            _prune(buckets, second)


def counts(windows=DEFAULT_WINDOWS, now: float | None = None) -> dict[str, dict[str, int]]:
    """Requests per kind in each window: ``{"last_60s": {"quotes": 12, ...}, ...}``."""
    second = int(time.monotonic() if now is None else now)
    windows = [min(int(w), MAX_WINDOW_SEC) for w in windows]
    result = {f"last_{w}s": dict.fromkeys(KINDS, 0) for w in windows}
    with _lock:
        for kind, buckets in _buckets.items():
            _prune(buckets, second)
            for bucket_second, count in buckets:
                age = second - bucket_second
                for w in windows:
                    if age < w:
                        result[f"last_{w}s"][kind] += count
    return result


def _reset_for_tests() -> None:
    """Clear every count. Tests only."""
    with _lock:
        for buckets in _buckets.values():
            buckets.clear()
