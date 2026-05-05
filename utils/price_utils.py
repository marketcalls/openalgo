"""Price snapping helpers for the Strategy v2 engine.

Brokers reject limit / SL / SL-M orders whose price is not aligned to the
instrument's tick size. Every price the engine writes to a broker order must
go through round_to_tick().

Decimal arithmetic is used internally so a 0.05 tick never drifts due to
binary floating-point error (which would otherwise turn 100.05 into
100.04999999999998 → broker rejection).

This module deliberately lives in utils/ (not services/) so it can be used
by services, blueprints, and event handlers without circular imports.
"""

from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING, ROUND_HALF_UP
from typing import Literal, Union

Number = Union[int, float, Decimal]
RoundMode = Literal["nearest", "favorable", "down", "up"]
Side = Literal["BUY", "SELL"]


def _to_decimal(x: Number) -> Decimal:
    if isinstance(x, Decimal):
        return x
    # Going through str avoids 0.1 != Decimal(0.1) precision issues.
    return Decimal(str(x))


def round_to_tick(
    price: Number,
    tick_size: Number,
    mode: RoundMode = "nearest",
    side: Side = "BUY",
) -> float:
    """Snap `price` to the nearest multiple of `tick_size`.

    Args:
        price:      Raw price from a calculation (e.g. trail SL recomputation).
        tick_size:  Instrument tick size (cached on the leg row at arm-time).
        mode:
            - 'nearest':   standard half-up rounding to nearest tick.
            - 'down':      always round down (floor).
            - 'up':        always round up (ceiling).
            - 'favorable': trader-favorable direction, requires `side`:
                  BUY  side  → round DOWN  (looser SL on a long, easier target)
                  SELL side  → round UP    (looser SL on a short, easier target)
              The intent: never make a stop tighter or a target harder due to
              tick-size snapping. Costs a fraction of a tick at most.
        side:       Required for mode='favorable'. Ignored otherwise.

    Returns:
        Snapped price as a float (broker payloads use float / numeric strings).

    Raises:
        ValueError if tick_size <= 0 or mode is not recognised.
    """
    p = _to_decimal(price)
    t = _to_decimal(tick_size)

    if t <= 0:
        raise ValueError(f"tick_size must be > 0, got {tick_size}")

    if mode == "nearest":
        rounding = ROUND_HALF_UP
    elif mode == "down":
        rounding = ROUND_FLOOR
    elif mode == "up":
        rounding = ROUND_CEILING
    elif mode == "favorable":
        if side not in ("BUY", "SELL"):
            raise ValueError(f"side must be 'BUY' or 'SELL' when mode='favorable', got {side!r}")
        rounding = ROUND_FLOOR if side == "BUY" else ROUND_CEILING
    else:
        raise ValueError(f"Unknown round mode: {mode!r}")

    # Quantise (p / t) to an integer number of ticks, then multiply back.
    quantised_ticks = (p / t).quantize(Decimal("1"), rounding=rounding)
    snapped = quantised_ticks * t
    # Render with at most as many decimals as the tick size carries.
    # E.g. tick=0.05 → 2 decimals; tick=0.5 → 1 decimal; tick=1 → 0 decimals.
    decimals = max(0, -t.as_tuple().exponent)
    return float(snapped.quantize(Decimal(10) ** -decimals))


def is_aligned_to_tick(price: Number, tick_size: Number) -> bool:
    """True if `price` is exactly a multiple of `tick_size` (decimal-correct)."""
    p = _to_decimal(price)
    t = _to_decimal(tick_size)
    if t <= 0:
        return False
    return (p % t) == Decimal(0)


def ticks_between(low: Number, high: Number, tick_size: Number) -> int:
    """Count how many full ticks separate two prices (low < high). Useful for
    validating user-entered SL/target distances against the instrument's
    minimum movement, e.g. trail X must be >= 1 tick.
    """
    if tick_size is None:
        return 0
    lo = _to_decimal(low)
    hi = _to_decimal(high)
    t = _to_decimal(tick_size)
    if t <= 0:
        return 0
    return int(((hi - lo) / t).quantize(Decimal("1"), rounding=ROUND_FLOOR))
