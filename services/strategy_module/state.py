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
import uuid
from collections.abc import Iterable, Iterator
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
        # Set after the stop request is durable and before any broker/API-key
        # work.  Entry claims consult this under the same run lock, closing the
        # window between a signal's database check and its eventual dispatch.
        "stopping": False,
        # At most one in-flight signal entry decision per configured leg. The
        # map lives and dies with the run and is keyed only by validated leg id.
        "signal_entry_claims": {},
        "legs": {str(leg["leg_id"]): _new_leg_state(leg) for leg in legs},
    }
    with get_state_lock(run_id):
        _run_state[run_id] = state
    return state


def new_position_ref() -> str:
    """Return an opaque durable identity for one position incarnation."""
    return uuid.uuid4().hex


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
        "position_ref": leg.get("position_ref"),
        "entry_order_id": None,
        "entry_status": "pending",
        "entry_filled_qty": 0,
        "entry_avg": 0.0,
        "exit_order_id": None,
        "exit_claim_token": None,
        "exit_kind": None,
        "exit_avg": None,
        # Live figures
        "ltp": None,
        "mtm": 0.0,
        "realized_pnl": 0.0,
        "status": "configured",
        "tick_source": "ws",
        # Risk levels, filled in on the first tick from the leg's configuration
        # Points or percent. Read by risk_adapter, which is the only place
        # that converts, so the core never sees a unit at all.
        "risk_unit": leg.get("risk_unit") or "points",
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
        # Set only while a flip's outgoing position is still unfilled. See
        # add_leg for why this leg id can name two positions at once.
        "superseded": None,
    }


def claim_leg_exit(run_id: int, leg_id: Any, kind: str) -> dict[str, Any] | None:
    """Claim a leg for exit, or return None if it must not be exited again.

    The claim and the check happen under one lock hold, which is the whole
    point. Both callers used to set ``exit_kind`` at claim time and then test
    ``exit_order_id``, which is only written after the dispatch returns: two
    rules firing on the same leg before the first order came back both passed
    the guard and sent a covering order each, leaving the account positioned
    the opposite way. The same test also failed open when ``record_order``
    could not write its row, because ``exit_order_id`` was then set to None.

    ``exit_kind`` is the marker instead: written here, under the lock, before
    any dispatch, and cleared only by ``release_leg_exit`` when the broker
    refused. It cannot be defeated by timing or by a database failure.

    Returns a copy of the leg to dispatch from, so the caller does its order
    building and its network call outside the lock.
    """
    # create=False: a dispatch can outlive the run it belongs to, and creating
    # a lock here would register one for a run id that no longer has state and
    # that nothing ever removes. That is the leak _lock_for was given its
    # create flag for; a run with no lock has no state either way.
    lock = _lock_for(run_id, create=False)
    if lock is None:
        return None
    with lock:
        state = _run_state.get(run_id)
        if state is None:
            return None
        leg = state["legs"].get(str(leg_id))
        if leg is None or leg.get("status") != "open":
            return None
        if leg.get("entry_status") != "complete":
            # Accepted by the broker but not yet filled. A leg is "open" from
            # the moment its entry is accepted, so exiting here sends the full
            # quantity the other way against a position that may be nothing at
            # all: if the entry then cancels or rejects, that square-off is
            # itself a naked position in the reverse direction. Nothing is
            # confirmed to close, so nothing is closed. The caller reports it
            # rather than treating it as flat, so the run stays managed and the
            # stop can be retried once the fill lands.
            return None
        if (
            leg.get("exit_kind") is not None
            or leg.get("exit_claim_token") is not None
            or leg.get("exit_order_id") is not None
        ):
            return None
        leg["exit_kind"] = kind
        leg["exit_claim_token"] = new_position_ref()
        return dict(leg)


def claim_signal_entry(run_id: int, leg_id: Any, position: str) -> dict[str, Any] | None:
    """Claim one bounded signal entry decision before any external I/O."""
    lock = _lock_for(run_id, create=False)
    if lock is None:
        return None
    with lock:
        run = _run_state.get(run_id)
        if run is None:
            return None
        if run.get("stopping"):
            return {"note": "run_stopping"}
        key = str(leg_id)
        claims = run.setdefault("signal_entry_claims", {})
        if key in claims:
            return {"note": "flip_pending"}

        leg = run["legs"].get(str(leg_id)) if run else None
        requested = str(position or "").upper()
        live_position = leg.get("position") if leg and leg.get("status") == "open" else None
        superseded = leg.get("superseded") if leg else None

        if live_position == requested:
            return {"note": "already_long" if requested == "B" else "already_short"}
        if live_position is not None and superseded is not None:
            return {"note": "flip_pending"}
        if superseded and superseded.get("position") == requested:
            return {"note": "already_long" if requested == "B" else "already_short"}
        if superseded is not None:
            return {"note": "flip_pending"}
        if live_position is not None and (
            leg.get("exit_kind") is not None
            or leg.get("exit_claim_token") is not None
            or leg.get("exit_order_id") is not None
        ):
            return {"note": "flip_pending"}

        claim = {
            "claim_token": new_position_ref(),
            "position_ref": new_position_ref(),
            "position": requested,
            "held_position": live_position,
            "expected_position_ref": leg.get("position_ref") if leg else None,
        }
        claims[key] = claim
        return dict(claim)


