"""Per-call strategy-mode override (Phase 6 sandbox parity).

The strategy v2 engine carries a `mode` flag on each run ('live' | 'sandbox')
that should drive routing independent of the global analyze toggle. Without
this contextvar, a sandbox-mode strategy would still route to LIVE when the
global analyze flag is OFF — a Phase 1 known issue (see services/strategy/
broker_adapter_impls.py module docstring).

This module provides a ContextVar that BrokerAdapter implementations set
around their service calls. `place_order_with_auth` (and any other order
path that branches on global analyze) checks this contextvar BEFORE the
global flag — when set, it wins.

ContextVar properties we rely on:
  - per-thread / per-async-task isolation. Eventlet green threads each get
    their own context, so two concurrent runs in different modes don't
    leak state.
  - the @contextmanager wrapper guarantees reset on exception via the
    try/finally — no risk of a hung override carrying into unrelated calls.

Usage from a BrokerAdapter:

    with force_strategy_mode("sandbox"):
        ok, resp, _ = place_order_service.place_order(order_data, api_key)

Usage from the order service (place_order_with_auth):

    forced = get_force_mode()
    if forced == "sandbox":
        # always sandbox path, regardless of global analyze
    elif forced == "live":
        # always live path
    else:
        # forced is None — fall back to global analyze flag
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Literal, Optional

ForceMode = Literal["live", "sandbox"]

# Default None means "no override; use the global analyze flag".
_force_mode: ContextVar[Optional[ForceMode]] = ContextVar(
    "openalgo_strategy_v2_force_mode", default=None
)


def get_force_mode() -> Optional[ForceMode]:
    """Return the current per-call mode override, or None if not set.

    Read from inside the order pipeline (place_order_with_auth) BEFORE
    consulting the global analyze flag.
    """
    return _force_mode.get()


@contextmanager
def force_strategy_mode(mode: ForceMode) -> Iterator[None]:
    """Set the override for the duration of the with-block. Exception-safe —
    the try/finally always runs the reset, even on exception.

    Nested with-blocks compose correctly via ContextVar tokens: the inner
    set+reset uses its own token, restoring whatever the outer block set
    when it exits.
    """
    if mode not in ("live", "sandbox"):
        raise ValueError(f"force_strategy_mode: unknown mode {mode!r}")
    token = _force_mode.set(mode)
    try:
        yield
    finally:
        _force_mode.reset(token)


def is_sandbox_forced() -> bool:
    """Convenience: True iff the override is explicitly 'sandbox'."""
    return _force_mode.get() == "sandbox"


def is_live_forced() -> bool:
    """Convenience: True iff the override is explicitly 'live'."""
    return _force_mode.get() == "live"
