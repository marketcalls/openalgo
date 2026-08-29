"""Frozen value types for the shared risk core.

Data only. Nothing here reads a clock, a database, a broker or a feed; the only
behaviour is normalising untrusted input into typed values. Every type is
frozen so a decision can be handed to another thread, cached, put on a queue or
serialised without anyone mutating it behind the caller's back.

Naming follows what OpenAlgo already ships rather than what the openbull fork
invented:

* Sides are ``BUY`` / ``SELL`` (docs/prompt/order-constants.md), not ``B`` / ``S``.
* Stops and targets are absolute prices, because that is what
  ``database/scalping_db.py`` stores, what ``/api/v1/`` quotes speak, and what
  the browser displays. A points-configured caller converts once at the edge
  with :func:`stop_from_points` / :func:`target_from_points`.
* ``entry_price`` / ``quantity`` / ``initial_sl`` / ``current_sl`` / ``target``
  are the shipped scalping field names and are accepted as aliases by
  :meth:`PositionRisk.from_state`.
* Aggregate wording follows docs/plans/2026-02-06-strategy-risk-management-prd.md
  (``combined_*``) and services/strategy_pnl_service.py (``realized`` /
  ``unrealized`` / ``total``).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# The favourable excursion a position must show before a trail is allowed to
# move the stop. 1.0 is not arbitrary: it is the value both shipped engines use
# today (MIN_TRAIL_PROFIT in services/scalping_risk_monitor_service.py and in
# frontend/src/hooks/useTrailingSL.ts). Keeping it as the default means adopting
# this core does not silently re-tune anybody's live stops.
DEFAULT_TRAIL_TRIGGER = 1.0


class Side(StrEnum):
    """Position direction, using OpenAlgo's order constants."""

    BUY = "BUY"
    SELL = "SELL"


class TrailMode(StrEnum):
    """How a trailing stop derives its new level.

    ``CONTINUOUS`` anchors to the best price the position has actually seen and
    keeps a fixed gap behind it. ``STEPPED`` anchors to the configured initial
    stop and advances it one step per completed trigger of favourable movement.
    See the reconciliation notes in ``services/risk/position.py``.
    """

    CONTINUOUS = "continuous"
    STEPPED = "stepped"


class BreachReason(StrEnum):
    """Why a rule fired.

    The per-position values are ``sl`` and ``target`` because those are already
    the wire contract between the scalping service, its SocketIO push and the
    browser. The aggregate values follow the PRD's ``exit_detail`` vocabulary.
    """

    STOP = "sl"
    TARGET = "target"
    COMBINED_STOP = "combined_sl"
    COMBINED_TARGET = "combined_target"
    LOCK_PROFIT = "lock_profit"


def is_price(value: Any) -> bool:
    """True when ``value`` is a usable, strictly positive, finite price.

    Zero is deliberately not a price. Nothing on an Indian exchange trades at
    or below zero, so a zero stop, target or last price is a missing value that
    reached us as a numeric default, and treating it literally is how a short
    leg with ``current_sl = 0`` would breach on every single tick.
    """
    if value is None or isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0.0


def as_float(value: Any, default: float = 0.0) -> float:
    """Coerce to float, falling back to ``default`` for anything unusable."""
    if value is None or isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def as_price(value: Any) -> float | None:
    """Coerce to a price, or ``None`` when the value is not a usable price."""
    return float(value) if is_price(value) else None


def normalise_side(value: Any) -> Side:
    """Map anything a caller might send to a :class:`Side`.

    Unknown values fall back to BUY, matching the shipped scalping engine's
    ``(state.get("side") or "BUY").upper()``. The fallback is safe because the
    side only chooses which comparison to run; a caller that has genuinely lost
    the side should be caught by :func:`services.risk.validate_position` rather
    than by an exception on the tick path.
    """
    if isinstance(value, Side):
        return value
    text = str(value or "").strip().upper()
    if text in ("SELL", "S", "SHORT", "-1"):
        return Side.SELL
    return Side.BUY


def normalise_trail_mode(value: Any) -> TrailMode:
    if isinstance(value, TrailMode):
        return value
    text = str(value or "").strip().lower()
    return TrailMode.STEPPED if text in ("stepped", "step", "staircase") else TrailMode.CONTINUOUS


