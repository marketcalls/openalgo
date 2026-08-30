"""Push channel for a live strategy run.

The Detail page polls ``/checkpoints`` every five seconds while a run is
active. Five seconds is a long time to sit in front of a position whose stop is
moving, and the poll costs a request whether or not anything changed. This
module is the other half of that seam: the engine says what happened and the
browser is told over the Socket.IO connection the app already holds.

Nothing here is load bearing for money. A broadcast that fails must never
reach the caller, because every caller is on the risk path: the tick consumer,
the fill handler, the stop path. Every public function swallows its own
failures, logs them, and returns ``False``.

Message kinds
-------------

Six events, all on the default namespace, all addressed to the room
``strategy:{strategy_id}``, and all carrying the same envelope::

    type          one of snapshot | delta | event | order_update
                  | run_update | terminal
    strategy_id   int
    run_id        int | None
    ts            IST ISO 8601 with offset, for display
    ts_ms         epoch milliseconds, for ordering on the client

``strategy_snapshot`` and ``strategy_delta`` then add the run's live figures
and a ``legs`` list. They are the same shape; a snapshot carries every leg,
a delta carries only the open ones, because a leg that is not open cannot have
moved on a tick and the client already has it from the snapshot.

``strategy_event`` adds ``event`` (an ``sm_strategy_event`` row as
``event_to_dict`` returns it), ``strategy_order_update`` adds ``order``
(``order_to_dict``), ``strategy_run_update`` adds ``run`` (``run_to_dict``),
and ``strategy_terminal`` adds ``stop_reason`` and ``pnl_realized``.

The event names are prefixed because ``order_update`` is already taken: the
raw websocket protocol on port 8765 uses it for account-level order updates,
and a client listening on the shared Socket.IO connection would not be able to
tell the two apart.

Rooms
-----

One room per strategy, ``strategy:{id}``. The only existing room convention in
the codebase is ``user_{username}`` in ``blueprints/websocket_example.py``,
which is dormant, lives on a ``/market`` namespace of its own and is scoped to
a user rather than to a thing being watched. A per-strategy room is what lets
a page open on strategy 4 not be woken by strategy 9's ticks. ``room_for`` is
exported so the connect handler that calls ``join_room`` and this module cannot
drift apart.

Threading
---------

Every caller of this module is a greenlet: the tick consumer, the engine, the
scheduler jobs and the request handlers. The one real OS thread in the
strategy package is ``tick_feed.on_tick``, and it never reaches here - it puts
the tick on a real queue and returns.

Emits are still marshalled through ``socketio.start_background_task`` rather
than called inline. Two reasons, both of which matter here more than they do
at the module's other call sites: it keeps the serialisation off the tick
path, and ``start_background_task`` is the async-mode-aware spawn, so if a
caller is ever moved onto a real thread the emit is at least handed to the
Socket.IO server's own machinery rather than run from underneath it. It is not
a substitute for the rule: do not call these functions from a real thread.
"""

from __future__ import annotations

import math
import os
import threading
import time
from datetime import datetime
from typing import Any

import pytz

from extensions import socketio
from services.strategy_module import state
from services.strategy_module.risk_adapter import run_pnl
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "EVENT_DELTA",
    "EVENT_EVENT",
    "EVENT_ORDER_UPDATE",
    "EVENT_RUN_UPDATE",
    "EVENT_SNAPSHOT",
    "EVENT_TERMINAL",
    "NAMESPACE",
    "delta_payload",
    "forget_strategy",
    "has_subscribers",
    "push_delta",
    "push_event",
    "push_order_update",
    "push_run_update",
    "push_snapshot",
    "push_terminal",
    "room_for",
    "snapshot_payload",
]

#: The default namespace. The frontend shares one Socket.IO connection across
#: tabs through ``useSocketContext()``, and that connection is on ``/``.
NAMESPACE = "/"

ROOM_PREFIX = "strategy:"

