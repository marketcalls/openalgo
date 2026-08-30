"""Aggregate risk across a set of positions: combined stop, combined target,
lock profit and trail to entry. Pure, no I/O.

Layer order on every evaluation, which is openbull's order and the order
docs/plan/strategy-module.md section 9 describes:

  1. Mark to market, summed from the per position values.
  2. Lock profit. Arms once profit reaches a threshold, then holds a floor that
     only ever rises. It runs first because its floor sits above the combined
     stop, so it is the tighter rule whenever it is armed.
  3. Combined stop, then combined target.

Two deliberate departures from openbull's ``evaluate_strategy``:

* When trail to entry has fired, openbull's code bypasses the combined stop AND
  the combined target, while its own spec (section 9.2) bypasses only the stop.
  The spec is right. Trail to entry is a risk reduction event: every remaining
  position is at worst flat, so the combined stop is redundant, but there is no
  reason to stop honouring a profit target, and disabling it means a set that
  later reaches its target never closes. Only the stop is bypassed here, via
  ``AggregateRisk.stop_bypassed``.

* openbull builds user facing sentences with rupee symbols inside the pure
  core. Formatting is presentation. This module returns numbers and enum
  reasons plus one plain text ``detail`` line, and the caller renders.

Costs are not modelled. Every amount here is gross mark to market, so a
combined stop of 5000 stops at 5000 before brokerage, taxes and slippage. A
caller that needs net should subtract its own cost estimate from the realized
and unrealized figures it passes in.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from services.risk.models import (
    AggregateDecision,
    AggregateRisk,
    BreachReason,
    PnLSummary,
    PositionPnL,
    PositionRisk,
    Side,
    StopMove,
    TrailToEntryDecision,
    as_price,
    format_price,
    is_price,
    normalise_side,
)


def position_pnl(side: Any, entry_price: float, quantity: float, last_price: Any) -> float:
    """Mark to market for one open position. Zero when it cannot be marked."""
    if not is_price(entry_price) or not is_price(last_price) or not quantity:
        return 0.0
    entry = float(entry_price)
    ltp = float(last_price)
    magnitude = abs(float(quantity))
    if normalise_side(side) is Side.BUY:
        return (ltp - entry) * magnitude
    return (entry - ltp) * magnitude


def aggregate_pnl(positions: Iterable[PositionPnL | Mapping[str, Any]]) -> PnLSummary:
    """Sum realized and unrealized mark to market across a set of positions.

    Unlike openbull's ``compute_strategy_mtm``, which reads a ``mtm`` field the
    caller wrote on a previous pass, this marks open positions from their own
    entry, quantity and last price. There is no way for the aggregate to be
    computed from a stale per position number it did not derive itself.
    """
    realized = 0.0
    unrealized = 0.0
    priced = 0
    unpriced = 0
    for item in positions:
        entry = item if isinstance(item, PositionPnL) else PositionPnL.from_state(item)
        # Realized is realized whether or not the position happens to be open
        # right now. A position re-entered after a completed round trip carries
        # that round trip's result and is open again; counting it only while
        # closed made the figure vanish the moment the next entry was placed,
        # so a daily loss limit reset on every flat moment and could never be
        # reached. An always-open position simply carries zero here.
        realized += entry.realized_pnl
        if entry.closed:
            continue
        if not is_price(entry.last_price) or not is_price(entry.entry_price):
            unpriced += 1
            continue
        priced += 1
        unrealized += position_pnl(entry.side, entry.entry_price, entry.quantity, entry.last_price)
    return PnLSummary(
        realized=realized,
        unrealized=unrealized,
        total=realized + unrealized,
        priced=priced,
        unpriced=unpriced,
    )


def evaluate_aggregate(
    risk: AggregateRisk, realized_pnl: float, unrealized_pnl: float
) -> AggregateDecision:
    """Judge the whole set against its combined limits.

    ``realized_pnl`` and ``unrealized_pnl`` arrive as values so the caller can
    source them from :func:`aggregate_pnl`, from
    services/strategy_pnl_service.py, or from a broker's own position book,
    without this module ever knowing which.
    """
    total = float(realized_pnl) + float(unrealized_pnl)
    peak = max(risk.peak_pnl, total)
    trough = min(risk.trough_pnl, total)

    lock_armed = risk.lock_armed
    lock_floor = risk.lock_floor
    armed_now = False
    floor_raised = False

    if risk.lock_profit_at is not None:
        if not lock_armed and total >= risk.lock_profit_at:
            lock_armed = True
            armed_now = True
        if lock_armed:
            # Floor candidates: the configured floor, whatever the floor already
            # is, and for a trailing lock the peak less the give back. The max
            # of those is what makes the floor a ratchet that never falls back.
            base = risk.lock_profit_floor if risk.lock_profit_floor is not None else 0.0
            candidates = [base]
            if lock_floor is not None:
                candidates.append(lock_floor)
            if risk.lock_trail_step is not None and risk.lock_trail_step > 0.0:
                candidates.append(peak - risk.lock_trail_step)
            new_floor = max(candidates)
            floor_raised = not armed_now and lock_floor is not None and new_floor > lock_floor
            lock_floor = new_floor

    def decide(reason: BreachReason | None, detail: str) -> AggregateDecision:
        return AggregateDecision(
            total_pnl=total,
            realized_pnl=float(realized_pnl),
            unrealized_pnl=float(unrealized_pnl),
            peak_pnl=peak,
            trough_pnl=trough,
            lock_armed=lock_armed,
            lock_floor=lock_floor,
            lock_armed_now=armed_now,
            lock_floor_raised=floor_raised,
            breached=reason is not None,
            reason=reason,
            detail=detail,
        )

    # Gated on the configuration still being present: a persisted ``lock_armed``
    # left over from a configuration the user has since removed must not keep
    # closing positions.
    if (
        risk.lock_profit_at is not None
        and lock_armed
        and lock_floor is not None
        and (total <= lock_floor)
    ):
        # A floor above the arming threshold self triggers on the arming tick.
        # That is a configuration error rather than a market event, so say so
        # instead of reporting a normal lock profit exit.
        if armed_now and risk.lock_profit_at is not None and lock_floor > risk.lock_profit_at:
            return decide(
                BreachReason.LOCK_PROFIT,
                f"lock profit floor {format_price(lock_floor)} is above its arming "
                f"threshold {format_price(risk.lock_profit_at)}, so it triggered on "
                "the tick it armed; the floor must be below the threshold",
            )
        return decide(
            BreachReason.LOCK_PROFIT,
            f"lock profit triggered: mark to market {format_price(total)} fell to or "
            f"below the locked floor {format_price(lock_floor)}",
        )

    if not risk.stop_bypassed and risk.combined_stoploss is not None:
        # Read as a magnitude, so 5000 and -5000 both mean a 5000 loss.
        limit = abs(risk.combined_stoploss)
        if total <= -limit:
            return decide(
                BreachReason.COMBINED_STOP,
                f"combined stop loss hit: mark to market {format_price(total)} fell to "
                f"or below the limit {format_price(-limit)}",
            )

    if risk.combined_target is not None and total >= risk.combined_target:
        return decide(
            BreachReason.COMBINED_TARGET,
            f"combined target hit: mark to market {format_price(total)} reached the "
            f"target {format_price(risk.combined_target)}",
        )

    detail = ""
    if armed_now:
        detail = (
            f"lock profit armed at {format_price(total)}, floor set to {format_price(lock_floor)}"
        )
    elif floor_raised and lock_floor is not None:
        detail = (
            f"lock profit floor raised to {format_price(lock_floor)} on a peak of "
            f"{format_price(peak)}"
        )
    return decide(None, detail)


def evaluate_aggregate_state(
    state: Mapping[str, Any], realized_pnl: float, unrealized_pnl: float
) -> AggregateDecision:
    """Convenience wrapper for callers holding a loose dict."""
    return evaluate_aggregate(AggregateRisk.from_state(state), realized_pnl, unrealized_pnl)


def trail_stops_to_entry(
    positions: Sequence[PositionRisk | Mapping[str, Any]],
    *,
    exclude: Iterable[str] = (),
    last_prices: Mapping[str, Any] | None = None,
) -> TrailToEntryDecision:
    """Move every remaining position's stop to its own entry price.

    Fired when one position takes its target (or its stop, depending on the
    product) and the rest should be made risk free. The triggering position is
    named in ``exclude`` because it is about to be closed anyway.

    Nothing is mutated. openbull's ``apply_trail_to_entry`` writes
    ``leg["effective_sl"]`` straight into the caller's dict while its module
    docstring claims purity; returning the moves instead means a REST handler
    that owns no state can call this, and a caller can log or veto the moves
    before applying them.

    A move is skipped when it would not tighten the stop, and, when a last price
    is supplied for that position, when entry is already on the wrong side of
    the market. openbull has no such check, so its trail to entry turns a losing
    position's stop into an instant market exit at a loss, which is the opposite
    of what making the winners risk free is for.
    """
    excluded = {str(item) for item in exclude}
    prices = last_prices or {}
    moves: list[StopMove] = []
    not_improving: list[str] = []
    through_price: list[str] = []
    no_entry: list[str] = []

    for item in positions:
        risk = item if isinstance(item, PositionRisk) else PositionRisk.from_state(item)
        if risk.identifier in excluded:
            continue
        if not is_price(risk.entry_price):
            no_entry.append(risk.identifier)
            continue

        entry = float(risk.entry_price)
        current = risk.effective_stop
        long_side = risk.is_long

        if current is not None and (entry <= current if long_side else entry >= current):
            not_improving.append(risk.identifier)
            continue

        reference = as_price(prices.get(risk.identifier))
        if reference is not None and (entry >= reference if long_side else entry <= reference):
            through_price.append(risk.identifier)
            continue

        moves.append(StopMove(identifier=risk.identifier, previous_stop=current, new_stop=entry))

    detail = ""
    if moves:
        detail = f"moved {len(moves)} stop(s) to entry"
        if through_price:
            detail += (
                f"; left {len(through_price)} alone because entry is already through the market"
            )
    elif through_price or not_improving or no_entry:
        detail = "no stop moved to entry"

    return TrailToEntryDecision(
        moves=tuple(moves),
        skipped_not_improving=tuple(not_improving),
        skipped_through_price=tuple(through_price),
        skipped_no_entry=tuple(no_entry),
        detail=detail,
    )


__all__ = [
    "AggregateDecision",
    "AggregateRisk",
    "PnLSummary",
    "PositionPnL",
    "StopMove",
    "TrailToEntryDecision",
    "aggregate_pnl",
    "evaluate_aggregate",
    "evaluate_aggregate_state",
    "position_pnl",
    "trail_stops_to_entry",
]
