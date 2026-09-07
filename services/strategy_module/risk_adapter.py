"""Bridge between a strategy run's state and the shared risk core.

``services/risk/`` owns the rules: when a stop is hit, when a target is taken,
how a trailing stop ratchets, when a combined limit or a lock-profit floor
breaks. This module owns nothing but the translation, in both directions:

    leg state  ->  PositionRisk   ->  evaluate_position  ->  PositionDecision  ->  leg state
    run state  ->  AggregateRisk  ->  evaluate_aggregate ->  AggregateDecision ->  run state

Keeping the rules out of here is the point. The scalping terminal, Flow and a
REST endpoint evaluate risk through the same core, so a change to how a trail
ratchets reaches all of them at once and cannot drift into a per-surface copy.
The original this is ported from had its own evaluator, which is how four
defects lived in it undetected.

Everything here is pure. No database, no broker, no clock, no logging of state.
Callers hold the run lock across a call and write the result back.
"""

from __future__ import annotations

from typing import Any

from services.risk import (
    AggregateDecision,
    AggregateRisk,
    PositionDecision,
    PositionRisk,
    Side,
    TrailMode,
    aggregate_pnl,
    evaluate_aggregate,
    evaluate_position,
    stop_from_points,
    target_from_points,
    trail_stops_to_entry,
)

# A leg's configured stop and target are points from entry; the core works in
# prices. These two are the only place that conversion happens.
__all__ = [
    "apply_leg_decision",
    "apply_run_decision",
    "leg_to_position_risk",
    "run_pnl",
    "run_to_aggregate_risk",
    "evaluate_leg",
    "evaluate_run",
    "trail_open_legs_to_entry",
]


def _side(position: str) -> Side:
    """A leg's B/S into the core's side.

    Deliberately strict. The original treats anything that is not "B" as a
    short, so a leg that simply forgot to record its side was silently
    evaluated upside down. Here an unusable value raises instead.
    """
    normalised = (position or "").upper()
    if normalised == "B":
        return Side.BUY
    if normalised == "S":
        return Side.SELL
    raise ValueError(f"Unusable leg position: {position!r}")


#: How a leg's risk numbers are expressed. Points is the default and the only
#: value a strategy written before this existed can have.
RISK_UNITS = ("points", "percent")


def _points_per_unit(leg: dict[str, Any], entry: float) -> float:
    """What one configured unit is worth in points for this leg.

    1.0 for a points leg. For a percent leg it is one percent of the entry
    price, so 2 becomes 2% of entry expressed in points.

    An entry of zero returns 0.0, which makes every derived level fall away
    rather than collapse onto the entry itself. A percent of nothing is not a
    stop at the entry price, it is a stop that cannot be computed yet, and the
    leg has no confirmed fill in that state anyway.
    """
    if str(leg.get("risk_unit") or "points").lower() != "percent":
        return 1.0
    return entry / 100.0 if entry > 0 else 0.0


def _in_points(value: Any, scale: float) -> float | None:
    """One configured risk number in points, or None when it is not set."""
    if value is None:
        return None
    try:
        converted = float(value) * scale
    except (TypeError, ValueError):
        return None
    return converted if converted > 0 else None