EVENT_SNAPSHOT = "strategy_snapshot"
EVENT_DELTA = "strategy_delta"
EVENT_EVENT = "strategy_event"
EVENT_ORDER_UPDATE = "strategy_order_update"
EVENT_RUN_UPDATE = "strategy_run_update"
EVENT_TERMINAL = "strategy_terminal"

#: Every trading time in this product is IST. Same zone the scheduler and the
#: signal path use, so a timestamp in a broadcast and one in an event row read
#: the same way.
IST = pytz.timezone("Asia/Kolkata")


def _delta_interval_seconds() -> float:
    """The minimum gap between two throttled deltas, in seconds."""
    raw = os.getenv("STRATEGY_DELTA_MIN_INTERVAL_MS", "100")
    try:
        millis = float(raw)
    except (TypeError, ValueError):
        logger.warning("STRATEGY_DELTA_MIN_INTERVAL_MS is not a number: %r; using 100", raw)
        millis = 100.0
    # Clamped rather than trusted. Zero is a legitimate choice (no throttle);
    # anything above a few seconds is a typo that would look like a dead feed.
    return min(max(millis, 0.0), 5000.0) / 1000.0


#: A liquid option ticks many times a second and a browser cannot paint more
#: than about ten frames of it. Ten per second per strategy is also what bounds
#: the number of background emit tasks this module creates.
DELTA_MIN_INTERVAL_SEC = _delta_interval_seconds()

#: strategy_id -> monotonic time of the last delta admitted for it. Bounded
#: three ways: ``push_terminal`` and ``forget_strategy`` drop a strategy's
#: entry when its run ends, and ``_prune_locked`` sweeps anything that outlives
#: both. See the resource note at the bottom of this module.
_last_delta_at: dict[int, float] = {}

#: Guards the map above, held for the dict operations only. Green under
#: eventlet, which is correct: every caller is a greenlet, and the critical
#: section is arithmetic on a dict with no I/O in it.
_throttle_lock = threading.Lock()

#: How many strategies the throttle map may track before it is swept. A
#: deployment runs a handful of strategies at once; this is a ceiling for a
#: worker that never restarts, not a working size.
MAX_TRACKED_STRATEGIES = 256

#: An entry untouched for this long belongs to a run that ended without saying
#: so. Comfortably longer than any gap between two ticks of a live run.
THROTTLE_IDLE_SEC = 900.0

#: Indirection so tests can drive the clock instead of sleeping. Monotonic,
#: never wall time: the throttle measures an elapsed interval, and a wall clock
#: that steps backwards over an NTP correction or a DST change would freeze the
#: feed for the length of the step.
_clock = time.monotonic

#: Set once if the Socket.IO manager turns out not to expose its rooms, so the
#: warning is not repeated on every tick.
_subscriber_probe_warned = False


# ---------------------------------------------------------------------------
# Rooms and subscribers
# ---------------------------------------------------------------------------


def room_for(strategy_id: int) -> str:
    """The Socket.IO room carrying one strategy's live updates."""
    return f"{ROOM_PREFIX}{strategy_id}"


def _room_size(room: str) -> int | None:
    """How many clients are in a room, or ``None`` when that cannot be told.

    ``python-socketio``'s in-memory manager keeps
    ``server.manager.rooms[namespace][room]`` as a bidict of sid to eio_sid, so
    on this deployment the answer is exact: one Gunicorn worker, no message
    queue, so every client of this instance is in this process's manager.
    """
    server = getattr(socketio, "server", None)
    if server is None:
        # SocketIO has not been bound to the app yet, which happens on import
        # and in any process that is not serving. Nobody can be listening.
        return 0
    rooms = getattr(getattr(server, "manager", None), "rooms", None)
    if not isinstance(rooms, dict):
        return None
    members = rooms.get(NAMESPACE, {}).get(room)
    if members is None:
        return 0
    try:
        return len(members)
    except TypeError:
        return None


