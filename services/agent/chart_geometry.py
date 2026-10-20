"""Chart geometry: pivots, levels, lines, zones and patterns, from real bars.

Why this module exists
----------------------

A level drawn on a chart is read as a fact about the market. So every price the
agent draws has to come from a candle the platform returned, and the model's job
is to choose **which** structure is interesting, never to choose what the numbers
are. That separation only holds if the arithmetic lives somewhere the model
cannot reach, which is here.

Like ``services/risk/``, this module **performs no I/O of any kind**: no
database, no broker, no market data, no clock, no agno. Every input arrives as an
argument and every answer leaves as a return value. That is what makes it
testable without a running platform, safe to call from the agent's real OS
thread, and impossible to talk past with a prompt.

The one input is :class:`Bars`, a cleaned candle window read once out of the
DataFrame ``services.agent.tools.market.candle_frame`` builds. After that
conversion nothing here touches pandas, so a test can build a window from six
tuples and assert on a pivot.

What the numbers mean
---------------------

* **Times are UTC epoch seconds**, the single time model the chart engine uses.
  ``candle_frame`` indexes in Asia/Kolkata, so the conversion happens once, in
  :meth:`Bars.from_frame`, and everything downstream is seconds.
* **A pivot is anchored to the bar where the extreme printed**, not to the bar
  that confirmed it ``right`` steps later. Returning the confirming bar is the
  off-by-right error this module is written to avoid.
* **Significance is measured against the window the operator can see**, because
  what counts as a meaningful retracement depends on how far they are zoomed in.
  Fractals themselves are detected over the whole fetched frame and only then
  clipped, so a pivot two bars inside the right edge is still confirmed by bars
  off screen.

Typical use
-----------

    from services.agent import chart_geometry as geom

    bars = geom.Bars.from_frame(frame)
    lo, hi = bars.window(visible_from, visible_to)
    highs, lows = geom.significant_pivots(bars, lo, hi)
    levels = geom.support_resistance(bars, lo, hi, reference=last_price)
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "DEFAULT_LEFT",
    "DEFAULT_RIGHT",
    "MAX_TRENDLINE_PIVOTS",
    "MIN_VERTICES",
    "SIGNIFICANCE_LADDER",
    "TOUCH_TOLERANCE_PCT",
    "Bars",
    "Pivot",
    "bar_seconds",
    "candlestick_patterns",
    "chart_patterns",
    "fit_line",
    "significant_pivots",
    "structure",
    "support_resistance",
    "swing_pivots",
    "zone",
]

#: Fractal half-widths. Three bars either side is the smallest window that
#: ignores a single outlier bar while still catching a two day reversal on a
#: daily frame.
DEFAULT_LEFT = 3
DEFAULT_RIGHT = 3

#: Retracement thresholds tried in turn, as a fraction of the visible range.
#: A fixed threshold is the wrong yardstick on a clean trend: when a stock runs
#: 100 points with 6 point pullbacks the range is dominated by the trend, the
#: threshold lands above every retracement, and the pivot list collapses to one
#: point. So the strictest rung is tried first and relaxed until both sides
#: carry :data:`MIN_VERTICES`. The last rung is 0, which prunes nothing.
SIGNIFICANCE_LADDER: tuple[float, ...] = (0.12, 0.09, 0.06, 0.03, 0.0)

#: Pivots per side :func:`significant_pivots` tries to reach before it stops
#: relaxing the threshold.
MIN_VERTICES = 4

#: How close a pivot has to sit to a candidate line before it counts as a touch,
#: as a percentage of the line's price at that bar. A swing sits a few ticks off.
TOUCH_TOLERANCE_PCT = 0.5

#: Pair search in :func:`fit_line` is quadratic. Beyond this many pivots the most
#: recent ones are used, because an old pivot rarely defines a live line.
MAX_TRENDLINE_PIVOTS = 40

#: How close two prices have to be, as a fraction of the window range, before a
#: pattern detector calls them equal. A double top is never two identical prints.
_EQUAL_FRACTION = 0.03

#: Bars scanned for candlestick patterns when the caller names no count. Twenty
#: bars is what a trader can see at the right edge without scrolling.
_DEFAULT_CANDLE_SCAN = 20

#: Trend context for a single-bar reversal pattern: a hammer only means anything
#: after a fall, and a hanging man only after a rise. Measured over this many
#: bars before the pattern bar.
_TREND_CONTEXT_BARS = 5

#: How tall a band may be and still be called a range, as a share of the whole
#: visible move. A consolidation is bounded by its own extremes, so this has to
#: leave room for the wick that printed inside it: measured on RELIANCE NSE daily
#: over 2026-04-01 to 2026-09-04, the stretch a trader boxes is 96.10 points of a
#: 223.60 point window, and the previous third of the range rejected it and
#: settled for a 29 bar sub-window inside it instead.
_RANGE_BAND_FRACTION = 0.45

#: How far price may actually get between the two ends of a candidate range, as a
#: share of that band's own height. This is the half that stops a wider band
#: turning every trend into a range: a trending leg fits inside a tall box too,
#: and the difference is that it came out the other side. Measured on TITAN NSE
#: daily over 2026-06-01 to 2026-09-04, widening alone boxed a 30 bar leg price
#: crossed 0.86 of top to bottom; with this rule the answer is the genuinely flat
#: 28 bars beside it, at 0.37.
_RANGE_DRIFT_FRACTION = 0.5


@dataclass(frozen=True, slots=True)
class Pivot:
    """One confirmed swing point.

    Attributes:
        index: Bar index inside the :class:`Bars` window it came from.
        time: UTC epoch seconds of that bar.
        price: The high for a swing high, the low for a swing low.
        kind: ``high`` or ``low``.
    """

    index: int
    time: float
    price: float
    kind: str

    def as_anchor(self) -> dict[str, float]:
        """Render this pivot as a chart anchor.

        Returns:
            ``{"time": ..., "price": ...}`` in the shape a draw command carries.
        """
        return {"time": float(self.time), "price": round(float(self.price), 4)}


@dataclass(frozen=True, slots=True)
class Bars:
    """A cleaned candle window, read once out of a DataFrame.

    Everything below this class works on plain tuples, so geometry can be
    exercised without pandas and a test can build a window by hand.

    Attributes:
        times: UTC epoch seconds, ascending, one per bar.
        opens: Open prices.
        highs: High prices.
        lows: Low prices.
        closes: Close prices.
        volumes: Volumes, or an empty tuple when the broker served none.
    """

    times: tuple[float, ...]
    opens: tuple[float, ...]
    highs: tuple[float, ...]
    lows: tuple[float, ...]
    closes: tuple[float, ...]
    volumes: tuple[float, ...] = ()

    def __len__(self) -> int:
        """Return how many bars the window holds."""
        return len(self.times)

    @classmethod
    def from_frame(cls, frame: Any) -> Bars:
        """Read a cleaned candle frame into a geometry window.

        Args:
            frame: The DataFrame ``services.agent.tools.market.candle_frame``
                builds: indexed by an Asia/Kolkata timestamp, oldest first, with
                float ``open``, ``high``, ``low``, ``close`` and optionally
                ``volume`` columns and no NaN left anywhere.

        Returns:
            The window. Empty when the frame carries no rows or no close, which
            every caller checks rather than assuming a bar exists.
        """
        if frame is None or len(frame) == 0 or "close" not in getattr(frame, "columns", ()):
            return cls((), (), (), (), ())

        try:
            times = tuple(float(moment.timestamp()) for moment in frame.index)
        except (AttributeError, TypeError, ValueError):
            logger.exception("A candle frame index could not be read as timestamps")
            return cls((), (), (), (), ())

        def column(name: str, fallback: Sequence[float]) -> tuple[float, ...]:
            if name not in frame.columns:
                return tuple(fallback)
            return tuple(float(value) for value in frame[name].tolist())

        closes = column("close", ())
        return cls(
            times=times,
            opens=column("open", closes),
            highs=column("high", closes),
            lows=column("low", closes),
            closes=closes,
            volumes=column("volume", ()) if "volume" in frame.columns else (),
        )

    def window(self, start: float | None = None, end: float | None = None) -> tuple[int, int]:
        """Clip the window to a visible time range.

        Args:
            start: Lower bound in UTC epoch seconds, or None for the first bar.
            end: Upper bound in UTC epoch seconds, or None for the last bar.

        Returns:
            Inclusive ``(lo, hi)`` bar indices. A range that selects fewer than
            two bars falls back to the whole window, because a viewport the
            operator has scrolled off the loaded data is not a reason to refuse
            to answer.
        """
        total = len(self.times)
        if total == 0:
            return 0, -1

        lo, hi = 0, total - 1
        if start is not None and math.isfinite(start):
            lo = next((i for i, t in enumerate(self.times) if t >= start), total - 1)
        if end is not None and math.isfinite(end):
            hi = next((i for i in range(total - 1, -1, -1) if self.times[i] <= end), 0)
        if hi - lo < 1:
            return 0, total - 1
        return lo, hi

    def span(self, lo: int, hi: int) -> float:
        """Return the high to low range across a bar span.

        Args:
            lo: First bar index, inclusive.
            hi: Last bar index, inclusive.

        Returns:
            The range in price units, or 0.0 when the span is empty.
        """
        if hi < lo or not self.highs:
            return 0.0
        return float(max(self.highs[lo : hi + 1]) - min(self.lows[lo : hi + 1]))


def bar_seconds(bars: Bars) -> float:
    """Estimate the seconds between adjacent bars.

    The median gap rather than the mean, so a weekend or a holiday does not
    stretch the answer. Used to turn a slope in price per second into the price
    per bar a trader reads.

    Args:
        bars: The candle window.

    Returns:
        Seconds per bar, or 0.0 when the window holds fewer than two bars.
    """
    if len(bars) < 2:
        return 0.0
    gaps = sorted(
        bars.times[i + 1] - bars.times[i]
        for i in range(len(bars) - 1)
        if bars.times[i + 1] > bars.times[i]
    )
    if not gaps:
        return 0.0
    return float(gaps[len(gaps) // 2])


# ---------------------------------------------------------------------------
# Pivots
# ---------------------------------------------------------------------------


def _fractals(values: Sequence[float], left: int, right: int, kind: str) -> list[int]:
    """Bar indices whose value is the extreme of their own neighbourhood.

    Equal extremes count on both sides, because a double top with two prints at
    the same price is two pivots and a strict test drops the earlier of them. A
    run of consecutive equal bars collapses to its first bar, and a bar whose
    whole neighbourhood equals it is flat rather than a swing, so a constant
    series yields nothing.

    Args:
        values: Highs for a swing high search, lows for a swing low search.
        left: Bars required to the left.
        right: Bars required to the right before the pivot is confirmed.
        kind: ``high`` or ``low``.

    Returns:
        Bar indices, ascending.
    """
    total = len(values)
    width = left + right + 1
    if total < width or width < 1:
        return []

    found: list[int] = []
    for centre in range(left, total - right):
        value = values[centre]
        if not math.isfinite(value):
            continue
        neighbours = list(values[centre - left : centre]) + list(
            values[centre + 1 : centre + right + 1]
        )
        if not neighbours:
            continue
        if kind == "high":
            if value < max(neighbours) or value <= min(neighbours):
                continue
        elif value > min(neighbours) or value >= max(neighbours):
            continue
        # One pivot per plateau: every bar of a run of equal values passes the
        # test above, so a run collapses onto its first member.
        if found and found[-1] == centre - 1 and values[centre - 1] == value:
            continue
        found.append(centre)
    return found


def _zigzag(candidates: list[Pivot], threshold: float) -> list[Pivot]:
    """Prune pivots whose retracement is smaller than ``threshold``.

    The classic zigzag walk. A same-side candidate replaces the running pivot
    when it is more extreme, so the true top of a long leg survives even when the
    wiggles either side of it are tiny. An opposite-side candidate is accepted
    only when the move away from the running pivot clears the threshold.

    Args:
        candidates: Fractals from both sides, ascending by bar index.
        threshold: Minimum retracement in price units.

    Returns:
        A strictly alternating high, low, high sequence, ascending by index.
    """
    kept: list[Pivot] = []
    for candidate in candidates:
        if not kept:
            kept.append(candidate)
            continue
        last = kept[-1]
        if candidate.kind == last.kind:
            more_extreme = (
                candidate.price > last.price
                if candidate.kind == "high"
                else candidate.price < last.price
            )
            if more_extreme:
                kept[-1] = candidate
        elif abs(candidate.price - last.price) >= threshold:
            kept.append(candidate)
    return kept


def swing_pivots(
    bars: Bars,
    lo: int = 0,
    hi: int | None = None,
    *,
    left: int = DEFAULT_LEFT,
    right: int = DEFAULT_RIGHT,
    significance: float = 0.0,
) -> tuple[list[Pivot], list[Pivot]]:
    """Confirmed swing highs and lows inside a bar span.

    Fractals are detected over the whole window and only then clipped to
    ``lo..hi``, so a pivot near the right edge of the viewport is still confirmed
    by bars the operator cannot see.

    Args:
        bars: The candle window.
        lo: First bar of the visible span, inclusive.
        hi: Last bar of the visible span, inclusive. None means the last bar.
        left: Bars required to the left of the extreme.
        right: Bars required to the right before the pivot is confirmed. The
            last ``right`` bars can never produce a pivot.
        significance: Retracement filter as a fraction of the visible range. 0.0
            returns every confirmed fractal; anything above runs the zigzag prune
            and the result strictly alternates.

    Returns:
        ``(highs, lows)``, each ascending by bar index.
    """
    total = len(bars)
    if total == 0:
        return [], []
    last = total - 1 if hi is None else min(int(hi), total - 1)
    first = max(int(lo), 0)
    if last < first:
        return [], []

    candidates: list[Pivot] = []
    for kind, values in (("high", bars.highs), ("low", bars.lows)):
        for index in _fractals(values, max(int(left), 0), max(int(right), 0), kind):
            if first <= index <= last:
                candidates.append(
                    Pivot(
                        index=index,
                        time=bars.times[index],
                        price=values[index],
                        kind=kind,
                    )
                )
    candidates.sort(key=lambda pivot: (pivot.index, 0 if pivot.kind == "high" else 1))

    window_range = bars.span(first, last)
    if significance > 0.0 and window_range > 0.0:
        candidates = _zigzag(candidates, float(significance) * window_range)

    return (
        [pivot for pivot in candidates if pivot.kind == "high"],
        [pivot for pivot in candidates if pivot.kind == "low"],
    )


def significant_pivots(
    bars: Bars, lo: int = 0, hi: int | None = None
) -> tuple[list[Pivot], list[Pivot]]:
    """Swing points at the strictest threshold this chart will actually support.

    Walks :data:`SIGNIFICANCE_LADDER` from strict to loose and stops as soon as
    both sides carry :data:`MIN_VERTICES`. A clean trend has shallow pullbacks
    and needs a loose threshold; a choppy range needs a strict one, and picking
    one number for both draws a sawtooth on the second.

    Args:
        bars: The candle window.
        lo: First bar of the visible span, inclusive.
        hi: Last bar of the visible span, inclusive.

    Returns:
        ``(highs, lows)`` at the first threshold that reached the vertex count,
        or at the loosest rung when none did.
    """
    highs: list[Pivot] = []
    lows: list[Pivot] = []
    for threshold in SIGNIFICANCE_LADDER:
        highs, lows = swing_pivots(bars, lo, hi, significance=threshold)
        if len(highs) >= MIN_VERTICES and len(lows) >= MIN_VERTICES:
            break
    return highs, lows


# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------


def support_resistance(
    bars: Bars,
    lo: int = 0,
    hi: int | None = None,
    *,
    reference: float | None = None,
    min_touches: int = 2,
) -> list[dict[str, Any]]:
    """Horizontal levels where swing points cluster.

    Swing highs and swing lows are grouped separately, so a level built from
    highs is reported as such and never has a low averaged into it. Grouping is
    agglomerative rather than histogram binning, so two pivots a rupee apart are
    never split by an arbitrary bin edge. The reported price is the pivot in the
    group nearest its mean, a price that actually printed, rather than the mean
    itself, which would move with every change of zoom.

    Args:
        bars: The candle window.
        lo: First bar of the visible span, inclusive.
        hi: Last bar of the visible span, inclusive.
        reference: The price ``role`` is read against, normally the live last
            price. None falls back to the last close in the span.
        min_touches: Drop clusters touched fewer times than this.

    Returns:
        Dicts carrying ``price``, ``touches``, ``role`` (``support`` or
        ``resistance``), ``side`` (which pivots built it), ``first_time`` and
        ``last_time``, strongest first: touch count, then most recently touched.
    """
    total = len(bars)
    if total == 0:
        return []
    last = total - 1 if hi is None else min(int(hi), total - 1)
    first = max(int(lo), 0)
    if last < first:
        return []

    window_range = bars.span(first, last)
    if window_range <= 0:
        return []

    highs, lows = swing_pivots(bars, first, last)
    visible = last - first + 1
    buckets = min(48, max(12, visible // 8))
    tolerance = window_range / max(buckets, 1)
    if tolerance <= 0:
        return []

    mark = reference if reference is not None and math.isfinite(reference) else None
    if mark is None:
        mark = float(bars.closes[last])

    levels: list[dict[str, Any]] = []
    for side, pivots in (("high", highs), ("low", lows)):
        ordered = sorted(pivots, key=lambda pivot: pivot.price)
        if not ordered:
            continue
        groups: list[list[Pivot]] = [[ordered[0]]]
        for pivot in ordered[1:]:
            if pivot.price - groups[-1][0].price <= tolerance:
                groups[-1].append(pivot)
            else:
                groups.append([pivot])

        for group in groups:
            if len(group) < max(int(min_touches), 1):
                continue
            prices = [pivot.price for pivot in group]
            mean = sum(prices) / len(prices)
            price = min(prices, key=lambda value: (abs(value - mean), value))
            levels.append(
                {
                    "price": round(float(price), 4),
                    "touches": len(group),
                    "role": "resistance" if price >= mark else "support",
                    "side": side,
                    "first_time": float(min(pivot.time for pivot in group)),
                    "last_time": float(max(pivot.time for pivot in group)),
                }
            )

    levels.sort(key=lambda level: (-level["touches"], -level["last_time"]))
    return levels


# ---------------------------------------------------------------------------
# Lines
# ---------------------------------------------------------------------------


def fit_line(
    pivots: Sequence[Pivot],
    tolerance_pct: float = TOUCH_TOLERANCE_PCT,
    *,
    bars: Bars | None = None,
    side: str = "",
) -> dict[str, Any] | None:
    """Find the straight line touching the most of these pivots and containing them.

    Every pair defines a candidate and the pair with the most other pivots within
    ``tolerance_pct`` of it wins. The line runs through two real pivots rather
    than through a regression cloud, so the drawn line actually touches the bars
    it claims to touch. Ties go to the wider span, because a line across the whole
    window says more than one joining two adjacent swings, then to the tighter
    residual.

    **Containment decides before any of that**, when ``bars`` and ``side`` are
    given, and it is what separates a trendline from a regression. A resistance
    line has essentially nothing above it and a support line essentially nothing
    below it: that is the definition, not a refinement of it. Ranking on touches
    alone produced lines that price crossed 22 and 19 times out of 107 bars on a
    real daily chart, each one plausible in isolation and neither one a line any
    trader would draw. Breaks are counted first and fewest wins, so a line that
    holds beats a line that fits.

    A small tolerance is allowed on a break for the same reason it is allowed on
    a touch: a wick a rupee through a line has not broken it.

    Args:
        pivots: Swing points from one side. Mixing both sides is allowed but is
            rarely what a trendline means.
        tolerance_pct: How close a pivot has to sit to count as a touch, as a
            percentage of the line's price at that bar.
        bars: The candle window, for counting breaks. Without it the old
            touch-only ranking applies, which is right for a caller that has
            pivots but no bars.
        side: ``resistance`` to count highs above the line, ``support`` to count
            lows below it. Ignored when ``bars`` is None.

    Returns:
        ``from`` and ``to`` pivots, ``slope`` in price per second, ``touches``,
        ``r2`` over the touching pivots only, and ``breaks``, the number of bars
        that pierced it. None when fewer than two usable pivots were supplied.
    """
    points = [pivot for pivot in pivots if math.isfinite(pivot.time) and math.isfinite(pivot.price)]
    if len(points) < 2:
        return None

    points.sort(key=lambda pivot: pivot.time)
    if len(points) > MAX_TRENDLINE_PIVOTS:
        points = points[-MAX_TRENDLINE_PIVOTS:]

    tolerance = max(float(tolerance_pct), 0.0) / 100.0
    contain = bars is not None and side in ("resistance", "support") and len(bars.times) > 0

    def breaks(slope: float, intercept: float, since: float) -> int:
        """Bars after ``since`` that pierced this line.

        **Only from the anchor forward**, which is the whole difference between
        a trendline and an envelope. A line drawn from a swing in May says
        nothing about April, and counting April against it forces the fit out to
        whatever sits above the entire window: measured, that moved a resistance
        line from the 1,372 swing a trader would use to the 1,473 all-time high,
        which contains everything and describes nothing.

        Zero when containment is not being checked.
        """
        if not contain:
            return 0
        assert bars is not None
        count = 0
        for index, moment in enumerate(bars.times):
            if moment < since:
                continue
            value = slope * moment + intercept
            allowance = abs(value) * tolerance
            if side == "resistance":
                if bars.highs[index] > value + allowance:
                    count += 1
            elif bars.lows[index] < value - allowance:
                count += 1
        return count

    best_score: tuple[int, float, int, float, float] | None = None
    best_pair: tuple[int, int] | None = None

    for i in range(len(points) - 1):
        for j in range(i + 1, len(points)):
            width = points[j].time - points[i].time
            if width <= 0:
                continue
            slope = (points[j].price - points[i].price) / width
            intercept = points[i].price - slope * points[i].time
            residuals = [abs(point.price - (slope * point.time + intercept)) for point in points]
            allowances = [abs(slope * point.time + intercept) * tolerance for point in points]
            hits = [
                index for index, residual in enumerate(residuals) if residual <= allowances[index]
            ]
            error = sum(residuals[index] ** 2 for index in hits)
            # Fewest breaks first, negated so a larger tuple is still better.
            # Then how recently the line was last touched, because a trendline
            # is only worth drawing while it is still in play: a support that
            # last held in July, with thirty bars since, is history rather than
            # a level, and ranking on touches alone kept choosing exactly that.
            # Only then touches, span and residual, which is the old ranking
            # applied among the lines that both hold and are still live.
            score = (
                -breaks(slope, intercept, points[i].time),
                float(points[j].time),
                len(hits),
                float(width),
                -error,
            )
            if best_score is None or score > best_score:
                best_score = score
                best_pair = (i, j)

    if best_pair is None:
        return None

    start, end = points[best_pair[0]], points[best_pair[1]]
    slope = (end.price - start.price) / (end.time - start.time)
    intercept = start.price - slope * start.time
    fitted = [slope * point.time + intercept for point in points]
    touching = [
        (point.price, value)
        for point, value in zip(points, fitted, strict=True)
        if abs(point.price - value) <= abs(value) * tolerance
    ]

    if len(touching) < 3:
        r2 = 1.0
    else:
        observed = [price for price, _value in touching]
        mean = sum(observed) / len(observed)
        total = sum((price - mean) ** 2 for price in observed)
        residual = sum((price - value) ** 2 for price, value in touching)
        r2 = 1.0 if total <= 0 else 1.0 - residual / total

    return {
        "from": start,
        "to": end,
        "slope": float(slope),
        "touches": len(touching),
        "r2": round(float(r2), 4),
        "breaks": int(-best_score[0]) if best_score is not None else 0,
    }


def structure(highs: Sequence[Pivot], lows: Sequence[Pivot]) -> dict[str, Any]:
    """Read the sequence of swing highs and lows as a trend verdict.

    Args:
        highs: Swing highs, ascending by time.
        lows: Swing lows, ascending by time.

    Returns:
        The four transition counts and a plain sentence naming the structure.
    """
    higher_highs = sum(1 for a, b in zip(highs, highs[1:], strict=False) if b.price > a.price)
    lower_highs = sum(1 for a, b in zip(highs, highs[1:], strict=False) if b.price < a.price)
    higher_lows = sum(1 for a, b in zip(lows, lows[1:], strict=False) if b.price > a.price)
    lower_lows = sum(1 for a, b in zip(lows, lows[1:], strict=False) if b.price < a.price)

    if lower_highs > higher_highs and lower_lows > higher_lows:
        verdict = "lower highs and lower lows, a downtrend"
    elif higher_highs > lower_highs and higher_lows > lower_lows:
        verdict = "higher highs and higher lows, an uptrend"
    elif lower_highs > higher_highs and higher_lows > lower_lows:
        verdict = "lower highs into higher lows, a contracting range"
    elif higher_highs > lower_highs and lower_lows > higher_lows:
        verdict = "higher highs and lower lows, an expanding range"
    else:
        verdict = "no clean sequence of highs and lows"

    return {
        "higher_highs": higher_highs,
        "lower_highs": lower_highs,
        "higher_lows": higher_lows,
        "lower_lows": lower_lows,
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------


def zone(bars: Bars, kind: str, lo: int = 0, hi: int | None = None) -> dict[str, Any] | None:
    """Derive a demand or supply zone from the bars around a real swing.

    A demand zone is the base price left behind before an advance: the lowest low
    of the three bars around the most recent significant swing low, up to the
    highest candle body in that same group. A supply zone is the mirror. Both
    edges therefore printed, and neither is a number anybody typed.

    Args:
        bars: The candle window.
        kind: ``demand`` for the base under price, ``supply`` for the ceiling
            above it.
        lo: First bar of the visible span, inclusive.
        hi: Last bar of the visible span, inclusive.

    Returns:
        ``low``, ``high``, ``from_time``, ``to_time``, ``pivot_time``,
        ``pivot_price`` and ``bars_since``, or None when the span holds no swing
        of that side.
    """
    total = len(bars)
    if total == 0:
        return None
    last = total - 1 if hi is None else min(int(hi), total - 1)
    first = max(int(lo), 0)
    if last < first:
        return None

    highs, lows = significant_pivots(bars, first, last)
    pivots = lows if kind == "demand" else highs
    if not pivots:
        return None

    anchor = pivots[-1]
    left = max(anchor.index - 1, 0)
    right = min(anchor.index + 1, total - 1)
    bodies_high = max(
        max(bars.opens[index], bars.closes[index]) for index in range(left, right + 1)
    )
    bodies_low = min(min(bars.opens[index], bars.closes[index]) for index in range(left, right + 1))

    if kind == "demand":
        band_low = min(bars.lows[left : right + 1])
        band_high = bodies_high
    else:
        band_low = bodies_low
        band_high = max(bars.highs[left : right + 1])

    if band_high <= band_low:
        return None

    return {
        "low": round(float(band_low), 4),
        "high": round(float(band_high), 4),
        "from_time": float(bars.times[left]),
        "to_time": float(bars.times[last]),
        "pivot_time": float(anchor.time),
        "pivot_price": round(float(anchor.price), 4),
        "bars_since": int(last - anchor.index),
    }


def consolidation(
    bars: Bars,
    lo: int = 0,
    hi: int | None = None,
    *,
    min_bars: int = 12,
) -> dict[str, Any] | None:
    """Find the widest stretch where price stayed inside one narrow band.

    A consolidation is not a swing, which is why it cannot come out of
    :func:`zone`: that derives a band from a pivot and the bars beside it, and a
    range has no pivot. This looks for the opposite, the longest run that went
    nowhere.

    The method is a widest-window scan. For every start bar it extends forward
    while the running high-low span stays inside ``tolerance`` of the window's
    own midpoint, and keeps the longest such run. Ties break on the tighter
    band, because two runs of equal length are better described by the one that
    held price more closely.

    Tolerance is a fraction of price rather than an absolute, so the same rule
    works on an index at 23,000 and a stock at 300. It is derived from the span
    actually on screen rather than fixed: a quiet chart and a volatile one
    disagree about what counts as narrow, and a constant would find a range in
    every quiet chart and none in any volatile one.

    Two rules decide a candidate, and it takes both
    ------------------------------------------------

    **The band may be up to** :data:`_RANGE_BAND_FRACTION` **of the visible
    move.** A consolidation is the whole sideways stretch, bounded by its own
    extremes, not the tightest band that happens to fit inside one. A third of
    the range was too mean for that: on RELIANCE NSE daily over 2026-04-01 to
    2026-09-04 the stretch a trader boxes is 1249.80 to 1345.90 across 68 bars,
    96.10 points of a 223.60 point window, and a third allowed only 74.53, so
    the long obvious run was refused and a 29 bar sub-window inside it,
    1265.90 to 1337.00, was reported instead.

    **And price must not have travelled more than**
    :data:`_RANGE_DRIFT_FRACTION` **of that band's height between the run's two
    ends.** A trending leg also fits inside a tall box; what makes it a trend is
    that it came out the far side. Net progress is bounded by the band by
    construction, both closes being inside it, so the fraction reads directly as
    how much of its own box price actually crossed: near 1 is a leg, near 0 is a
    base. Widening the band without this rule starts calling trends ranges,
    measured: on TITAN NSE daily over 2026-06-01 to 2026-09-04 it boxed 30 bars
    price crossed 0.86 of, and the rule replaces that with the 28 genuinely flat
    bars beside it at 0.37.

    Args:
        bars: The candle window.
        lo: First bar of the visible span, inclusive.
        hi: Last bar of the visible span, inclusive.
        min_bars: Shortest run worth calling a consolidation. Below about a
            dozen bars a range is indistinguishable from noise.

    Returns:
        ``low``, ``high``, ``from_time``, ``to_time``, ``bars``, ``width_pct``,
        ``drift_pct`` (net progress as a percentage of the band, the trend test
        this run passed) and ``touches``, or None when nothing in the span held
        a band that long without trending out of it.
    """
    total = len(bars)
    if total == 0:
        return None
    last = total - 1 if hi is None else min(int(hi), total - 1)
    first = max(int(lo), 0)
    span = last - first + 1
    if span < min_bars:
        return None

    visible_high = max(bars.highs[first : last + 1])
    visible_low = min(bars.lows[first : last + 1])
    visible_range = visible_high - visible_low
    if visible_range <= 0:
        return None

    tolerance = visible_range * _RANGE_BAND_FRACTION

    best: tuple[int, float, int, int, float] | None = None
    for start in range(first, last - min_bars + 2):
        band_high = bars.highs[start]
        band_low = bars.lows[start]
        for end in range(start, last + 1):
            band_high = max(band_high, bars.highs[end])
            band_low = min(band_low, bars.lows[end])
            if band_high - band_low > tolerance:
                break
            length = end - start + 1
            if length < min_bars:
                continue
            width = band_high - band_low
            # Net progress across the run. A leg that fits the band is still a
            # leg, and this is what tells the two apart.
            drift = abs(bars.closes[end] - bars.closes[start])
            if width <= 0 or drift > _RANGE_DRIFT_FRACTION * width:
                continue
            if best is None or length > best[0] or (length == best[0] and width < best[1]):
                best = (length, width, start, end, drift)

    if best is None:
        return None

    length, width, start, end, drift = best
    band_high = max(bars.highs[start : end + 1])
    band_low = min(bars.lows[start : end + 1])
    if band_high <= band_low:
        return None

    # How often price came back to an edge. A range nobody tested twice is a
    # pause, and saying how many touches it had lets the operator judge that
    # rather than taking the rectangle on trust.
    edge = (band_high - band_low) * 0.15
    touches = sum(
        1
        for index in range(start, end + 1)
        if bars.highs[index] >= band_high - edge or bars.lows[index] <= band_low + edge
    )

    return {
        "low": round(float(band_low), 4),
        "high": round(float(band_high), 4),
        "from_time": float(bars.times[start]),
        "to_time": float(bars.times[end]),
        "bars": int(length),
        "width_pct": round(float((band_high - band_low) / band_low * 100.0), 2),
        "drift_pct": round(float(drift / (band_high - band_low) * 100.0), 1),
        "touches": int(touches),
    }


# ---------------------------------------------------------------------------
# Candlestick patterns
# ---------------------------------------------------------------------------


def _shape(bars: Bars, index: int) -> dict[str, float]:
    """Measure one candle into the proportions every detector below reads.

    Args:
        bars: The candle window.
        index: Bar index.

    Returns:
        ``body``, ``range``, ``upper`` and ``lower`` in price units, and
        ``bullish`` as 1.0 or 0.0.
    """
    open_price = bars.opens[index]
    close = bars.closes[index]
    top = max(open_price, close)
    bottom = min(open_price, close)
    return {
        "body": abs(close - open_price),
        "range": bars.highs[index] - bars.lows[index],
        "upper": bars.highs[index] - top,
        "lower": bottom - bars.lows[index],
        "bullish": 1.0 if close > open_price else 0.0,
    }


def _prior_move(bars: Bars, index: int) -> float:
    """Measure the move into a bar, used to give a reversal pattern its context.

    Args:
        bars: The candle window.
        index: The pattern bar.

    Returns:
        The change in close over the preceding :data:`_TREND_CONTEXT_BARS` bars.
        Positive means price rose into this bar. 0.0 when there is no history.
    """
    back = index - _TREND_CONTEXT_BARS
    if back < 0:
        return 0.0
    return float(bars.closes[index] - bars.closes[back])


def candlestick_patterns(
    bars: Bars, scan: int = _DEFAULT_CANDLE_SCAN, lo: int = 0, hi: int | None = None
) -> list[dict[str, Any]]:
    """Detect candlestick patterns on the most recent visible bars.

    Every test is a proportion of the bar's own range, so the same rule holds on
    a 20 rupee stock and a 2000 rupee one. Single-bar reversals also check the
    move into them, because a hammer after a rally is a hanging man and calling
    both a hammer is how a pattern list stops being worth reading.

    Args:
        bars: The candle window.
        scan: How many bars back from ``hi`` to examine.
        lo: First bar of the visible span, inclusive.
        hi: Last bar of the visible span, inclusive. None means the last bar. The
            scan ends here rather than at the end of the fetched window, so an
            operator who has scrolled back is told about the bars they can see.

    Returns:
        One dict per hit: ``name``, ``bias`` (``bullish``, ``bearish`` or
        ``neutral``), ``index``, ``time``, ``price`` (the extreme the marker
        belongs at) and ``bars`` (how many candles the pattern spans). Newest
        last.
    """
    total = len(bars)
    if total < 2:
        return []

    last = total - 1 if hi is None else min(int(hi), total - 1)
    start = max(last - max(int(scan), 1) + 1, max(int(lo), 0), 1)
    if last < start:
        return []
    hits: list[dict[str, Any]] = []

    def record(index: int, name: str, bias: str, width: int = 1) -> None:
        price = bars.highs[index] if bias == "bearish" else bars.lows[index]
        hits.append(
            {
                "name": name,
                "bias": bias,
                "index": index,
                "time": float(bars.times[index]),
                "price": round(float(price), 4),
                "bars": width,
            }
        )

    for index in range(start, last + 1):
        here = _shape(bars, index)
        before = _shape(bars, index - 1)
        span = here["range"]
        if span <= 0:
            continue
        body = here["body"]
        rising = _prior_move(bars, index) > 0

        if body <= 0.1 * span:
            record(index, "doji", "neutral")
        elif body >= 0.9 * span:
            record(index, "marubozu", "bullish" if here["bullish"] else "bearish")
        elif body <= 0.3 * span and here["upper"] >= body and here["lower"] >= body:
            record(index, "spinning top", "neutral")

        if body > 0 and here["lower"] >= 2 * body and here["upper"] <= body:
            record(index, "hanging man" if rising else "hammer", "bearish" if rising else "bullish")
        if body > 0 and here["upper"] >= 2 * body and here["lower"] <= body:
            record(
                index,
                "shooting star" if rising else "inverted hammer",
                "bearish" if rising else "bullish",
            )

        # Two bar patterns.
        prev_open, prev_close = bars.opens[index - 1], bars.closes[index - 1]
        prev_top, prev_bottom = max(prev_open, prev_close), min(prev_open, prev_close)
        prev_mid = (prev_open + prev_close) / 2.0
        if before["body"] > 0 and body > 0:
            if (
                not before["bullish"]
                and here["bullish"]
                and bars.opens[index] <= prev_bottom
                and bars.closes[index] >= prev_top
            ):
                record(index, "bullish engulfing", "bullish", 2)
            elif (
                before["bullish"]
                and not here["bullish"]
                and bars.opens[index] >= prev_top
                and bars.closes[index] <= prev_bottom
            ):
                record(index, "bearish engulfing", "bearish", 2)
            elif (
                not before["bullish"]
                and here["bullish"]
                and bars.opens[index] < bars.lows[index - 1]
                and prev_mid < bars.closes[index] < prev_open
            ):
                record(index, "piercing line", "bullish", 2)
            elif (
                before["bullish"]
                and not here["bullish"]
                and bars.opens[index] > bars.highs[index - 1]
                and prev_open < bars.closes[index] < prev_mid
            ):
                record(index, "dark cloud cover", "bearish", 2)
            elif (
                before["body"] >= 0.6 * before["range"]
                and body <= 0.5 * before["body"]
                and prev_bottom <= min(bars.opens[index], bars.closes[index])
                and max(bars.opens[index], bars.closes[index]) <= prev_top
            ):
                record(
                    index,
                    "bullish harami" if here["bullish"] else "bearish harami",
                    "bullish" if here["bullish"] else "bearish",
                    2,
                )

        equal = _EQUAL_FRACTION * span
        if (
            not before["bullish"]
            and here["bullish"]
            and abs(bars.lows[index] - bars.lows[index - 1]) <= equal
        ):
            record(index, "tweezer bottom", "bullish", 2)
        if (
            before["bullish"]
            and not here["bullish"]
            and abs(bars.highs[index] - bars.highs[index - 1]) <= equal
        ):
            record(index, "tweezer top", "bearish", 2)

        if bars.highs[index] <= bars.highs[index - 1] and bars.lows[index] >= bars.lows[index - 1]:
            record(index, "inside bar", "neutral", 2)
        elif bars.highs[index] > bars.highs[index - 1] and bars.lows[index] < bars.lows[index - 1]:
            record(index, "outside bar", "neutral", 2)

        # Three bar patterns.
        if index < 2:
            continue
        first = _shape(bars, index - 2)
        middle = before
        first_mid = (bars.opens[index - 2] + bars.closes[index - 2]) / 2.0
        if (
            first["body"] >= 0.5 * first["range"]
            and middle["body"] <= 0.4 * middle["range"]
            and body >= 0.5 * span
        ):
            if not first["bullish"] and here["bullish"] and bars.closes[index] > first_mid:
                record(index, "morning star", "bullish", 3)
            elif first["bullish"] and not here["bullish"] and bars.closes[index] < first_mid:
                record(index, "evening star", "bearish", 3)

        rising_closes = bars.closes[index] > bars.closes[index - 1] > bars.closes[index - 2]
        falling_closes = bars.closes[index] < bars.closes[index - 1] < bars.closes[index - 2]
        all_bullish = first["bullish"] and middle["bullish"] and here["bullish"]
        all_bearish = not (first["bullish"] or middle["bullish"] or here["bullish"])
        if all_bullish and rising_closes:
            record(index, "three white soldiers", "bullish", 3)
        elif all_bearish and falling_closes:
            record(index, "three black crows", "bearish", 3)

    return hits


# ---------------------------------------------------------------------------
# Chart patterns
# ---------------------------------------------------------------------------


def chart_patterns(
    bars: Bars,
    highs: Sequence[Pivot],
    lows: Sequence[Pivot],
    lo: int = 0,
    hi: int | None = None,
) -> list[dict[str, Any]]:
    """Read multi-swing chart patterns off the pivot sequence.

    Every pattern is a statement about pivots that printed, so its anchors are
    real bars. Tolerance is a fraction of the visible range, which is what lets
    one rule describe a double top on any instrument, and it is measured over the
    same span the pivots came from: scaling it off the whole fetched frame while
    the pivots came from the viewport would call two highs equal on a zoomed-in
    chart purely because the fetch reached back further.

    Args:
        bars: The candle window, used for the range the tolerance scales from.
        highs: Swing highs, ascending by time.
        lows: Swing lows, ascending by time.
        lo: First bar of the visible span, inclusive.
        hi: Last bar of the visible span, inclusive. None means the last bar.

    Returns:
        One dict per pattern: ``name``, ``bias`` and ``anchors``, a list of
        ``{time, price}`` in the order they should be joined. Empty when the
        pivot sequence supports none.
    """
    total = len(bars)
    if total == 0:
        return []
    last = total - 1 if hi is None else min(int(hi), total - 1)
    window = bars.span(max(int(lo), 0), last)
    if window <= 0:
        return []
    equal = _EQUAL_FRACTION * window
    found: list[dict[str, Any]] = []

    def anchors(*pivots: Pivot) -> list[dict[str, float]]:
        return [pivot.as_anchor() for pivot in pivots]

    if len(highs) >= 2 and lows:
        a, b = highs[-2], highs[-1]
        trough = [pivot for pivot in lows if a.time < pivot.time < b.time]
        if abs(a.price - b.price) <= equal and trough:
            found.append(
                {
                    "name": "double top",
                    "bias": "bearish",
                    "anchors": anchors(a, min(trough, key=lambda p: p.price), b),
                }
            )

    if len(lows) >= 2 and highs:
        a, b = lows[-2], lows[-1]
        peak = [pivot for pivot in highs if a.time < pivot.time < b.time]
        if abs(a.price - b.price) <= equal and peak:
            found.append(
                {
                    "name": "double bottom",
                    "bias": "bullish",
                    "anchors": anchors(a, max(peak, key=lambda p: p.price), b),
                }
            )

    if len(highs) >= 3 and len(lows) >= 2:
        left, head, right = highs[-3], highs[-2], highs[-1]
        neck = [pivot for pivot in lows if left.time < pivot.time < right.time]
        if (
            head.price > left.price
            and head.price > right.price
            and abs(left.price - right.price) <= equal
            and len(neck) >= 2
        ):
            found.append(
                {
                    "name": "head and shoulders",
                    "bias": "bearish",
                    "anchors": anchors(left, neck[0], head, neck[-1], right),
                }
            )

    if len(lows) >= 3 and len(highs) >= 2:
        left, head, right = lows[-3], lows[-2], lows[-1]
        neck = [pivot for pivot in highs if left.time < pivot.time < right.time]
        if (
            head.price < left.price
            and head.price < right.price
            and abs(left.price - right.price) <= equal
            and len(neck) >= 2
        ):
            found.append(
                {
                    "name": "inverse head and shoulders",
                    "bias": "bullish",
                    "anchors": anchors(left, neck[0], head, neck[-1], right),
                }
            )

    if len(highs) >= 2 and len(lows) >= 2:
        high_step = highs[-1].price - highs[-2].price
        low_step = lows[-1].price - lows[-2].price
        flat_highs = abs(high_step) <= equal
        flat_lows = abs(low_step) <= equal
        shape = None
        bias = "neutral"
        if flat_highs and low_step > equal:
            shape, bias = "ascending triangle", "bullish"
        elif flat_lows and high_step < -equal:
            shape, bias = "descending triangle", "bearish"
        elif high_step < -equal and low_step > equal:
            shape = "symmetrical triangle"
        elif flat_highs and flat_lows:
            shape = "rectangle range"
        if shape:
            found.append(
                {
                    "name": shape,
                    "bias": bias,
                    "anchors": anchors(highs[-2], highs[-1], lows[-2], lows[-1]),
                }
            )

    return found
