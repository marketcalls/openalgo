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

from utils.logging import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()
_active: dict[str, int] = {}
_peak: dict[str, int] = {}

# Hard cap on distinct stream kinds.
#
# `kind` is meant to name a CLASS of stream ("mcp_sse"), of which there are a
# handful. Nothing in the signature stops a caller passing something
# per-connection instead -- a client id, a session id -- and that would make
# this registry grow without bound in a worker that runs for weeks. That is the
# exact defect this migration spent its time removing from other registries, so
# it would be poor form to ship it in the thing built to measure them.
#
# Excess kinds are folded into one bucket rather than dropped: losing the count
# entirely would be worse than losing its breakdown.
MAX_KINDS = 32
_OVERFLOW = "_other"


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
        if kind not in _active and len(_active) >= MAX_KINDS:
            logger.warning(
                "stream_registry: %d distinct kinds already tracked; folding %r into %r. "
                "kind should name a class of stream, not an individual connection.",
                MAX_KINDS,
                kind,
                _OVERFLOW,
            )
            kind = _OVERFLOW
        current = _active.get(kind, 0) + 1
        _active[kind] = current
        if current > _peak.get(kind, 0):
            _peak[kind] = current
    tracked = kind  # may have been folded into the overflow bucket above
    try:
        yield
    finally:
        with _lock:
            _active[tracked] = max(0, _active.get(tracked, 1) - 1)


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