def has_subscribers(strategy_id: int) -> bool:
    """Whether any client is watching this strategy.

    The engine calls this before building a payload, so an unwatched run costs
    nothing beyond a dict lookup.

    Fails open. If the manager's shape is ever not what is read above, the
    choice is between a feed that silently goes dead and a few payloads built
    for nobody, and the first is much worse to diagnose.
    """
    global _subscriber_probe_warned
    try:
        size = _room_size(room_for(strategy_id))
    except Exception:
        logger.exception("Could not read the subscriber count for strategy %s", strategy_id)
        return True
    if size is None:
        if not _subscriber_probe_warned:
            _subscriber_probe_warned = True
            logger.warning(
                "The Socket.IO manager does not expose its rooms; "
                "strategy broadcasts will be sent without a subscriber check"
            )
        return True
    return size > 0


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------


def _now_ist() -> datetime:
    """Now, in IST. Separate function so tests can pin it."""
    return datetime.now(IST)


def _num(value: Any) -> float | None:
    """A number as a plain float, or ``None``.

    Non-finite values become ``None`` rather than travelling: ``NaN`` and
    ``Infinity`` are not JSON, and one of them in a frame makes the browser
    throw on the whole frame rather than on the one field.
    """
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _num0(value: Any) -> float:
    """A number as a plain float, with ``None`` read as zero."""
    number = _num(value)
    return 0.0 if number is None else number


def _envelope(kind: str, strategy_id: Any, run_id: Any) -> dict[str, Any]:
    """The fields every message carries.

    ``ts`` is IST for display, matching how the rest of the module renders a
    stored naive-UTC timestamp at its boundary. ``ts_ms`` is epoch
    milliseconds, which is unambiguous and is what the client sorts on: two
    frames from the same millisecond are the only ordering question a push
    channel has, and a formatted local string is the wrong tool for it.
    """
    now = _now_ist()
    return {
        "type": kind,
        "strategy_id": strategy_id,
        "run_id": run_id,
        "ts": now.isoformat(),
        "ts_ms": int(now.timestamp() * 1000),
    }


def _leg_sort_key(leg: dict[str, Any]) -> tuple[int, float, str]:
    """Order legs by id, numerically when the id is a number.

    Stable ordering matters: the client renders the legs as rows, and rows that
    reorder between two frames read as the position having changed.
    """
    value = leg.get("leg_id")
    try:
        return (0, float(value), "")  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return (1, 0.0, str(value))


def _leg_payload(leg: dict[str, Any]) -> dict[str, Any]:
    """One leg, in the shape both a snapshot and a delta use.

    Identical in both on purpose, so the client has one leg type and one render
    path rather than a full one and a partial one that drift.
    """
    return {
        "leg_id": leg.get("leg_id"),
        "symbol": leg.get("symbol"),
        "exchange": leg.get("exchange"),
        "position": leg.get("position"),
        "lots": leg.get("lots"),
        "qty": leg.get("qty"),
        "status": leg.get("status"),
        "entry_status": leg.get("entry_status"),
        "exit_kind": leg.get("exit_kind"),
        "ltp": _num(leg.get("ltp")),
        "entry_avg": _num0(leg.get("entry_avg")),
        "mtm": _num0(leg.get("mtm")),
        "realized_pnl": _num0(leg.get("realized_pnl")),
        "effective_sl": _num(leg.get("effective_sl")),
        "effective_target": _num(leg.get("effective_target")),
        "trail_active": bool(leg.get("trail_active", False)),
        # Derived rather than stored, so it cannot disagree with the price
        # ratchet the trailing stop actually uses.
        "favorable_points": _num0(state.favorable_peak_points(leg)),
        "tick_source": leg.get("tick_source"),
    }


