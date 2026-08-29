"""Shared, pure risk evaluation core.

One place where OpenAlgo decides whether a position has hit its stop, taken its
target, earned a tighter trailing stop, or whether a whole set of positions has
run past its combined limits. The scalping terminal, Flow, a strategy engine and
a REST endpoint can all sit on it because of one rule:

    **No I/O of any kind.** No database, no broker, no market data, no logging,
    no clock. Every input arrives as an argument and every decision leaves as a
    return value.

That is what makes the rules testable without a running platform, identical
across four consumers, safe to call from a green thread and from a real one, and
exposable over HTTP without a service layer in between.

Layout
------

* ``models``    frozen value types and the input normalisation
* ``position``  per position stop, target and trailing stop, plus the
                reconciliation notes explaining every behavioural choice
* ``aggregate`` combined stop, combined target, lock profit, trail to entry
* ``adapters``  the legacy ``evaluate_trail`` dict shape, unchanged

The golden vectors in ``test/risk/vectors.json`` are the contract that binds
this core to the TypeScript copy in ``frontend/src/hooks/useTrailingSL.ts``.
Add a case there whenever a rule changes, so the two cannot drift.

Typical use
-----------

    from services.risk import PositionRisk, evaluate_position

    decision = evaluate_position(PositionRisk.from_state(row), ltp)
    if decision.breached:
        exit_now(decision.reason, decision.detail)
    elif decision.stop_moved:
        persist(decision.stop_price)
"""

from services.risk.adapters import evaluate_trail
from services.risk.aggregate import (
    aggregate_pnl,
    evaluate_aggregate,
    evaluate_aggregate_state,
    position_pnl,
    trail_stops_to_entry,
)
from services.risk.models import (
    DEFAULT_TRAIL_TRIGGER,
    AggregateDecision,
    AggregateRisk,
    BreachReason,
    PnLSummary,
    PositionDecision,
    PositionPnL,
    PositionRisk,
    Side,
    StopMove,
    TrailMode,
    TrailToEntryDecision,
    side_from_quantity,
    stop_from_points,
    target_from_points,
)
from services.risk.position import (
    evaluate_position,
    evaluate_position_state,
    validate_position,
)

__all__ = [
    "DEFAULT_TRAIL_TRIGGER",
    "AggregateDecision",
    "AggregateRisk",
    "BreachReason",
    "PnLSummary",
    "PositionDecision",
    "PositionPnL",
    "PositionRisk",
    "Side",
    "StopMove",
    "TrailMode",
    "TrailToEntryDecision",
    "aggregate_pnl",
    "evaluate_aggregate",
    "evaluate_aggregate_state",
    "evaluate_position",
    "evaluate_position_state",
    "evaluate_trail",
    "position_pnl",
    "side_from_quantity",
    "stop_from_points",
    "target_from_points",
    "trail_stops_to_entry",
    "validate_position",
]