def leg_to_position_risk(leg: dict[str, Any]) -> PositionRisk:
    """One leg's state as the core's input type.

    The stop and target are taken from the leg's live effective levels when it
    has them, and derived from the configured points when it does not, which is
    the first tick after entry. The initial stop is always the configured one:
    a stepped trail anchors its steps to that level, so handing it the already
    trailed value would compound the advance on every tick.
    """
    side = _side(leg.get("position"))
    entry = float(leg.get("entry_avg") or 0.0)

    # A leg configured in percent is converted to points here and nowhere else.
    # services/risk/ speaks one language, points from entry, and translating
    # into it is the adapter's whole job: a second unit inside the core would
    # mean two ways to express the same stop and two places to get it wrong.
    scale = _points_per_unit(leg, entry)

    sl_pts = _in_points(leg.get("sl_pts"), scale)
    target_pts = _in_points(leg.get("target_pts"), scale)
    initial_stop = stop_from_points(side, entry, sl_pts) if sl_pts else None
    configured_target = target_from_points(side, entry, target_pts) if target_pts else None

    trail_x = _in_points(leg.get("trail_x"), scale) or 0.0
    trail_y = _in_points(leg.get("trail_y"), scale) or 0.0

    return PositionRisk(
        identifier=str(leg.get("leg_id")),
        side=side,
        entry_price=entry,
        quantity=float(leg.get("qty") or 0.0),
        stop_price=leg.get("effective_sl") if leg.get("effective_sl") is not None else initial_stop,
        initial_stop_price=initial_stop,
        target_price=(
            leg.get("effective_target")
            if leg.get("effective_target") is not None
            else configured_target
        ),
        trailing_enabled=trail_x > 0,
        trail_trigger=trail_x,
        # Two shapes of trail, distinguished by whether a step was configured.
        #
        # X alone is a fixed-distance trail: it arms once the leg is X in front
        # and then holds a constant X-point gap behind the favourable extreme.
        # The core expresses that gap as trail_step, so a continuous trail
        # passes X for both the trigger and the step. Passing 0 here, which the
        # points-based configuration invites, disables trailing outright: the
        # core requires a positive step before it will move a stop at all.
        #
        # X with Y arms at X and then advances the configured stop in Y-point
        # steps, which is the core's stepped mode.
        trail_step=trail_y if trail_y > 0 else trail_x,
        trail_mode=TrailMode.STEPPED if trail_y > 0 else TrailMode.CONTINUOUS,
        highest_price=leg.get("highest_price"),
        lowest_price=leg.get("lowest_price"),
    )


def apply_leg_decision(leg: dict[str, Any], decision: PositionDecision) -> None:
    """Write an evaluation back onto the leg, in place.

    Applied whether or not anything breached, because the extremes and the
    trailed stop are ratchets: dropping them on a quiet tick would let the
    stop slide back and give up protection the position already earned.
    """
    leg["effective_sl"] = decision.stop_price
    leg["effective_target"] = decision.target_price
    leg["highest_price"] = decision.highest_price
    leg["lowest_price"] = decision.lowest_price
    leg["mtm"] = decision.pnl
    if decision.trail_armed:
        leg["trail_active"] = True


def evaluate_leg(leg: dict[str, Any], last_price: Any) -> PositionDecision:
    """Evaluate one leg against a tick and write the outcome back."""
    decision = evaluate_position(leg_to_position_risk(leg), last_price)
    if decision.evaluated:
        leg["ltp"] = float(last_price)
    apply_leg_decision(leg, decision)
    return decision


def run_pnl(state: dict[str, Any]) -> tuple[float, float]:
    """A run's realized and unrealized P&L, as ``(realized, unrealized)``.

    Marked from each leg's own entry, quantity and last price rather than from
    a ``mtm`` field written on an earlier pass, so the total cannot be computed
    from a stale per-leg number. Closed legs contribute their realized figure.
    """
    summary = aggregate_pnl(
        [
            {
                "identifier": str(leg.get("leg_id")),
                "side": leg.get("position"),
                "entry_price": leg.get("entry_avg") or 0.0,
                "quantity": leg.get("qty") or 0.0,
                "last_price": leg.get("ltp"),
                # Anything not currently open contributes its realized figure
                # rather than a mark. This is not the same as "status is
                # closed": a signal-mode leg returns to "configured" after an
                # exit so it can be signalled again the same day, and keying
                # on "closed" alone dropped that leg's realized profit out of
                # the run total entirely, leaving every strategy-level rule
                # judged against a number the run never made.
                "closed": leg.get("status") != "open",
                "realized_pnl": leg.get("realized_pnl") or 0.0,
            }
            for leg in state.get("legs", {}).values()
            # A leg that has never traded has nothing to contribute either way.
            if leg.get("status") == "open" or leg.get("realized_pnl")
        ]
    )
    return summary.realized, summary.unrealized