def _figures(run: dict[str, Any]) -> dict[str, Any]:
    """The run's live P&L and its ratchets.

    Realized and unrealized are recomputed from the legs rather than read from
    the ``pnl_*`` fields the aggregate evaluator last wrote. A delta pushed
    after a fill but before the next aggregate pass would otherwise show the
    P&L from before the fill, which is the same defect - a total summed from a
    field written on an earlier pass - that ``run_pnl`` exists to avoid.

    Peak and trough are ratchets only the aggregate evaluator maintains, so
    they are read from the state as stored.
    """
    try:
        realized, unrealized = run_pnl(run)
    except Exception:
        # A leg with an unusable side raises. Falling back keeps a REST caller
        # of snapshot_payload answering instead of returning a 500, and the
        # engine will refuse that leg on its own next pass.
        logger.exception("Could not mark run %s; falling back to its stored P&L", run.get("run_id"))
        realized = _num0(run.get("pnl_realized"))
        unrealized = _num0(run.get("pnl_unrealized"))

    realized = _num0(realized)
    unrealized = _num0(unrealized)
    return {
        "mtm_realized": realized,
        "mtm_unrealized": unrealized,
        "mtm_total": realized + unrealized,
        "peak": _num0(run.get("pnl_peak")),
        "trough": _num0(run.get("pnl_trough")),
        "lock_armed": bool(run.get("lock_armed", False)),
        "lock_floor": _num(run.get("lock_floor")),
        "trail_to_entry_active": bool(run.get("trail_to_entry_active", False)),
        "tick_source_degraded": bool(run.get("tick_source_degraded", False)),
    }


def _state_payload(run_id: int, kind: str, *, open_only: bool) -> dict[str, Any] | None:
    """A snapshot or a delta, built from a copy of the run's state."""
    run = state.get_run_state(run_id)
    if run is None:
        return None

    legs = state.open_legs(run) if open_only else list(run.get("legs", {}).values())
    payload = _envelope(kind, run.get("strategy_id"), run.get("run_id", run_id))
    payload.update(_figures(run))
    payload["legs"] = [_leg_payload(leg) for leg in sorted(legs, key=_leg_sort_key)]
    return payload


def snapshot_payload(run_id: int) -> dict[str, Any] | None:
    """The whole of a run's live state, or ``None`` if it has none.

    Pure: no throttle, no emit, no Socket.IO. The REST route that answers "what
    is this run doing right now" builds its body from exactly this, so a client
    that joins mid-run and a client that has been streaming all session are
    looking at the same shape.
    """
    return _state_payload(run_id, "snapshot", open_only=False)


def delta_payload(run_id: int) -> dict[str, Any] | None:
    """A run's live figures and every open leg, or ``None`` if it has none.

    Every open leg, not only the one whose tick prompted this. With a throttle
    in front, sending just the ticked leg strands the others at whatever they
    last showed: two legs on the same underlying tick in the same second, one
    frame is dropped, and that leg's row sits at a stale price until it happens
    to be the one that survives a window.
    """
    return _state_payload(run_id, "delta", open_only=True)


# ---------------------------------------------------------------------------
# Throttle
#
# The throttle governs deltas and nothing else. A delta is one frame of a
# continuous stream, so dropping one costs nothing: the next frame carries the
# same fields with fresher numbers.
#
# The other four kinds are one-offs. Each describes something that happened
# once, and a client that misses one never learns of it from a later frame:
#
#   order_update  a fill. The position changed size or price.
#   event         a persisted risk event: a stop armed, a floor advanced.
#   run_update    a run row changed.
#   terminal      the run stopped. There is no next frame.
#
# So none of them is throttled. push_delta(force=True) is the same exemption
# for the two deltas that are also one-offs: the one right after a fill, whose
# leg figures have just changed shape, and the last one of a run, which would
# otherwise leave the numbers frozen one tick short of where the run ended.
# ---------------------------------------------------------------------------


