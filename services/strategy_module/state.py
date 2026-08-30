"""In-process runtime state for strategy runs.

The original this is ported from keeps this state in Redis. Here it is a plain
dict, and that is a deliberate upgrade rather than a downgrade: OpenAlgo runs
as a single Gunicorn worker (``-w 1``, hardcoded in ``start.sh`` and
``install/install.sh``, with no environment variable to raise it), so there is
exactly one process that can own a run. A network hop to Redis would buy no
correctness and would put an await on the hottest path in the module.

Durability is not this module's job. Every few seconds ``checkpoint`` writes a
snapshot to ``sm_strategy_checkpoint``, and on boot ``recovery`` rebuilds this
dict from the order rows plus the newest checkpoint. Losing the process loses
at most the seconds since the last checkpoint, and the per-leg stop levels
re-derive from the next tick anyway.

The stored shape is kept identical to the checkpoint's ``leg_state`` JSON so
that a snapshot round-trips through the database without translation.

Threading
---------

Everything that touches this module runs as a greenlet: the tick consumer, the
engine, the scheduler jobs and the request handlers. The market-data producer
is the one thing that may be a real OS thread, and it never comes here - it
hands a tick to a queue and returns. So the locks below are ordinary
``threading`` locks, which eventlet makes green, and that is correct.

What matters is the rule from CLAUDE.md: **a critical section holds in-memory
bookkeeping only**. No database call, no broker call, no emit. A greenlet
waiting on a lock cannot yield to the hub, so any I/O inside one stalls the
entire worker. Callers read what they need out of the state, release, and then
do the slow work.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from typing import Any

from utils.logging import get_logger

logger = get_logger(__name__)


# run_id -> the run's live state. Popped by clear_run_state when the run ends,
# which is what keeps this from being an unbounded module-level registry.
_run_state: dict[int, dict[str, Any]] = {}

# run_id -> the lock guarding that run's state. Popped alongside the state.
_state_locks: dict[int, threading.Lock] = {}

# Guards the two dicts above while an entry is being created or removed. Held
# only for the dict operation itself, never across a caller's critical section.
_registry_lock = threading.Lock()


def _lock_for(run_id: int, *, create: bool) -> threading.Lock | None:
    """The lock for one run, created only when asked.

    ``create`` is the whole point. An earlier version created a lock on any
    access, so merely reading the state of a run that had already finished
    registered a lock for its id and never removed it. Any caller that probes
    arbitrary run ids - a stale websocket, a retried request, a scan - would
    grow the registry without bound in a worker that never restarts.
    """
    with _registry_lock:
        lock = _state_locks.get(run_id)
        if lock is None and create:
            lock = threading.Lock()
            _state_locks[run_id] = lock
        return lock


def get_state_lock(run_id: int) -> threading.Lock:
    """The lock for one run, created if it does not exist yet.

    For writers. Readers should use the module's own accessors, which do not
    create a lock for a run that has no state.
    """
    lock = _lock_for(run_id, create=True)
    assert lock is not None  # create=True always returns one
    return lock


@contextmanager
def run_state(run_id: int) -> Iterator[dict[str, Any] | None]:
    """Hold a run's lock and yield its mutable state.

    The state is yielded live, not copied, so mutations inside the block are
    the update. Yields ``None`` when the run has no state, which is the normal
    answer for a run that has already stopped; callers must handle it rather
    than assume.

    Keep the block to in-memory work. See the module docstring.
    """
    lock = _lock_for(run_id, create=False)
    if lock is None:
        # No lock means no state: the run never started here, or has finished
        # and been cleared. Yield the absence rather than minting a lock.
        yield None
        return
    with lock:
        yield _run_state.get(run_id)


def init_run_state(run_id: int, strategy_id: int, legs: list[dict]) -> dict[str, Any]:
    """Create the state for a freshly started run.

    ``legs`` are the resolved legs: each carries the concrete symbol, exchange,
    quantity and the leg's configured risk parameters.
    """
    state: dict[str, Any] = {
        "run_id": run_id,
        "strategy_id": strategy_id,
        "pnl_realized": 0.0,
        "pnl_unrealized": 0.0,
        "pnl_total": 0.0,
        "pnl_peak": 0.0,
        "pnl_trough": 0.0,
        "lock_armed": False,
        "lock_floor": None,
        "trail_to_entry_active": False,
        "tick_source_degraded": False,
        "legs": {str(leg["leg_id"]): _new_leg_state(leg) for leg in legs},
    }
    with get_state_lock(run_id):
        _run_state[run_id] = state
    return state


def _new_leg_state(leg: dict) -> dict[str, Any]:
    """One leg's starting state.

    ``position`` is written unconditionally, for every kind of leg. The
    original omits it on signal-mode legs, and because the evaluator treats
    anything that is not "B" as a short, those legs were evaluated with an
    inverted sign: their P&L, stop and target all pointed the wrong way and the
    stop fired on a favourable move. There is no shape of leg here that is
    allowed to be missing a side.
    """
    position = str(leg.get("position") or "").upper()
    if position not in ("B", "S"):
        # Refusing is better than defaulting: a silent "B" is exactly the bug
        # described above, and it is invisible until money moves.
        raise ValueError(
            f"Leg {leg.get('leg_id')} has an unusable position: {leg.get('position')!r}"
        )

    return {
        "leg_id": leg["leg_id"],
        "position": position,
        "symbol": leg["symbol"],
        "exchange": leg["exchange"],
        "lots": leg.get("lots", 1),
        "qty": leg["quantity"],
        # Order plumbing
        "entry_order_id": None,
        "entry_status": "pending",
        "entry_avg": 0.0,
        "exit_order_id": None,
        "exit_kind": None,
        "exit_avg": None,
        # Live figures
        "ltp": None,
        "mtm": 0.0,
        "realized_pnl": 0.0,
        "status": "configured",
        "tick_source": "ws",
        # Risk levels, filled in on the first tick from the leg's configuration
        "sl_pts": leg.get("sl_pts"),
        "target_pts": leg.get("target_pts"),
        "trail_x": (leg.get("trail") or {}).get("x") or 0,
        "trail_y": (leg.get("trail") or {}).get("y") or 0,
        "effective_sl": None,
        "effective_target": None,
        "trail_active": False,
        # The favourable extreme is stored as a price, in the vocabulary
        # services/risk/ already uses, rather than as points-from-entry. The
        # original stores points and so has to re-derive a price on every tick
        # from an entry that may since have been re-averaged; keeping the price
        # means one ratchet with one meaning. Points from entry are a display
        # value, computed by favorable_peak_points() when the UI wants them.
        "highest_price": None,
        "lowest_price": None,
    }


def favorable_peak_points(leg: dict[str, Any]) -> float:
    """How far the leg has moved in its favour, in points, for display.

    Derived rather than stored, so it cannot disagree with the price ratchet
    the trailing stop actually uses.
    """
    entry = leg.get("entry_avg") or 0.0
    if not entry:
        return 0.0
    if leg.get("position") == "B":
        peak = leg.get("highest_price")
        return max(0.0, float(peak) - float(entry)) if peak else 0.0
    trough = leg.get("lowest_price")
    return max(0.0, float(entry) - float(trough)) if trough else 0.0


def get_run_state(run_id: int) -> dict[str, Any] | None:
    """A deep copy of a run's state, safe to read outside the lock.

    A copy rather than the live dict on purpose: a caller that wants to mutate
    must go through ``run_state`` and hold the lock, and handing out the real
    object makes it far too easy not to.
    """
    lock = _lock_for(run_id, create=False)
    if lock is None:
        return None
    with lock:
        state = _run_state.get(run_id)
        return deepcopy(state) if state is not None else None


def hydrate_run_state(run_id: int, state: dict[str, Any]) -> None:
    """Install a whole state, as recovery does when rebuilding a run."""
    with get_state_lock(run_id):
        _run_state[run_id] = state


def clear_run_state(run_id: int) -> None:
    """Drop a finished run's state and its lock.

    Both, together. Leaving the lock behind would be a small leak per run in a
    process that never restarts.
    """
    with _registry_lock:
        _run_state.pop(run_id, None)
        _state_locks.pop(run_id, None)


def active_run_ids() -> list[int]:
    """Every run this process currently holds state for."""
    with _registry_lock:
        return list(_run_state)


def open_legs(state: dict[str, Any]) -> list[dict[str, Any]]:
    """The legs of a run that are open, and so still carry risk."""
    return [leg for leg in state.get("legs", {}).values() if leg.get("status") == "open"]


def legs_for_symbol(state: dict[str, Any], symbol: str, exchange: str) -> list[dict[str, Any]]:
    """The open legs a tick for this instrument applies to."""
    return [
        leg
        for leg in state.get("legs", {}).values()
        if leg.get("status") == "open"
        and leg.get("symbol") == symbol
        and leg.get("exchange") == exchange
    ]


def subscribed_symbols(state: dict[str, Any]) -> set[tuple[str, str]]:
    """Every ``(symbol, exchange)`` the run needs ticks for."""
    return {
        (leg["symbol"], leg["exchange"])
        for leg in state.get("legs", {}).values()
        if leg.get("status") in ("configured", "open")
    }


def snapshot_for_checkpoint(state: dict[str, Any]) -> dict[str, Any]:
    """The state reduced to what a checkpoint row stores."""
    return {
        "pnl_realized": state.get("pnl_realized", 0.0),
        "pnl_unrealized": state.get("pnl_unrealized", 0.0),
        "pnl_total": state.get("pnl_total", 0.0),
        "pnl_peak": state.get("pnl_peak", 0.0),
        "pnl_trough": state.get("pnl_trough", 0.0),
        "lock_floor": state.get("lock_floor"),
        "trail_to_entry_active": bool(state.get("trail_to_entry_active", False)),
        "leg_state": deepcopy(state.get("legs", {})),
    }