def release_signal_entry_claim(run_id: int, leg_id: Any, claim_token: Any) -> bool:
    """Release only the signal-entry decision carrying this unique token."""
    lock = _lock_for(run_id, create=False)
    if lock is None:
        return False
    with lock:
        run = _run_state.get(run_id)
        claims = run.get("signal_entry_claims", {}) if run else {}
        key = str(leg_id)
        claim = claims.get(key)
        if not claim or claim.get("claim_token") != claim_token:
            return False
        claims.pop(key, None)
        return True


def claim_legs_for_exit(
    run_id: int, leg_ids: Iterable[Any], kind: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Claim every exitable leg and name the ones that cannot be, in one hold.

    Returns ``(claimed, unfilled)``. A leg is claimed when it is open, has a
    confirmed entry fill, and has no exit already in flight; it is reported as
    unfilled when it is open but its entry has only been accepted.

    One lock hold for both, deliberately. Claiming under one and classifying
    under another leaves a window the width of a database round trip: a fill
    landing inside it makes the leg exitable after the claim pass has skipped
    it and no longer unfilled when the classify pass looks, so it appears in
    neither list. The caller then finalises the run believing there was
    nothing to exit, while the position is open at the broker with nothing
    watching it.
    """
    claimed: list[dict[str, Any]] = []
    unfilled: list[dict[str, Any]] = []

    lock = _lock_for(run_id, create=False)
    if lock is None:
        return claimed, unfilled
    with lock:
        state = _run_state.get(run_id)
        if state is None:
            return claimed, unfilled
        for leg_id in leg_ids:
            leg = state["legs"].get(str(leg_id))
            if leg is None or leg.get("status") != "open":
                continue
            if (
                leg.get("exit_kind") is not None
                or leg.get("exit_claim_token") is not None
                or leg.get("exit_order_id") is not None
            ):
                continue
            if leg.get("entry_status") != "complete":
                unfilled.append(dict(leg))
                continue
            leg["exit_kind"] = kind
            leg["exit_claim_token"] = new_position_ref()
            claimed.append(dict(leg))
    return claimed, unfilled


def release_superseded_exit(run_id: int, leg_id: Any, exit_order_id: Any) -> bool:
    """Mark a flip's outgoing exit as no longer in flight. Says whether it matched.

    A flip squares the held side and opens the other immediately, so until the
    closing order fills the leg keeps the outgoing position under
    ``superseded``. If that closing order is then rejected, the outgoing
    position is still held: both sides are on the book, and the leg itself
    describes only the new one. Clearing the dead order id is what lets the old
    side be closed again.
    """
    if exit_order_id is None:
        return False
    lock = _lock_for(run_id, create=False)
    if lock is None:
        return False
    with lock:
        state = _run_state.get(run_id)
        leg = state["legs"].get(str(leg_id)) if state else None
        superseded = leg.get("superseded") if leg else None
        if not superseded or exit_order_id not in {
            superseded.get("exit_claim_token"),
            superseded.get("exit_order_id"),
        }:
            return False
        superseded["exit_order_id"] = None
        superseded["exit_claim_token"] = None
        superseded["exit_kind"] = None
        return True


def release_order_exit(
    run_id: int,
    leg_id: Any,
    exit_order_id: Any,
    position_ref: str | None,
) -> str | None:
    """Release the exact live or superseded owner of one terminal order row."""
    lock = _lock_for(run_id, create=False)
    if lock is None:
        return None
    with lock:
        run = _run_state.get(run_id)
        leg = run["legs"].get(str(leg_id)) if run else None
        if leg is None:
            return None
        superseded = leg.get("superseded")
        if (
            superseded
            and superseded.get("exit_order_id") == exit_order_id
            and (position_ref is None or superseded.get("position_ref") == position_ref)
        ):
            superseded["exit_order_id"] = None
            superseded["exit_claim_token"] = None
            superseded["exit_kind"] = None
            return "superseded"
        if leg.get("exit_order_id") == exit_order_id and (
            position_ref is None or leg.get("position_ref") == position_ref
        ):
            leg["exit_order_id"] = None
            leg["exit_claim_token"] = None
            leg["exit_kind"] = None
            return "live"
        return None


def bind_superseded_exit(run_id: int, leg_id: Any, claim_token: Any, order_row_id: int) -> bool:
    """Replace one outgoing-position claim with its durable order-row id."""
    lock = _lock_for(run_id, create=False)
    if lock is None:
        return False
    with lock:
        run = _run_state.get(run_id)
        leg = run["legs"].get(str(leg_id)) if run else None
        superseded = leg.get("superseded") if leg else None
        if (
            claim_token is None
            or not superseded
            or superseded.get("exit_claim_token") != claim_token
        ):
            return False
        superseded["exit_order_id"] = order_row_id
        return True


def claim_superseded_exit(run_id: int, leg_id: Any, position: str) -> dict[str, Any] | None:
    """Claim a flip's outgoing position for a fresh exit, if it is still held.

    Returns a snapshot to dispatch from, carrying the outgoing side and size,
    or None when there is no such position or an exit for it is already in
    flight. The symbol comes from the leg, because a flip is a reversal on the
    same contract.
    """
    lock = _lock_for(run_id, create=False)
    if lock is None:
        return None
    with lock:
        state = _run_state.get(run_id)
        leg = state["legs"].get(str(leg_id)) if state else None
        superseded = leg.get("superseded") if leg else None
        if not superseded or (
            superseded.get("exit_claim_token") is not None
            or superseded.get("exit_order_id") is not None
        ):
            return None
        if str(superseded.get("position") or "").upper() != str(position or "").upper():
            return None
        # Marked in flight straight away, under the same hold, so two alerts
        # cannot each send a covering order for the one outgoing position.
        claim_token = new_position_ref()
        superseded["exit_claim_token"] = claim_token
        return {
            "leg_id": leg["leg_id"],
            "position": superseded["position"],
            "position_ref": superseded.get("position_ref"),
            "entry_order_id": superseded.get("entry_order_id"),
            "claim_token": claim_token,
            "symbol": leg["symbol"],
            "exchange": leg["exchange"],
            "quantity": superseded.get("qty"),
            "entry_avg": superseded.get("entry_avg"),
        }


def bind_live_exit(
    run_id: int,
    leg_id: Any,
    claim_token: Any,
    order_row_id: int,
    position_ref: str | None,
) -> bool:
    """Bind a durable row to the exact live-exit claim before dispatch."""
    lock = _lock_for(run_id, create=False)
    if lock is None:
        return False
    with lock:
        run = _run_state.get(run_id)
        leg = run["legs"].get(str(leg_id)) if run else None
        if (
            leg is None
            or claim_token is None
            or leg.get("exit_claim_token") != claim_token
            or leg.get("exit_order_id") is not None
            or (position_ref is not None and leg.get("position_ref") != position_ref)
        ):
            return False
        leg["exit_order_id"] = order_row_id
        return True


def release_leg_exit(run_id: int, leg_id: Any, claim_id: Any) -> bool:
    """Undo only the exact live-exit claim whose order was refused.

    Without this the leg is skipped by every later exit attempt for the rest of
    the session: its stop loss, its target, the scheduler square-off and the
    operator's own Close button all pass over it while the position is still
    held at the broker.
    """
    if claim_id is None:
        return False
    lock = _lock_for(run_id, create=False)
    if lock is None:
        return False
    with lock:
        state = _run_state.get(run_id)
        if state is None:
            return False
        leg = state["legs"].get(str(leg_id))
        if leg is None or claim_id not in {
            leg.get("exit_claim_token"),
            leg.get("exit_order_id"),
        }:
            return False
        leg["exit_kind"] = None
        leg["exit_claim_token"] = None
        leg["exit_order_id"] = None
        return True


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


def mark_stopping(run_id: int) -> bool:
    """Block new signal entries for a durably requested stop.

    Pure in-memory bookkeeping under the run lock. The caller persists the
    request first, so a process death cannot forget a stop that state observed.
    """
    lock = _lock_for(run_id, create=False)
    if lock is None:
        return False
    with lock:
        run = _run_state.get(run_id)
        if run is None:
            return False
        run["stopping"] = True
        return True


def add_leg(
    run_id: int,
    leg: dict,
    claim_token: Any,
    expected_position_ref: str | None,
    entry_order_id: int,
) -> dict[str, Any] | None:
    """Install a claimed signal leg only over its exact expected owner.

    Batch runs seed every leg at start, because a batch enters them all at
    once and its sides are known from the configuration. A signal-mode leg
    does not exist here until a signal opens it: its side is decided by which
    signal arrived, not by what was configured, and inventing a placeholder
    side beforehand is exactly the defect this module refuses elsewhere.
    """
    lock = _lock_for(run_id, create=False)
    if lock is None:
        return None
    with lock:
        state = _run_state.get(run_id)
        if state is None:
            return None
        if state.get("stopping"):
            return None
        key = str(leg["leg_id"])
        claim = state.get("signal_entry_claims", {}).get(key)
        if (
            not claim
            or claim.get("claim_token") != claim_token
            or claim.get("position_ref") != leg.get("position_ref")
            or claim.get("expected_position_ref") != expected_position_ref
        ):
            return None
        previous = state["legs"].get(key)
        current_position_ref = previous.get("position_ref") if previous else None
        if current_position_ref != expected_position_ref:
            return None
        if previous is not None and previous.get("superseded") is not None:
            return None

        leg_state = _new_leg_state(leg)
        leg_state["entry_order_id"] = entry_order_id
        if claim.get("held_position") is not None and previous is not None:
            if previous.get("status") == "open" and (
                previous.get("exit_kind") is None or previous.get("exit_claim_token") is None
            ):
                return None
            # A flip squares the held side and opens the other one straight
            # away, so for as long as the closing order is unfilled this leg id
            # names two positions. Overwriting wholesale lost the outgoing
            # one's order id, and because a fill is matched on (run, leg) the
            # old long's exit fill then closed the new short: it vanished from
            # open_legs, no stop was evaluated for it, no square-off would
            # reach it, and the broker still held it. Keep what is needed to
            # settle the outgoing position when its fill arrives.
            if previous.get("status") == "open":
                leg_state["superseded"] = {
                    "exit_order_id": previous.get("exit_order_id"),
                    "exit_claim_token": previous.get("exit_claim_token"),
                    "exit_kind": previous.get("exit_kind"),
                    "entry_order_id": previous.get("entry_order_id"),
                    "position_ref": previous.get("position_ref"),
                    "position": previous.get("position"),
                    "entry_avg": previous.get("entry_avg"),
                    "qty": previous.get("qty"),
                }
        if previous is not None:
            # A signal leg is re-entered on the same id after it has been
            # closed, and a fresh state would reset realized_pnl to zero. That
            # figure is what overall_sl_mtm, overall_target_mtm and the
            # lock-profit floor are judged against, so zeroing it turns a daily
            # loss limit into a per-round-trip one: a strategy that loses 1000
            # five times never reaches a 5000 limit. Carry it forward.
            leg_state["realized_pnl"] = float(previous.get("realized_pnl") or 0.0)
        state["legs"][key] = leg_state
        return leg_state


def finish_signal_entry(
    run_id: int,
    leg_id: Any,
    position_ref: str,
    claim_token: Any,
    accepted: bool,
) -> bool:
    """Apply one entry acknowledgement only to its installed incarnation."""
    lock = _lock_for(run_id, create=False)
    if lock is None:
        return False
    with lock:
        run = _run_state.get(run_id)
        leg = run["legs"].get(str(leg_id)) if run else None
        claim = run.get("signal_entry_claims", {}).get(str(leg_id)) if run else None
        if (
            leg is None
            or leg.get("position_ref") != position_ref
            or not claim
            or claim.get("claim_token") != claim_token
        ):
            return False
        if leg.get("entry_status") == "pending":
            leg["entry_status"] = "open" if accepted else "rejected"
            leg["status"] = "open" if accepted else "rejected"
        run["signal_entry_claims"].pop(str(leg_id), None)
        return True


def reject_entry_intent(run_id: int, leg_id: Any, position_ref: str | None) -> bool:
    """Make one exact batch placeholder non-managed when intent persistence fails.

    The broker was never called, so the configured placeholder cannot become
    exposure. Matching the position reference prevents a delayed failure from
    rejecting a newer incarnation that reused the same leg id.
    """
    lock = _lock_for(run_id, create=False)
    if lock is None:
        return False
    with lock:
        run = _run_state.get(run_id)
        leg = run["legs"].get(str(leg_id)) if run else None
        if leg is None or leg.get("position_ref") != position_ref:
            return False
        if leg.get("entry_status") == "complete":
            return False
        leg["entry_order_id"] = None
        leg["entry_status"] = "rejected"
        leg["status"] = "rejected"
        return True


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