def _prune_locked(now: float) -> None:
    """Sweep the throttle map. Caller holds ``_throttle_lock``.

    Only runs when the map is over its ceiling, so the normal path is one
    ``len()``. A run that ends cleanly removes its own entry; this is for the
    ones that do not, in a worker that never restarts.
    """
    if len(_last_delta_at) <= MAX_TRACKED_STRATEGIES:
        return
    for strategy_id in [sid for sid, at in _last_delta_at.items() if now - at > THROTTLE_IDLE_SEC]:
        del _last_delta_at[strategy_id]
    if len(_last_delta_at) > MAX_TRACKED_STRATEGIES:
        # Nothing was stale, so this many strategies really are streaming.
        # Clearing costs one unthrottled delta each and nothing else, which is
        # a better failure than a map that grows for the life of the process.
        logger.warning(
            "Strategy delta throttle is tracking %d strategies; resetting it",
            len(_last_delta_at),
        )
        _last_delta_at.clear()


def _admit_delta(strategy_id: int, *, force: bool) -> bool:
    """Whether this delta may go out now, recording it if so."""
    now = _clock()
    with _throttle_lock:
        _prune_locked(now)
        last = _last_delta_at.get(strategy_id)
        if not force and last is not None and (now - last) < DELTA_MIN_INTERVAL_SEC:
            return False
        # A forced delta stamps the window too. It is a frame the client has
        # just received, so the next throttled one is measured from it.
        _last_delta_at[strategy_id] = now
        return True


def forget_strategy(strategy_id: int) -> None:
    """Drop a strategy's throttle entry.

    Called by ``push_terminal``, and safe to call again from wherever a run is
    finalised, so an entry cannot outlive its run even on a path that never
    reaches a terminal push.
    """
    with _throttle_lock:
        _last_delta_at.pop(strategy_id, None)


# ---------------------------------------------------------------------------
# Emitting
# ---------------------------------------------------------------------------


def _emit_now(event: str, payload: dict[str, Any], room: str) -> None:
    """The emit itself, on whatever background task the server gave us."""
    try:
        socketio.emit(event, payload, to=room, namespace=NAMESPACE)
    except Exception:
        # Two layers of this, because the two live in different places. Under
        # eventlet this body runs in a greenlet of its own, so a raise here
        # would never reach the try in _emit; it would surface as an unhandled
        # greenlet exception with no request context attached to it.
        logger.exception("Strategy broadcast %s to %s failed", event, room)


def _emit(event: str, payload: dict[str, Any], strategy_id: int) -> bool:
    """Hand one message to the Socket.IO server. Never raises."""
    room = room_for(strategy_id)
    try:
        socketio.start_background_task(_emit_now, event, payload, room)
        return True
    except Exception:
        logger.exception("Could not schedule the %s broadcast to %s", event, room)
        return False


def _push(event: str, strategy_id: Any, payload: dict[str, Any] | None) -> bool:
    """Emit one built payload to one strategy's room, if anyone is there."""
    if payload is None:
        return False
    try:
        identifier = int(strategy_id)
    except (TypeError, ValueError):
        logger.warning("Strategy broadcast %s has an unusable strategy id: %r", event, strategy_id)
        return False
    if not has_subscribers(identifier):
        return False
    return _emit(event, payload, identifier)


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def push_snapshot(run_id: int) -> bool:
    """Push a run's whole live state. Not throttled: a snapshot is rare.

    Sent when a client joins, and after anything that changes the shape of the
    run rather than its numbers - a leg opening, a leg closing, a signal-mode
    leg appearing - since those legs leave the delta stream.
    """
    try:
        # Same order as push_delta: the strategy id comes out under the run's
        # own lock, so an unwatched run never pays for the deep copy that
        # building the payload takes.
        with state.run_state(run_id) as run:
            strategy_id = run.get("strategy_id") if run else None
        if strategy_id is None:
            return False

        identifier = int(strategy_id)
        if not has_subscribers(identifier):
            return False

        payload = snapshot_payload(run_id)
        if payload is None:
            return False
        return _emit(EVENT_SNAPSHOT, payload, identifier)
    except Exception:
        logger.exception("Could not push a snapshot for run %s", run_id)
        return False


