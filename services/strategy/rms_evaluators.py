"""Pure-function RMS rule evaluators.

These functions take a leg's current state + ltp and return a decision —
no DB writes, no event publishing, no broker calls. The engine wires the
decisions into actions (close_leg, persist new SL).

Splitting the logic out from rms_engine.py keeps the engine's tick callback
short and the rules unit-testable in isolation.

All evaluators are direction-aware: long legs (net_qty > 0) trigger SL
when ltp falls below; short legs (net_qty < 0) trigger SL when ltp rises
above. Pts and pct units interchangeable per parameter — pct is relative
to the leg's avg_entry, so it works at strategy level without a capital
reference.

Trail SL is the X/Y ratchet from plan §6 (image 5):
    "Every time the instrument moves in your favor by Xpts, advance the
     SL by Ypts in the same direction."
Floor-division: a 5-pt favorable move with X=1, Y=2 advances SL by 10pts
(5 advances × 2), not just 2. One-way ratchet: SL only ever moves in the
trader's favor — retracement does not relax it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Optional

from utils.price_utils import round_to_tick


Unit = Literal["pts", "pct"]
Direction = Literal["long", "short"]


# ---------------------------------------------------------------------------
# Unit conversion
# ---------------------------------------------------------------------------


def to_price_delta(value: float, unit: Unit, reference_price: float) -> float:
    """Convert a (value, unit) pair to an absolute price delta.

    For pct, the reference is the leg's avg_entry — `%` is relative to where
    the position opened, never to capital (plan §1.1 #4).
    """
    if unit == "pts":
        return float(value)
    if unit == "pct":
        return float(reference_price) * float(value) / 100.0
    raise ValueError(f"Unknown unit: {unit!r}")


def direction_of(net_qty: int) -> Direction:
    return "long" if net_qty > 0 else "short"


def dir_sign(direction: Direction) -> int:
    """+1 for long, -1 for short — used to compute favorable-move direction."""
    return 1 if direction == "long" else -1


# ---------------------------------------------------------------------------
# Decision dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TargetDecision:
    triggered: bool
    target_price: Optional[float] = None
    threshold: Optional[float] = None  # which side of LTP triggers (for audit)


@dataclass(frozen=True)
class SLDecision:
    triggered: bool
    sl_price: Optional[float] = None
    threshold: Optional[float] = None


@dataclass(frozen=True)
class TrailDecision:
    advanced: bool
    advances: int = 0
    new_sl_price: Optional[float] = None
    new_anchor: Optional[float] = None


# ---------------------------------------------------------------------------
# Target evaluator — fires when LTP crosses target in the favorable direction.
# ---------------------------------------------------------------------------


def evaluate_target(
    *,
    enabled: bool,
    target_value: Optional[float],
    target_unit: Optional[Unit],
    avg_entry: float,
    ltp: float,
    direction: Direction,
    tick_size: float,
) -> TargetDecision:
    """Compute the target price and decide if LTP has crossed it.

    Long target: avg_entry + delta — fires when ltp >= target_price.
    Short target: avg_entry - delta — fires when ltp <= target_price.
    """
    if not enabled or target_value is None or target_unit is None:
        return TargetDecision(triggered=False)

    delta = to_price_delta(target_value, target_unit, avg_entry)
    if delta <= 0:
        return TargetDecision(triggered=False)

    sign = dir_sign(direction)
    raw_target = avg_entry + (delta * sign)

    # Snap to tick — for a target, favorable rounding makes the target EASIER
    # to hit. Per utils/price_utils.round_to_tick:
    #   side='BUY'  → ROUND_FLOOR (down)  — used for long target (lower price)
    #   side='SELL' → ROUND_CEILING (up)  — used for short target (higher price,
    #                                       i.e. closer to entry above for short)
    # The 'side' here aligns with the leg DIRECTION (long=BUY, short=SELL),
    # NOT with the closing-trade action — same convention as the SL evaluator
    # below.
    target_price = round_to_tick(
        raw_target,
        tick_size,
        mode="favorable",
        side="BUY" if direction == "long" else "SELL",
    )

    # Trigger when ltp has crossed the target in the favorable direction.
    if direction == "long":
        triggered = ltp >= target_price
    else:
        triggered = ltp <= target_price

    return TargetDecision(triggered=triggered, target_price=target_price, threshold=ltp)


# ---------------------------------------------------------------------------
# Stop-loss evaluator — fires when LTP crosses SL in the adverse direction.
# ---------------------------------------------------------------------------


def evaluate_sl(
    *,
    enabled: bool,
    sl_value: Optional[float],
    sl_unit: Optional[Unit],
    avg_entry: float,
    ltp: float,
    direction: Direction,
    tick_size: float,
    current_sl_price: Optional[float] = None,
) -> SLDecision:
    """Compute the effective SL price and decide if LTP has crossed it.

    `current_sl_price` overrides the value-derived SL when present (this is
    how trail advances + trail-to-entry get respected — they write to
    current_sl_price and the SL evaluator just reads it). On the first call
    (current_sl_price is None) we compute the initial SL from sl_value.

    Long SL: avg_entry - delta — fires when ltp <= sl_price.
    Short SL: avg_entry + delta — fires when ltp >= sl_price.
    """
    if not enabled:
        return SLDecision(triggered=False)

    if current_sl_price is not None:
        sl_price = current_sl_price
    else:
        if sl_value is None or sl_unit is None:
            return SLDecision(triggered=False)
        delta = to_price_delta(sl_value, sl_unit, avg_entry)
        if delta <= 0:
            return SLDecision(triggered=False)
        sign = dir_sign(direction)
        raw_sl = avg_entry - (delta * sign)
        # Favorable rounding for SL = LOOSER stop:
        #   long SL  (sell trigger below entry):  round DOWN  (further from entry)
        #   short SL (buy trigger above entry):   round UP    (further from entry)
        sl_price = round_to_tick(
            raw_sl,
            tick_size,
            mode="favorable",
            side="BUY" if direction == "long" else "SELL",
        )

    if direction == "long":
        triggered = ltp <= sl_price
    else:
        triggered = ltp >= sl_price

    return SLDecision(triggered=triggered, sl_price=sl_price, threshold=ltp)


# ---------------------------------------------------------------------------
# Trail SL — X/Y ratchet (image 5)
# ---------------------------------------------------------------------------


def evaluate_trail(
    *,
    enabled: bool,
    trail_x: Optional[float],
    trail_y: Optional[float],
    trail_unit: Optional[Unit],
    avg_entry: float,
    ltp: float,
    direction: Direction,
    tick_size: float,
    last_anchor: float,
    current_sl_price: float,
) -> TrailDecision:
    """X/Y ratchet — for every X favorable points moved since the last
    anchor, advance the SL by Y points and bump the anchor.

    The `last_anchor` starts at avg_entry on the first fill. After each
    advance, the anchor moves by exactly n_advances × x_delta (NOT to ltp
    — see plan §6 'X-Y ratchet' for why that matters).

    One-way ratchet: the new SL must be in-favor of the current SL after
    tick-snap, otherwise no advance is recorded.
    """
    if not enabled or trail_x is None or trail_y is None or trail_unit is None:
        return TrailDecision(advanced=False)
    if trail_x <= 0 or trail_y <= 0:
        return TrailDecision(advanced=False)

    sign = dir_sign(direction)
    x_delta = to_price_delta(trail_x, trail_unit, avg_entry)
    y_delta = to_price_delta(trail_y, trail_unit, avg_entry)

    favorable = (ltp - last_anchor) * sign
    if favorable < x_delta:
        return TrailDecision(advanced=False)

    n_advances = int(favorable // x_delta)
    if n_advances <= 0:
        return TrailDecision(advanced=False)

    raw_new_sl = current_sl_price + (n_advances * y_delta * sign)
    new_sl = round_to_tick(
        raw_new_sl,
        tick_size,
        mode="favorable",
        side="BUY" if direction == "long" else "SELL",
    )

    # One-way ratchet — must improve (in trader-favorable direction).
    improved = (new_sl - current_sl_price) * sign > 0
    if not improved:
        return TrailDecision(advanced=False)

    new_anchor = last_anchor + (n_advances * x_delta * sign)

    return TrailDecision(
        advanced=True,
        advances=n_advances,
        new_sl_price=new_sl,
        new_anchor=new_anchor,
    )
