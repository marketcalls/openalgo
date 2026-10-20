"""Per-position risk: stop loss, target and trailing stop. Pure, no I/O.

One tick in, one decision out. Nothing here touches a database, a broker, the
feed, a clock or a logger, which is what lets the scalping monitor, Flow, a
strategy engine and a REST handler all run the identical rules.

Reconciling the two implementations this replaces
-------------------------------------------------

OpenAlgo ships ``evaluate_trail`` in services/scalping_risk_monitor_service.py
with a hand written TypeScript twin in frontend/src/hooks/useTrailingSL.ts. The
openbull fork ships ``evaluate_leg`` in backend/strategy/risk_evaluator.py. They
disagree in nine places. Each is resolved below with the reason, so nothing is
dropped silently.

1. Stop anchoring. OpenAlgo trails continuously against the running extreme
   (``highest - step``); openbull, when given both an X trigger and a Y step,
   anchors to entry (``entry + Y * (1 + floor((peak - X) / Y))``). Neither is
   wrong, they are different products, so both are kept as :class:`TrailMode`.
   CONTINUOUS is the default because it is what is live today.

2. The stepped formula itself. openbull's code and openbull's own spec
   (docs/plan/strategy-module.md section 9.1, which says the stop moves to
   ``entry + (peak - X)``) disagree: at the arming instant the code puts the
   stop a whole step above entry while the spec puts it at breakeven. Neither
   matches the trigger/step model brokers and AlgoTest actually describe, which
   is "for every X of favourable movement, move the stop by Y, starting from
   where the user put it". This module implements that third reading:
   ``initial_stop + step * floor(favourable / trigger)``. It needs the
   configured stop as a separate anchor from the live stop, which is precisely
   why OpenAlgo's schema keeps ``initial_sl`` alongside ``current_sl``.

3. Arming gate. OpenAlgo gates on the CURRENT last price being at least
   MIN_TRAIL_PROFIT in front of entry; openbull gates on the favourable PEAK.
   The peak is correct. With OpenAlgo's gate, a state restored after a restart
   with ``highest_price`` already far ahead but the price now back near entry
   refuses to re-derive the trail, so the stop silently sits at its original
   level instead of the trailed one it had earned. The peak is monotonic, so
   once armed it stays armed, which is also why openbull needs no persisted
   ``trail_active`` flag and neither do we: ``trail_armed`` is recomputed from
   the peak on every call and is one less thing for a caller to store. This
   change is behaviour preserving for every existing test in the repo, because
   a state whose peak justifies a trail also has the trailed level already in
   ``current_sl`` in the normal, non restarted case.

4. Missing stop. OpenAlgo falls back ``current_sl or initial_sl or entry``.
   The final fallback is a live bug: a position configured with a target and no
   stop gets an implicit stop at entry, and the monitor's own ``has_sl`` guard
   does not prevent it, so the first tick back through entry exits the position
   and reports it as a stop loss the user never set. Here ``None`` means no
   stop, full stop.

5. Zero as a value. Both implementations accept zero prices literally.
   ``current_sl = 0`` on a short means ``ltp >= 0``, which is true on every
   tick. Zero is not a price on any Indian exchange, so a zero stop, target,
   entry or last price is read as absent (see :func:`models.is_price`).

6. Unusable ticks. OpenAlgo guards ``ltp <= 0`` in the monitor's tick handler
   but not in the evaluator, so a direct caller gets no protection, and neither
   implementation handles NaN, where ``max(nan, x)`` is argument order
   dependent and poisons the stored extreme forever. Here a non finite or non
   positive last price returns ``evaluated=False`` with the input carried
   through unchanged.

7. Trailing off a broken entry. OpenAlgo reads ``entry_price or 0.0``, so a
   missing entry becomes zero and every tick then looks like a vast profit,
   arming the trail immediately and dragging the stop up to ``ltp - step``.
   Here a non positive entry disables trailing and P&L; the absolute stop and
   target still work, because they do not depend on entry.

8. A trail may never place the stop beyond the best price actually traded.
   openbull's stepped trail has no such guard, so any configuration with
   ``Y > X`` puts the stop above the current price on the very tick it arms and
   fires an immediate stop loss at a price better than the stop. The guard is a
   no op for CONTINUOUS (``highest - step <= highest`` always) and it is
   deliberately against the PEAK rather than the current price: a stop that is
   through the current price because the price has since fallen back is a
   correct, merely late, detection and must still fire.

9. Which fires when both hit. Both implementations give the stop priority over
   the target on the same tick, and so does this one. Within one tick the order
   of the two touches is unknowable, so assume the adverse one.

Two behaviours are kept exactly as OpenAlgo has them, against openbull:

* Only the extreme on the position's own side is updated. Tracking the adverse
  excursion too would be free information, but the scalping monitor decides
  whether to persist by diffing exactly these fields, so updating both would
  add database writes for no decision.
* The default trigger stays at 1.0, OpenAlgo's MIN_TRAIL_PROFIT, so adopting
  this core does not re-tune a live stop. openbull has no floor at all and will
  trail from the first tick.

And one openbull behaviour is deliberately dropped: its fixed distance trail
arms on the entry tick regardless of profit, which replaces a user's configured
wide stop with ``entry - X`` immediately. A trail tightens a stop after the
position has earned it, never before.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from services.risk.models import (
    BreachReason,
    PositionDecision,
    PositionRisk,
    Side,
    TrailMode,
    as_price,
    format_price,
    is_price,
)


def evaluate_position(risk: PositionRisk, last_price: Any) -> PositionDecision:
    """Judge one position against one last price.

    Order of work: update the favourable extreme, move the trailing stop, then
    test the stop, then the target. The trail runs first so a stop that has
    just ratcheted is the one tested, which is what both implementations do and
    what makes a trailed stop able to fire on the tick that set it.
    """
    if not is_price(last_price):
        # Carry everything through untouched so the caller can always write the
        # decision back over its state without a special case.
        return PositionDecision(
            identifier=risk.identifier,
            evaluated=False,
            stop_price=risk.effective_stop,
            target_price=as_price(risk.target_price),
            highest_price=risk.highest_price,
            lowest_price=risk.lowest_price,
            pnl=0.0,
            detail="tick ignored: last price is missing, zero, negative or not finite",
        )

    ltp = float(last_price)
    long_side = risk.is_long
    entry = risk.entry_price if is_price(risk.entry_price) else None

    # Seed a missing extreme from entry, or from this tick when even entry is
    # unusable, so the extreme is never seeded at zero.
    seed = entry if entry is not None else ltp
    highest = risk.highest_price
    lowest = risk.lowest_price
    if long_side:
        highest = max(highest if highest is not None else seed, ltp)
    else:
        lowest = min(lowest if lowest is not None else seed, ltp)

    # Favourable excursion: how far the best price seen has run in our favour.
    favourable = 0.0
    if entry is not None:
        best = highest if long_side else lowest
        if best is not None:
            favourable = max(0.0, (best - entry) if long_side else (entry - best))

    stop = risk.effective_stop
    original_stop = stop
    trail_armed = False

    trigger = max(0.0, risk.trail_trigger)
    can_trail = (
        risk.trailing_enabled
        and risk.trail_step > 0.0
        and math.isfinite(risk.trail_step)
        and entry is not None
    )
    # A trigger of zero means "as soon as it is in profit", not "from entry",
    # so a strictly positive excursion is always required.
    if can_trail and favourable > 0.0 and favourable >= trigger:
        trail_armed = True
        candidate = _trail_candidate(risk, favourable, highest, lowest, trigger)
        if candidate is not None:
            candidate = _clamp_to_peak(candidate, long_side, highest, lowest)
            # Ratchet: a trail may only ever tighten.
            if stop is None or (candidate > stop if long_side else candidate < stop):
                stop = candidate

    stop_moved = stop != original_stop
    target = as_price(risk.target_price)

    stop_hit = stop is not None and (ltp <= stop if long_side else ltp >= stop)
    target_hit = target is not None and (ltp >= target if long_side else ltp <= target)

    reason: BreachReason | None = None
    detail = ""
    if stop_hit:
        reason = BreachReason.STOP
        detail = (
            f"stop loss hit: last price {format_price(ltp)} is at or "
            f"{'below' if long_side else 'above'} the stop {format_price(stop)} "
            f"on a {'long' if long_side else 'short'} position"
        )
    elif target_hit:
        reason = BreachReason.TARGET
        detail = (
            f"target hit: last price {format_price(ltp)} is at or "
            f"{'above' if long_side else 'below'} the target {format_price(target)} "
            f"on a {'long' if long_side else 'short'} position"
        )
    elif stop_moved and stop is not None:
        previous = format_price(original_stop) if original_stop is not None else "none"
        detail = (
            f"trailing stop moved from {previous} to {format_price(stop)} after "
            f"{format_price(favourable)} of favourable movement"
        )

    pnl = 0.0
    if entry is not None and risk.quantity:
        pnl = (ltp - entry) * risk.quantity if long_side else (entry - ltp) * risk.quantity

    return PositionDecision(
        identifier=risk.identifier,
        evaluated=True,
        stop_price=stop,
        target_price=target,
        highest_price=highest,
        lowest_price=lowest,
        pnl=pnl,
        breached=bool(reason),
        reason=reason,
        detail=detail,
        stop_moved=stop_moved,
        trail_armed=trail_armed,
    )


def evaluate_position_state(state: Mapping[str, Any], last_price: Any) -> PositionDecision:
    """Convenience wrapper for callers holding a loose dict rather than a dataclass."""
    return evaluate_position(PositionRisk.from_state(state), last_price)


def validate_position(risk: PositionRisk, last_price: Any = None) -> tuple[str, ...]:
    """Plain text reasons a configuration is unusable, empty when it is fine.

    The same checks frontend/src/components/scalping/SetSLDialog.tsx performs
    before saving. They live here so the browser, the save endpoint and a REST
    caller cannot drift, and because a stop on the wrong side of the market is
    an instant exit rather than protection.
    """
    problems: list[str] = []
    long_side = risk.is_long
    entry = risk.entry_price if is_price(risk.entry_price) else None
    reference = float(last_price) if is_price(last_price) else entry

    if entry is None:
        problems.append("entry price is missing or not a positive number")

    stop = risk.effective_stop
    if stop is not None and reference is not None:
        if long_side and stop >= reference:
            problems.append(
                f"stop {format_price(stop)} is at or above {format_price(reference)} "
                "on a long position, which exits immediately"
            )
        if not long_side and stop <= reference:
            problems.append(
                f"stop {format_price(stop)} is at or below {format_price(reference)} "
                "on a short position, which exits immediately"
            )

    target = as_price(risk.target_price)
    if target is not None and reference is not None:
        if long_side and target <= reference:
            problems.append(
                f"target {format_price(target)} is at or below {format_price(reference)} "
                "on a long position, which exits immediately"
            )
        if not long_side and target >= reference:
            problems.append(
                f"target {format_price(target)} is at or above {format_price(reference)} "
                "on a short position, which exits immediately"
            )

    if risk.trailing_enabled and not (risk.trail_step > 0.0):
        problems.append("trailing is enabled but the trail step is not a positive number")
    if (
        risk.trailing_enabled
        and risk.trail_mode is TrailMode.STEPPED
        and not (risk.trail_trigger > 0.0)
    ):
        problems.append("a stepped trail needs a positive trail trigger")
    if (
        risk.trailing_enabled
        and risk.trail_mode is TrailMode.STEPPED
        and risk.trail_step > risk.trail_trigger > 0.0
    ):
        problems.append(
            "a stepped trail with a step larger than its trigger gives back more than "
            "it locks in; reduce the step or raise the trigger"
        )
    return tuple(problems)


def _trail_candidate(
    risk: PositionRisk,
    favourable: float,
    highest: float | None,
    lowest: float | None,
    trigger: float,
) -> float | None:
    """The level the trail wants, before the peak clamp and the ratchet."""
    if risk.trail_mode is TrailMode.STEPPED:
        if trigger <= 0.0:
            # Undefined: a stepped trail with no trigger has no step boundary.
            return None
        anchor = as_price(risk.initial_stop_price) or risk.effective_stop
        if anchor is None:
            return None
        steps = math.floor(favourable / trigger)
        if steps <= 0:
            return None
        advance = steps * risk.trail_step
        return anchor + advance if risk.is_long else anchor - advance

    if risk.is_long:
        return None if highest is None else highest - risk.trail_step
    return None if lowest is None else lowest + risk.trail_step


def _clamp_to_peak(
    candidate: float, long_side: bool, highest: float | None, lowest: float | None
) -> float:
    """Never place a stop beyond the best price the position has actually seen."""
    if long_side and highest is not None:
        return min(candidate, highest)
    if not long_side and lowest is not None:
        return max(candidate, lowest)
    return candidate


__all__ = [
    "BreachReason",
    "PositionDecision",
    "PositionRisk",
    "Side",
    "TrailMode",
    "evaluate_position",
    "evaluate_position_state",
    "validate_position",
]