def stop_from_points(side: Any, entry_price: float, points: float) -> float | None:
    """Convert a points-based stop distance into the absolute stop price."""
    if not is_price(entry_price) or not is_price(points):
        return None
    entry = float(entry_price)
    distance = float(points)
    price = entry - distance if normalise_side(side) is Side.BUY else entry + distance
    return price if price > 0.0 else None


def target_from_points(side: Any, entry_price: float, points: float) -> float | None:
    """Convert a points-based target distance into the absolute target price."""
    if not is_price(entry_price) or not is_price(points):
        return None
    entry = float(entry_price)
    distance = float(points)
    price = entry + distance if normalise_side(side) is Side.BUY else entry - distance
    return price if price > 0.0 else None


def side_from_quantity(net_quantity: Any) -> Side:
    """Derive the side from a signed net quantity, as the position book reports it."""
    return Side.SELL if as_float(net_quantity) < 0.0 else Side.BUY


@dataclass(frozen=True, slots=True)
class PositionRisk:
    """Everything the core needs to judge one position against one tick.

    ``stop_price`` is the live stop, which a trail may already have moved.
    ``initial_stop_price`` is the level the user configured and is the anchor a
    stepped trail advances from; the shipped scalping schema already carries
    both as ``current_sl`` and ``initial_sl``, which is exactly why the stepped
    mode is expressible here at all.

    ``quantity`` is a magnitude. ``side`` is the single source of direction, so
    a caller holding a signed net quantity passes ``abs()`` here and derives the
    side with :func:`side_from_quantity`.
    """

    identifier: str = ""
    side: Side = Side.BUY
    entry_price: float = 0.0
    quantity: float = 0.0
    stop_price: float | None = None
    initial_stop_price: float | None = None
    target_price: float | None = None
    trailing_enabled: bool = False
    trail_step: float = 0.0
    trail_trigger: float = DEFAULT_TRAIL_TRIGGER
    trail_mode: TrailMode = TrailMode.CONTINUOUS
    highest_price: float | None = None
    lowest_price: float | None = None

    def __post_init__(self) -> None:
        # Frozen dataclasses still allow normalisation here, and doing it once
        # at construction means every downstream comparison can trust the types.
        object.__setattr__(self, "side", normalise_side(self.side))
        object.__setattr__(self, "trail_mode", normalise_trail_mode(self.trail_mode))

    @property
    def is_long(self) -> bool:
        return self.side is Side.BUY

    @property
    def effective_stop(self) -> float | None:
        """The stop actually in force: the live one, else the configured one.

        Note what is absent: there is no fall back to ``entry_price``. See the
        reconciliation notes in ``position.py`` for why that fallback is a bug.
        """
        return as_price(self.stop_price) or as_price(self.initial_stop_price)

    @classmethod
    def from_state(cls, state: Mapping[str, Any]) -> PositionRisk:
        """Build from a loose dict: the scalping state shape or the canonical one.

        Accepts both alias sets so the scalping monitor's DB rows, the browser's
        wire payload and a REST body all load without a translation layer at
        each call site.
        """
        get = state.get

        def first(*names: str) -> Any:
            for name in names:
                value = get(name)
                if value is not None:
                    return value
            return None

        entry = as_float(first("entry_price", "entry", "entry_avg", "average_price"))
        side = normalise_side(first("side", "action", "position"))
        stop = as_price(first("stop_price", "current_sl", "currentSl"))
        initial_stop = as_price(first("initial_stop_price", "initial_sl", "initialSl"))
        target = as_price(first("target_price", "target", "targetPrice"))

        # Points-configured callers (the strategy PRD, Flow) convert once, here.
        if stop is None and initial_stop is None:
            initial_stop = stop_from_points(side, entry, as_float(first("sl_points", "sl_pts")))
        if target is None:
            target = target_from_points(side, entry, as_float(first("target_points", "target_pts")))

        trigger = first("trail_trigger", "trailing_trigger", "trail_x")
        return cls(
            identifier=str(first("identifier", "id", "symbol") or ""),
            side=side,
            entry_price=entry,
            quantity=abs(as_float(first("quantity", "qty"))),
            stop_price=stop,
            initial_stop_price=initial_stop,
            target_price=target,
            trailing_enabled=bool(first("trailing_enabled", "trailingEnabled")),
            trail_step=as_float(first("trail_step", "trailing_step", "trailingStep", "trail_y")),
            trail_trigger=(
                as_float(trigger, DEFAULT_TRAIL_TRIGGER)
                if trigger is not None
                else DEFAULT_TRAIL_TRIGGER
            ),
            trail_mode=normalise_trail_mode(first("trail_mode", "trailMode")),
            highest_price=as_price(first("highest_price", "highestPrice")),
            lowest_price=as_price(first("lowest_price", "lowestPrice")),
        )


