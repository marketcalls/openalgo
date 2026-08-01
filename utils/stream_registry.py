"""Live count of long-lived streams (gthread gate A6-04 / B1).

Under gthread every open SSE stream and every Socket.IO transport occupies one
Gunicorn worker thread for its entire lifetime. That makes them the dominant
term in the thread budget -- and the one term nobody could measure.

The plan's sizing formula asks for "active Python Strategy SSE streams" and
"active MCP SSE streams" as inputs. Before this, the first was knowable only by
reading a private list and the second was not knowable at all, so the numbers in
the acceptance table were estimates with no way to check them against reality.

Counts are reported through the admin runtime diagnostics, so an operator can
compare live stream count against the configured thread count and see how much
headroom is actually left rather than inferring it.
"""

import threading
from contextlib import contextmanager

_lock = threading.Lock()
_active: dict[str, int] = {}
_peak: dict[str, int] = {}


@contextmanager
def track_stream(kind: str):
    """Count one long-lived stream for its lifetime.

    Wrap the generator body, not the route: the thread is held for as long as
    the generator is alive, which is what actually consumes the budget.

    Decrement happens in a ``finally`` because a disconnecting client raises
    out of the generator -- the common exit, not the exceptional one. Miss it
    and the count only ever rises, which is worse than not counting at all.
    """
    with _lock:
        current = _active.get(kind, 0) + 1
        _active[kind] = current
        if current > _peak.get(kind, 0):
            _peak[kind] = current
    try:
        yield
    finally:
        with _lock:
            _active[kind] = max(0, _active.get(kind, 1) - 1)


def stream_counts() -> dict:
    """Active and peak stream counts, plus the total thread pressure."""
    with _lock:
        active = dict(_active)
        peak = dict(_peak)
    return {
        "active": active,
        "peak": peak,
        "total_active": sum(active.values()),
        "total_peak": sum(peak.values()),
    }


def reset_peaks() -> None:
    """Clear the high-water marks, e.g. at the start of a soak window."""
    with _lock:
        _peak.clear()