def run_to_aggregate_risk(state: dict[str, Any], strategy: dict[str, Any]) -> AggregateRisk:
    """A run's aggregate limits and ratchets as the core's input type.

    ``overall_sl_mtm`` is stored as a positive number and applied as a negative
    threshold; the core takes it the same way, so it passes through unchanged.

    ``stop_bypassed`` carries the trail-to-entry rule: once one leg's stop has
    fired and every other leg has been moved to break even, the combined stop
    and target stop being evaluated for the rest of the run.
    """
    lock = strategy.get("lock_profit") or {}
    mode = lock.get("mode")
    return AggregateRisk(
        combined_stoploss=strategy.get("overall_sl_mtm"),
        combined_target=strategy.get("overall_target_mtm"),
        lock_profit_at=lock.get("if_profit_reaches"),
        lock_profit_floor=lock.get("lock_profit"),
        # A trail step only means anything in the trailing variant. Passing it
        # through in plain lock mode would turn a static floor into a rising
        # one, which is a different product than the user configured.
        lock_trail_step=lock.get("trail_step") if mode == "lock_and_trail" else None,
        lock_armed=bool(state.get("lock_armed", False)),
        lock_floor=state.get("lock_floor"),
        peak_pnl=float(state.get("pnl_peak") or 0.0),
        trough_pnl=float(state.get("pnl_trough") or 0.0),
        stop_bypassed=bool(state.get("trail_to_entry_active", False)),
    )


def apply_run_decision(state: dict[str, Any], decision: AggregateDecision) -> None:
    """Write an aggregate evaluation back onto the run state, in place.

    Peak and trough are written on every pass, breach or not. The original
    persists them only on one of its several stop paths, so a run closed by an
    overall stop, a target, a lock-profit floor, the scheduler or the kill
    switch recorded peak and trough as zero even though it had real numbers
    all session.
    """
    state["pnl_realized"] = decision.realized_pnl
    state["pnl_unrealized"] = decision.unrealized_pnl
    state["pnl_total"] = decision.total_pnl
    state["pnl_peak"] = decision.peak_pnl
    state["pnl_trough"] = decision.trough_pnl
    state["lock_armed"] = decision.lock_armed
    state["lock_floor"] = decision.lock_floor


def evaluate_run(state: dict[str, Any], strategy: dict[str, Any]) -> AggregateDecision:
    """Evaluate a run's combined limits and write the outcome back."""
    realized, unrealized = run_pnl(state)
    decision = evaluate_aggregate(run_to_aggregate_risk(state, strategy), realized, unrealized)
    apply_run_decision(state, decision)
    return decision


def trail_open_legs_to_entry(state: dict[str, Any], triggering_leg_id: Any) -> list[str]:
    """Move every other open leg's stop to its own entry, and say which moved.

    Fired when one leg's stop hits and the strategy is configured to make the
    rest of the book risk free. The triggering leg is excluded because it is
    about to be closed anyway.

    A manual close must not call this. Moving every other stop is a response to
    the market having gone against the position; an operator closing one leg by
    hand is an override, and treating it as a signal would silently tighten
    every remaining stop.
    """
    legs = [leg for leg in state.get("legs", {}).values() if leg.get("status") == "open"]
    decision = trail_stops_to_entry(
        [leg_to_position_risk(leg) for leg in legs],
        exclude=[str(triggering_leg_id)],
        last_prices={str(leg.get("leg_id")): leg.get("ltp") for leg in legs},
    )

    by_id = {str(leg.get("leg_id")): leg for leg in legs}
    moved: list[str] = []
    for move in decision.moves:
        leg = by_id.get(move.identifier)
        if leg is not None:
            leg["effective_sl"] = move.new_stop
            moved.append(move.identifier)

    if moved:
        state["trail_to_entry_active"] = True
    return moved