def push_delta(run_id: int, *, force: bool = False) -> bool:
    """Push a run's live figures and open legs, subject to the throttle.

    ``force`` exempts this frame, for the two deltas that are one-offs: the one
    after a fill, and the last one of a run.
    """
    try:
        # The strategy id is read first, and under the lock rather than through
        # a copy, because both gates in front of the payload need it and
        # neither should pay for a deep copy of a state nobody will be sent.
        with state.run_state(run_id) as run:
            strategy_id = run.get("strategy_id") if run else None
        if strategy_id is None:
            return False

        identifier = int(strategy_id)
        if not has_subscribers(identifier):
            # Deliberately before the throttle. An unwatched run must not
            # consume its own window, or the first delta after a client joins
            # would be dropped for a frame it never saw.
            return False
        if not _admit_delta(identifier, force=force):
            return False

        payload = delta_payload(run_id)
        if payload is None:
            return False
        return _emit(EVENT_DELTA, payload, identifier)
    except Exception:
        logger.exception("Could not push a delta for run %s", run_id)
        return False


def push_event(strategy_id: int, event: dict[str, Any]) -> bool:
    """Push one persisted risk event, as ``event_to_dict`` returns it.

    Never throttled: the event happened once and a later frame does not carry
    it.
    """
    try:
        if not event:
            return False
        payload = _envelope("event", strategy_id, event.get("run_id"))
        payload["event"] = event
        return _push(EVENT_EVENT, strategy_id, payload)
    except Exception:
        logger.exception("Could not push an event for strategy %s", strategy_id)
        return False


def push_order_update(strategy_id: int, order: dict[str, Any]) -> bool:
    """Push one order row, as ``order_to_dict`` returns it.

    Never throttled: a fill is a one-off, and it is the frame the operator is
    watching for.
    """
    try:
        if not order:
            return False
        payload = _envelope("order_update", strategy_id, order.get("run_id"))
        payload["order"] = order
        return _push(EVENT_ORDER_UPDATE, strategy_id, payload)
    except Exception:
        logger.exception("Could not push an order update for strategy %s", strategy_id)
        return False


def push_run_update(strategy_id: int, run: dict[str, Any]) -> bool:
    """Push one run row, as ``run_to_dict`` returns it. Never throttled."""
    try:
        if not run:
            return False
        payload = _envelope("run_update", strategy_id, run.get("id"))
        payload["run"] = run
        return _push(EVENT_RUN_UPDATE, strategy_id, payload)
    except Exception:
        logger.exception("Could not push a run update for strategy %s", strategy_id)
        return False


def push_terminal(
    strategy_id: int, run_id: int, stop_reason: str | None, pnl_realized: float | None
) -> bool:
    """Push the run's last word, and forget its throttle entry.

    Never throttled: there is no next frame to carry it.

    The throttle entry is dropped whether or not the emit went out, so a
    failure to broadcast cannot leave the map holding a finished run.
    """
    try:
        payload = _envelope("terminal", strategy_id, run_id)
        payload["stop_reason"] = stop_reason
        payload["pnl_realized"] = _num0(pnl_realized)
        return _push(EVENT_TERMINAL, strategy_id, payload)
    except Exception:
        logger.exception("Could not push the terminal frame for run %s", run_id)
        return False
    finally:
        try:
            forget_strategy(int(strategy_id))
        except (TypeError, ValueError):
            logger.warning("Terminal frame has an unusable strategy id: %r", strategy_id)


# ---------------------------------------------------------------------------
# Resource surface
#
# One module-level dict, ``_last_delta_at``: one float per strategy that has
# streamed a delta. Removed by push_terminal and by forget_strategy when a run
# ends, and swept by _prune_locked if it ever passes MAX_TRACKED_STRATEGIES.
#
# One green lock, ``_throttle_lock``, module level, never per call.
#
# No database session, no file, no socket, no subprocess and no thread or
# executor of its own. Emits are handed to socketio.start_background_task,
# which under eventlet spawns a greenlet and on the development server a
# short-lived thread; the delta throttle is what bounds how many of those a
# running strategy can create, to one per DELTA_MIN_INTERVAL_SEC plus its
# one-offs.
# ---------------------------------------------------------------------------
