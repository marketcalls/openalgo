"""State machine for strategy runs and individual legs.

Transitions are validated against the tables below and applied with an atomic
UPDATE-WHERE so concurrent attempts to transition from the same source state
race-safely (only one wins; the other gets a no-op result).

Every successful transition publishes a StrategyStateChangedEvent on the bus.
The audit subscriber writes the strategy_events row; the socketio subscriber
emits to the UI; the telegram subscriber alerts on loud states. The engine
itself never writes to strategy_events directly.

Run states (see plan §3.3):
    DRAFT       — UI-only, never persisted as a run row
    ARMED       — waiting for entry signal
    ENTERING    — entry orders submitted, awaiting fills
    IN_TRADE    — RMS active
    EXITING     — exit orders submitted; engine stops monitoring new triggers
    CLOSED      — terminal; all legs flat
    ENTRY_FAILED — broker rejected entries
    EXIT_FAILED — broker rejected/partial exit
    ERRORED     — engine exception
    STOPPED     — user manual abort

Leg states (per-leg within a run):
    PENDING_ENTRY → OPEN → EXITING_LEG → CLOSED
                  → ENTRY_REJECTED  (rare)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Iterable, Optional, Tuple

from sqlalchemy import update

from database.strategy_v2_db import StrategyPosition, StrategyRun, db_session
from events.strategy_events import StrategyStateChangedEvent
from utils.event_bus import bus
from utils.logging import get_logger

logger = get_logger(__name__)


# ----------------------------------------------------------------------------
# Run-state transition table
# ----------------------------------------------------------------------------

# Each entry: source state -> set of legal target states
_RUN_TRANSITIONS: dict[str, set[str]] = {
    "ARMED": {"ENTERING", "STOPPED", "ERRORED"},
    "ENTERING": {"IN_TRADE", "ENTRY_FAILED", "ERRORED", "STOPPED"},
    "IN_TRADE": {"EXITING", "ERRORED", "STOPPED"},
    "EXITING": {"CLOSED", "EXIT_FAILED", "ERRORED"},
    # Terminal states — no outgoing transitions.
    "CLOSED": set(),
    "ENTRY_FAILED": set(),
    "EXIT_FAILED": set(),
    "ERRORED": set(),
    "STOPPED": set(),
}

TERMINAL_RUN_STATES = frozenset({"CLOSED", "ENTRY_FAILED", "EXIT_FAILED", "ERRORED", "STOPPED"})

ACTIVE_RUN_STATES = frozenset({"ARMED", "ENTERING", "IN_TRADE", "EXITING"})


def is_valid_run_transition(old: str, new: str) -> bool:
    return new in _RUN_TRANSITIONS.get(old, set())


def allowed_next_run_states(old: str) -> Iterable[str]:
    return tuple(sorted(_RUN_TRANSITIONS.get(old, set())))


# ----------------------------------------------------------------------------
# Leg-state transition table
# ----------------------------------------------------------------------------

_LEG_TRANSITIONS: dict[str, set[str]] = {
    "PENDING_ENTRY": {"OPEN", "ENTRY_REJECTED"},
    "OPEN": {"EXITING_LEG", "CLOSED"},  # CLOSED if leg exits in one step (e.g., basket close-all)
    "EXITING_LEG": {"CLOSED"},
    "CLOSED": set(),
    "ENTRY_REJECTED": set(),
}

TERMINAL_LEG_STATES = frozenset({"CLOSED", "ENTRY_REJECTED"})


def is_valid_leg_transition(old: str, new: str) -> bool:
    return new in _LEG_TRANSITIONS.get(old, set())


# ----------------------------------------------------------------------------
# Apply a run transition (atomic, race-safe)
# ----------------------------------------------------------------------------


class TransitionError(RuntimeError):
    """Raised when a transition is rejected (race lost or invalid)."""


def transition_run(
    run_id: int,
    expected_old: str,
    new_state: str,
    *,
    reason: str = "",
    strategy_id: Optional[int] = None,
    extra_columns: Optional[dict] = None,
) -> bool:
    """Atomically transition strategy_runs.state from `expected_old` to `new_state`.

    Race-safe: the UPDATE has WHERE state=expected_old, so concurrent attempts
    from the same source state race; only one succeeds. The loser sees
    rowcount==0 and the function returns False.

    On success, publishes StrategyStateChangedEvent. The audit subscriber
    persists the strategy_events row; the engine does NOT write that table.

    Args:
        run_id:        strategy_runs.id
        expected_old:  the state we expect the run to currently be in
        new_state:     the target state
        reason:        human-readable label propagated to the event payload
        strategy_id:   if known, populates the published event; else fetched
        extra_columns: additional column values to set in the same UPDATE
                       (e.g. exit_reason, entered_at, exited_at)

    Returns:
        True if the row was updated; False if the race was lost or the row
        didn't match (likely already advanced by another caller).

    Raises:
        TransitionError if the requested transition is not in the table.
    """
    if not is_valid_run_transition(expected_old, new_state):
        raise TransitionError(
            f"Invalid run transition {expected_old!r} → {new_state!r}. "
            f"Allowed from {expected_old!r}: {allowed_next_run_states(expected_old)}"
        )

    values = {"state": new_state}
    if extra_columns:
        values.update(extra_columns)
    if new_state == "CLOSED" and "exited_at" not in values:
        values["exited_at"] = datetime.now(timezone.utc)
    if new_state == "IN_TRADE" and "entered_at" not in values:
        values["entered_at"] = datetime.now(timezone.utc)

    stmt = (
        update(StrategyRun)
        .where(StrategyRun.id == run_id, StrategyRun.state == expected_old)
        .values(**values)
    )
    result = db_session.execute(stmt)
    db_session.commit()

    if result.rowcount == 0:
        logger.info(
            "transition_run race-lost: run_id=%s expected=%s target=%s",
            run_id,
            expected_old,
            new_state,
        )
        return False

    if strategy_id is None:
        row = db_session.query(StrategyRun.strategy_id).filter(StrategyRun.id == run_id).first()
        strategy_id = row[0] if row else 0

    bus.publish(
        StrategyStateChangedEvent(
            strategy_id=strategy_id,
            run_id=run_id,
            old_state=expected_old,
            new_state=new_state,
            reason=reason,
        )
    )
    return True


def transition_leg(
    position_id: int,
    expected_old: str,
    new_state: str,
) -> bool:
    """Atomically transition strategy_positions.leg_state."""
    if not is_valid_leg_transition(expected_old, new_state):
        raise TransitionError(
            f"Invalid leg transition {expected_old!r} → {new_state!r}"
        )

    stmt = (
        update(StrategyPosition)
        .where(
            StrategyPosition.id == position_id,
            StrategyPosition.leg_state == expected_old,
        )
        .values(leg_state=new_state)
    )
    result = db_session.execute(stmt)
    db_session.commit()
    if result.rowcount == 0:
        logger.info(
            "transition_leg race-lost: position_id=%s expected=%s target=%s",
            position_id,
            expected_old,
            new_state,
        )
        return False
    return True


def has_active_run(strategy_id: int, leg_id: int | None = None) -> bool:
    """True if the strategy currently has any run in an active state.

    Phase 13 — accepts an optional leg_id for per-leg scoping (CASH per-
    symbol routing). When leg_id is provided we look only for runs
    pinned to that leg; pack-style F&O runs (leg_id IS NULL) are ignored.
    When leg_id is None we look at strategy-level pack runs only.

    Not race-free on its own — the unique partial index
    `idx_strategy_runs_active_per_leg` is the actual enforcement; this
    is the friendly preflight check.
    """
    q = (
        db_session.query(StrategyRun.id)
        .filter(StrategyRun.strategy_id == strategy_id)
        .filter(StrategyRun.state.in_(ACTIVE_RUN_STATES))
    )
    if leg_id is None:
        q = q.filter(StrategyRun.leg_id.is_(None))
    else:
        q = q.filter(StrategyRun.leg_id == leg_id)
    return db_session.query(q.exists()).scalar()


def find_active_run(strategy_id: int, leg_id: int | None = None) -> int | None:
    """Return the id of the current active run for this (strategy, leg)
    or None if no active run exists. Same scoping rules as has_active_run.
    Used by the per-symbol exit path to look up the run to close."""
    q = (
        db_session.query(StrategyRun.id)
        .filter(StrategyRun.strategy_id == strategy_id)
        .filter(StrategyRun.state.in_(ACTIVE_RUN_STATES))
    )
    if leg_id is None:
        q = q.filter(StrategyRun.leg_id.is_(None))
    else:
        q = q.filter(StrategyRun.leg_id == leg_id)
    row = q.order_by(StrategyRun.id.desc()).first()
    return row[0] if row else None


def serialize_state_change(
    strategy_id: int,
    run_id: int,
    old_state: str,
    new_state: str,
    reason: str,
) -> str:
    """Helper for tests / logging — JSON-serialize a state transition payload."""
    return json.dumps(
        {
            "strategy_id": strategy_id,
            "run_id": run_id,
            "old_state": old_state,
            "new_state": new_state,
            "reason": reason,
        },
        sort_keys=True,
    )