@dataclass(frozen=True, slots=True)
class PositionDecision:
    """What one tick did to one position.

    ``evaluated`` is False when the tick itself was unusable (missing, zero,
    negative or non finite last price). In that case every other field is the
    input carried through unchanged, so a caller can always write the decision
    back over its state without checking.
    """

    identifier: str = ""
    evaluated: bool = True
    stop_price: float | None = None
    target_price: float | None = None
    highest_price: float | None = None
    lowest_price: float | None = None
    pnl: float = 0.0
    breached: bool = False
    reason: BreachReason | None = None
    detail: str = ""
    stop_moved: bool = False
    trail_armed: bool = False

    def to_trail_state(self) -> dict[str, Any]:
        """The legacy ``evaluate_trail`` return shape, field for field.

        Kept so services/scalping_risk_monitor_service.py and the browser can
        adopt the core without touching their persistence or SocketIO payloads.
        """
        return {
            "highest_price": self.highest_price,
            "lowest_price": self.lowest_price,
            "current_sl": self.stop_price,
            "breached": self.breached,
            "reason": self.reason.value if self.reason is not None else None,
        }

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form for a REST response or a log line."""
        return {
            "identifier": self.identifier,
            "evaluated": self.evaluated,
            "stop_price": self.stop_price,
            "target_price": self.target_price,
            "highest_price": self.highest_price,
            "lowest_price": self.lowest_price,
            "pnl": self.pnl,
            "breached": self.breached,
            "reason": self.reason.value if self.reason is not None else None,
            "detail": self.detail,
            "stop_moved": self.stop_moved,
            "trail_armed": self.trail_armed,
        }


@dataclass(frozen=True, slots=True)
class PositionPnL:
    """One position's contribution to the aggregate mark to market.

    Closed positions contribute ``realized_pnl``; open ones are marked from
    ``last_price``. An open position with no usable last price contributes
    nothing and is counted in ``unpriced``, mirroring the ``unpriced_legs``
    field services/strategy_pnl_service.py already reports.
    """

    identifier: str = ""
    side: Side = Side.BUY
    entry_price: float = 0.0
    quantity: float = 0.0
    last_price: float | None = None
    closed: bool = False
    realized_pnl: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "side", normalise_side(self.side))

    @classmethod
    def from_state(cls, state: Mapping[str, Any]) -> PositionPnL:
        get = state.get
        quantity = as_float(get("quantity") if get("quantity") is not None else get("qty"))
        side_value = get("side") if get("side") is not None else get("action")
        return cls(
            identifier=str(get("identifier") or get("symbol") or ""),
            # A position book row carries the direction in the sign of the
            # quantity rather than in a side field, so fall back to that.
            side=normalise_side(side_value) if side_value else side_from_quantity(quantity),
            entry_price=as_float(
                get("entry_price") if get("entry_price") is not None else get("average_price")
            ),
            quantity=abs(quantity),
            last_price=as_price(get("last_price") if get("last_price") is not None else get("ltp")),
            closed=bool(get("closed")) or str(get("status") or "").lower() == "closed",
            realized_pnl=as_float(
                get("realized_pnl") if get("realized_pnl") is not None else get("realized")
            ),
        )


@dataclass(frozen=True, slots=True)
class PnLSummary:
    """Aggregate mark to market, named as services/strategy_pnl_service.py names it."""

    realized: float = 0.0
    unrealized: float = 0.0
    total: float = 0.0
    priced: int = 0
    unpriced: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "realized": self.realized,
            "unrealized": self.unrealized,
            "total": self.total,
            "priced": self.priced,
            "unpriced": self.unpriced,
        }


@dataclass(frozen=True, slots=True)
class AggregateRisk:
    """Portfolio level limits and the ratchet state they need carried between ticks.

    All amounts are mark to market currency, not prices. ``combined_stoploss``
    is read as a magnitude, so a caller may send 5000 or -5000 and mean the
    same loss.

    Lock profit arms once ``total >= lock_profit_at`` and then holds a floor at
    ``lock_profit_floor``; with ``lock_trail_step`` set the floor additionally
    ratchets up to ``peak_pnl - lock_trail_step`` and never falls back.
    """

    combined_stoploss: float | None = None
    combined_target: float | None = None
    lock_profit_at: float | None = None
    lock_profit_floor: float | None = None
    lock_trail_step: float | None = None
    lock_armed: bool = False
    lock_floor: float | None = None
    peak_pnl: float = 0.0
    trough_pnl: float = 0.0
    stop_bypassed: bool = False

    @classmethod
    def from_state(cls, state: Mapping[str, Any]) -> AggregateRisk:
        get = state.get

        def first(*names: str) -> Any:
            for name in names:
                value = get(name)
                if value is not None:
                    return value
            return None

        step = first("lock_trail_step", "trail_step")
        return cls(
            combined_stoploss=_optional_float(
                first("combined_stoploss", "overall_sl_mtm", "max_loss")
            ),
            combined_target=_optional_float(
                first("combined_target", "overall_target_mtm", "max_profit")
            ),
            lock_profit_at=_optional_float(first("lock_profit_at", "if_profit_reaches")),
            lock_profit_floor=_optional_float(first("lock_profit_floor", "lock_profit")),
            lock_trail_step=_optional_float(step),
            lock_armed=bool(first("lock_armed")),
            lock_floor=_optional_float(first("lock_floor")),
            peak_pnl=as_float(first("peak_pnl", "pnl_peak")),
            trough_pnl=as_float(first("trough_pnl", "pnl_trough")),
            stop_bypassed=bool(first("stop_bypassed", "trail_to_entry_active")),
        )


@dataclass(frozen=True, slots=True)
class AggregateDecision:
    """What one aggregate evaluation decided.

    ``peak_pnl`` / ``trough_pnl`` / ``lock_armed`` / ``lock_floor`` are always
    returned, breach or not, because they are ratchets the caller must persist.
    """

    total_pnl: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    peak_pnl: float = 0.0
    trough_pnl: float = 0.0
    lock_armed: bool = False
    lock_floor: float | None = None
    lock_armed_now: bool = False
    lock_floor_raised: bool = False
    breached: bool = False
    reason: BreachReason | None = None
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_pnl": self.total_pnl,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "peak_pnl": self.peak_pnl,
            "trough_pnl": self.trough_pnl,
            "lock_armed": self.lock_armed,
            "lock_floor": self.lock_floor,
            "lock_armed_now": self.lock_armed_now,
            "lock_floor_raised": self.lock_floor_raised,
            "breached": self.breached,
            "reason": self.reason.value if self.reason is not None else None,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class StopMove:
    """One stop relocation the caller should apply."""

    identifier: str
    previous_stop: float | None
    new_stop: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "previous_stop": self.previous_stop,
            "new_stop": self.new_stop,
        }


@dataclass(frozen=True, slots=True)
class TrailToEntryDecision:
    """Which stops trail to entry, and which were deliberately left alone.

    Nothing is mutated. The caller applies ``moves``, which is what makes this
    usable from a REST handler that owns no state at all.
    """

    moves: tuple[StopMove, ...] = ()
    skipped_not_improving: tuple[str, ...] = ()
    skipped_through_price: tuple[str, ...] = ()
    skipped_no_entry: tuple[str, ...] = ()
    detail: str = ""

    @property
    def moved(self) -> int:
        return len(self.moves)

    def as_dict(self) -> dict[str, Any]:
        return {
            "moved": self.moved,
            "moves": [move.as_dict() for move in self.moves],
            "skipped_not_improving": list(self.skipped_not_improving),
            "skipped_through_price": list(self.skipped_through_price),
            "skipped_no_entry": list(self.skipped_no_entry),
            "detail": self.detail,
        }


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def format_price(value: float) -> str:
    """Compact plain text price for a detail message. No currency symbol."""
    text = f"{float(value):.4f}".rstrip("0").rstrip(".")
    return text or "0"
