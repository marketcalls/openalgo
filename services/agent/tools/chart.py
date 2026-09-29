"""Chart tools: read the chart the operator is looking at, and draw on it.

This is the toolkit that makes the chart panel different from the chat page, and
the difference is the **context**. The panel reports its symbol, exchange,
interval, viewport, indicators and the operator's own drawings with every
message, so no tool here takes a symbol, an exchange, an interval or a date: they
all come off :class:`~services.agent.chart_contract.ChartView`. A model that has
to ask what is on screen has already failed at the one thing this surface is for.

Provenance, which is stricter here than anywhere else in this project
--------------------------------------------------------------------

A level drawn on a chart is read as a fact about the market, so **no tool here
accepts a price**. Every number that reaches the canvas is computed by
``services.agent.chart_geometry`` from candles this process fetched through
``services.history_service``. The model chooses which structure is interesting;
it never chooses what the numbers are. A tool that took a price and drew it would
have handed the model a pen.

The one string a caller may pass through to the canvas is ``note``, and
:meth:`ChartToolkit._note` puts two controls on it. ``chart_contract.safe_note``
removes every digit, because a caption reading "support 1450" would be a price
the model chose wearing the clothes of one the candles gave, and on a canvas the
operator cannot tell them apart. Then the taint boundary keeps only the words
that appear in the operator's own message for the turn, so a caption is provably
theirs rather than something the model invented or copied out of a poisoned tool
result. Every other string argument is a closed vocabulary checked against a
fixed tuple, so nothing else the model types can reach the chart at all.

Grouping
--------

Everything drawn goes into one of ``chart_contract.GROUPS`` and every shape is
id'd ``ai:{group}:{index}``. A clear removes drawings under that prefix and
nothing else, so the operator's own markup survives. **An agent that wipes an
operator's markup is worse than one that draws nothing.**

A draw **replaces** its group. Asking twice for levels redraws them rather than
stacking a second set on the first.

No order tools
--------------

This surface is for reading and drawing. The registry gives the order toolkit
``surfaces=CHAT_ONLY``, so an order tool is not merely discouraged here, it is
absent from the model's schema. Nothing in this file may change that, and no
tool here mutates anything, so none requires confirmation and none writes an
audit row.

Threading
---------

Every tool runs on the agent's real OS thread. The candle fetch goes through
``OpenAlgoToolkit.service_call``, which is safe from either world, and the
geometry is pure Python on tuples. Nothing here builds a lock, a queue or a
thread. See CLAUDE.md, "Nothing may block or be blocked across the eventlet
boundary".
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from agno.exceptions import RetryAgentRun

from services.agent import chart_contract as cc
from services.agent import chart_geometry as geom
from services.agent.frames import ChartCommand
from services.agent.indicators.compute import IndicatorError, compute
from services.agent.prompts import wrap_tool_result
from services.agent.settings import PROJECT_ROOT
from services.agent.tools import context_value
from services.agent.tools.base import OpenAlgoToolkit, format_price
from services.agent.tools.market import (
    BrokerIntervals,
    candle_columns,
    candle_frame,
    ist_label,
    lookback_range,
    normalise_interval,
    normalise_pair,
)
from services.agent.tools.websearch import (
    DECISION_CONSTRAINED,
    DECISION_VERBATIM,
    constrain_query,
    operator_message,
)
from services.agent.viz_sink import emit_frame, sink_of
from services.history_service import get_history
from services.intervals_service import get_intervals
from utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from services.agent.tools import ToolContext

logger = get_logger(__name__)

__all__ = ["DEFAULT_LOOKBACK", "MAX_LOOKBACK", "MIN_LOOKBACK", "ChartToolkit"]

#: Bars fetched when the model names no lookback. Three hundred daily candles is
#: over a year of structure and clears the warm-up of every indicator below.
DEFAULT_LOOKBACK = 300

#: Floor on the lookback. Below this the pivot detector has nothing to work with
#: and would answer "no structure" about a chart that plainly has some.
MIN_LOOKBACK = 60

#: Ceiling on the lookback. Past this the fetch is slow, the pivot search is
#: quadratic in the pivots it finds, and the extra bars are off screen anyway.
MAX_LOOKBACK = 1500

#: Levels one call may draw. More than eight horizontal lines is a grid.
MAX_LEVELS = 8

#: Candlestick markers one call may place. The most recent are the ones a trader
#: is acting on; a marker on every doji of the last year is noise.
MAX_MARKERS = 8

#: Candlestick patterns are looked for over this many bars at the right edge of
#: the viewport, whatever lookback the swing detector was given. A hammer six
#: months ago is history; the lookback sizes the structure, not the signal.
CANDLE_SCAN_BARS = 30

#: Said when the panel sent no usable context. The model is told plainly rather
#: than being allowed to guess an instrument.
_NO_CHART = (
    "No chart context came with this message, so there is nothing to read or draw on. "
    "Tell the operator to open a chart on the trading terminal, and do not guess a "
    "symbol, an exchange or an interval."
)

#: Said when a drawing was computed but the surface has nowhere to send it.
_NO_SINK = (
    "This surface cannot apply chart commands, so nothing was drawn. Report the levels "
    "in prose and do not tell the operator that anything is on the chart."
)

_TREND_SIDES = ("auto", "support", "resistance", "both")
_ZONE_KINDS = ("demand", "supply", "both", "range")


@dataclass(frozen=True, slots=True)
class _Window:
    """One candle fetch, in both the shapes this toolkit reads it in.

    The geometry works on :class:`~services.agent.chart_geometry.Bars` and the
    indicators work on the DataFrame, and they have to be the same bars: two
    fetches would let an analysis quote a swing the momentum block never saw.
    Caching the pair together is what keeps that true.

    Attributes:
        bars: The window as geometry reads it.
        frame: The same window as ``openalgo.ta`` reads it.
        lo: First bar index inside the operator's viewport.
        hi: Last bar index inside the operator's viewport.
        meta: The accounting every result repeats: instrument, interval, bars
            fetched, bars analysed, and the viewport in IST.
    """

    bars: geom.Bars
    frame: Any
    lo: int = 0
    hi: int = 0
    meta: dict[str, Any] = field(default_factory=dict)


#: A chart indicator id. Kebab-case is the openalgo-charts convention and most
#: of its ids carry a hyphen, so a pattern allowing only underscores would
#: reject more than half the catalogue.
_INDICATOR_ID = re.compile(r"\A[a-z][a-z0-9-]{1,31}\Z")

#: The generated catalogue of what the chart can draw, read once per process.
#: Generated by ``frontend/scripts/generate-chart-indicators.mjs`` and committed,
#: because a production server has no Node.js and a plain ``git pull`` has to be
#: enough to upgrade the UI.
#:
#: Rooted at the module that already owns the repository root rather than at a
#: fresh ``parents[n]`` count. Counting it here got it wrong: this file is one
#: level deeper than the others that read ``docs/prompt/``, so the copied
#: ``parents[2]`` landed on ``services/docs/prompt/`` and the catalogue was never
#: readable. The tools degraded exactly as designed and said nothing, which is
#: why nobody noticed.
_CHART_INDICATOR_DOC = PROJECT_ROOT / "docs" / "prompt" / "indicators" / "chart-indicators.md"

_CATALOGUE_LINE = re.compile(r"^- `([a-z0-9-]+)` (.+?) \((.+)\)$")

_catalogue_cache: list[dict[str, str]] | None = None


def _chart_indicator_catalogue() -> list[dict[str, str]]:
    """The indicators the chart can draw, parsed from the generated catalogue.

    Read once and kept, because the file only changes when the package is
    upgraded and the process is restarted for that anyway.

    A missing or unreadable file returns an empty list rather than raising. The
    tools degrade to passing the operator's name straight through to the chart,
    which checks its own registry, so a stale install loses the listing and not
    the feature.

    Returns:
        Dicts of ``id``, ``name`` and ``category``, ordered as generated.
    """
    global _catalogue_cache
    if _catalogue_cache is not None:
        return _catalogue_cache

    rows: list[dict[str, str]] = []
    try:
        category = "Other"
        for line in _CHART_INDICATOR_DOC.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                category = line[3:].strip()
                continue
            match = _CATALOGUE_LINE.match(line.strip())
            if match:
                rows.append({"id": match.group(1), "name": match.group(2), "category": category})
    except Exception:
        logger.exception("Could not read the chart indicator catalogue")
        rows = []

    _catalogue_cache = rows
    return rows


class ChartToolkit(OpenAlgoToolkit):
    """Read and mark up the chart the operator has open.

    Every tool is read-only against the account: they fetch candles, compute
    geometry and send drawing commands. None requires confirmation and none
    writes an audit row, because none of them changes anything an operator owns.
    """

    def __init__(self, context: ToolContext) -> None:
        """Register the chart tools.

        The chart view, the sink, the interval cache and the frame cache are all
        bound before ``super().__init__`` because agno introspects the bound
        methods the moment it receives them, and a method reading an attribute
        the instance does not have yet would fail during registration rather
        than during a call.

        Args:
            context: The run's tool context. Its ``extras`` carry the sink the
                surface created and the ``chart_context`` the panel sent.
        """
        self._sink = sink_of(context)
        self._view = cc.ChartView.from_payload(context_value(context, "chart_context"))
        self._intervals = BrokerIntervals(lambda: self.service_call(get_intervals))
        #: Candle windows already fetched during this run, keyed by the clamped
        #: bar count. The instrument and the interval are fixed by the chart
        #: context, so the count is the whole key, and an analysis followed by
        #: two draws is one broker call. Lives exactly as long as the run, so
        #: nothing here outlives the request that built it. The viewport bounds
        #: are not cached with it: they belong to the turn, not to the fetch.
        self._windows: dict[int, _Window] = {}

        super().__init__(
            context,
            name="chart",
            tools=[
                self.read_chart,
                self.analyse_chart,
                self.find_patterns,
                self.draw_levels,
                self.draw_trendline,
                self.draw_zone,
                self.clear_drawings,
                self.list_chart_indicators,
                self.add_chart_indicator,
                self.remove_chart_indicator,
            ],
        )

    # -- tools ---------------------------------------------------------------

    def read_chart(self) -> str:
        """Report what is on the chart right now. Draws nothing, fetches nothing.

        Everything here came with the operator's message, so this call is free
        and instant. Use it before commenting on the operator's own drawings,
        before deciding whether your markup is still on screen, and whenever you
        need the exact indicator settings or the drawing anchors, which the
        session summary does not carry.

        Reach for it only when you need those lists. The instrument, the
        interval, the viewport and the last price are already stated in your
        THIS SESSION instructions.

        Returns:
            JSON with the instrument and timeframe, the viewport, the indicators
            on the chart, the drawings the operator placed by hand with their
            anchors, and which of your own drawing groups are still on screen.
        """
        view = self._view
        if not view.is_open:
            return wrap_tool_result("read_chart", _NO_CHART)

        payload: dict[str, Any] = {
            "symbol": view.symbol,
            "exchange": view.exchange,
            "interval": view.interval,
            "chart_type": view.chart_type or "candlestick",
            "bars_loaded": view.bars_loaded,
            "visible_bars": view.visible_bars,
            "visible_from": ist_label(view.visible_from),
            "visible_to": ist_label(view.visible_to),
            "last_price": view.last_price,
            "timezone": "Asia/Kolkata",
            "indicators": [dict(item) for item in view.indicators],
            "operator_drawings": [
                {
                    "tool": item.get("tool", ""),
                    "anchors": [
                        {"at": ist_label(point.get("time")), "price": point.get("price")}
                        for point in item.get("points") or ()
                    ],
                    **({"text": item["text"]} if item.get("text") else {}),
                }
                for item in view.drawings
            ],
            "your_drawing_groups": list(view.agent_groups),
            "summary": self._summary(),
        }
        return self._wrapped("read_chart", payload)

    def analyse_chart(self, lookback_bars: int = 0) -> str:
        """Analyse the chart on screen: trend, structure and momentum. Draws nothing.

        One candle fetch answers all three, so this is one call rather than
        three. Everything it reports is computed here from real bars: the swing
        sequence, the slope of the fitted rails, the period range, and RSI, MACD,
        ADX and ATR from the same candles.

        Args:
            lookback_bars: How many candles to analyse, 60 to 1500. Pass 0 for
                the default of 300, which is what almost every question wants.

        Returns:
            JSON with the instrument and the window, a direction and a structure
            verdict built from the swing highs and lows, the slope per bar, the
            period high, low and change, and the latest reading and direction of
            each momentum indicator with a one line verdict.
        """
        view = self._view
        if not view.is_open:
            return wrap_tool_result("analyse_chart", _NO_CHART)

        window = self._window(lookback_bars)
        bars, lo, hi = window.bars, window.lo, window.hi
        highs, lows = geom.significant_pivots(bars, lo, hi)
        shape = geom.structure(highs, lows)
        seconds = geom.bar_seconds(bars)

        slopes: list[float] = []
        rails: dict[str, Any] = {}
        for name, fit in _rails(bars, highs, lows).items():
            per_bar = fit["slope"] * seconds
            slopes.append(per_bar)
            rails[name] = {
                "from": {"at": ist_label(fit["from"].time), "price": fit["from"].price},
                "to": {"at": ist_label(fit["to"].time), "price": fit["to"].price},
                "slope_per_bar": round(per_bar, 4),
                "touches": fit["touches"],
                "r2": fit["r2"],
                "breaks": fit["breaks"],
            }

        first_close = bars.closes[lo]
        last_close = bars.closes[hi]
        change_pct = (
            round((last_close - first_close) / first_close * 100, 2) if first_close else None
        )
        if not slopes:
            direction = "sideways"
        else:
            average = sum(slopes) / len(slopes)
            span = bars.span(lo, hi)
            drift = average * (hi - lo)
            direction = (
                "up" if drift > 0.15 * span else "down" if drift < -0.15 * span else "sideways"
            )

        payload: dict[str, Any] = {
            **window.meta,
            "direction": direction,
            "structure": shape["verdict"],
            "swing_counts": {
                key: shape[key]
                for key in ("higher_highs", "lower_highs", "higher_lows", "lower_lows")
            },
            "slope_per_bar": round(sum(slopes) / len(slopes), 4) if slopes else 0.0,
            "rails": rails or None,
            "period_high": round(max(bars.highs[lo : hi + 1]), 4),
            "period_low": round(min(bars.lows[lo : hi + 1]), 4),
            "last_close": round(last_close, 4),
            "period_change_pct": change_pct,
            "swing_highs": [round(pivot.price, 4) for pivot in highs[-6:]],
            "swing_lows": [round(pivot.price, 4) for pivot in lows[-6:]],
            "momentum": self._momentum(window),
        }
        return self._wrapped("analyse_chart", payload, symbol=view.symbol)

    def find_patterns(self, lookback_bars: int = 0) -> str:
        """Find candlestick and chart patterns, and mark every one on the chart.

        Two kinds come back together. Candlestick patterns are single bars or
        runs of two or three: engulfings, hammers, stars, harami, tweezers,
        marubozu, doji. Chart patterns are statements about the swing sequence:
        double tops and bottoms, head and shoulders, triangles and ranges.

        Marking is not optional, exactly as it is not optional for draw_levels,
        draw_trendline and draw_zone: a pattern named in a paragraph makes the
        operator hunt for the bar, and this panel is docked to the chart the bar
        is on. If they would rather the chart were clean, clear_drawings
        ``patterns`` takes the markers off again.

        Every hit is detected from real candles, so its bar and its price are
        facts. Say which pattern, on which bar, and what it implies; do not add
        one the result does not list.

        Args:
            lookback_bars: How many candles to search, 60 to 1500. Pass 0 for the
                default of 300. Candlestick patterns are reported from the most
                recent 30 bars of that window, because a hammer six months ago is
                history rather than a signal.

        Returns:
            JSON listing each candlestick pattern with its bar, its bias and the
            price it printed at, and each chart pattern with its anchors.
        """
        view = self._view
        if not view.is_open:
            return wrap_tool_result("find_patterns", _NO_CHART)

        window = self._window(lookback_bars)
        bars, lo, hi = window.bars, window.lo, window.hi
        highs, lows = geom.significant_pivots(bars, lo, hi)
        candles = geom.candlestick_patterns(bars, CANDLE_SCAN_BARS, lo, hi)
        shapes_found = geom.chart_patterns(bars, highs, lows, lo, hi)

        recent = candles[-MAX_MARKERS:]
        payload: dict[str, Any] = {
            **window.meta,
            "candlestick_patterns": [
                {
                    "name": hit["name"],
                    "bias": hit["bias"],
                    "at": ist_label(hit["time"]),
                    "price": hit["price"],
                    "bars": hit["bars"],
                }
                for hit in recent
            ],
            "candlestick_hits_found": len(candles),
            "chart_patterns": [
                {
                    "name": item["name"],
                    "bias": item["bias"],
                    "anchors": [
                        {"at": ist_label(point["time"]), "price": point["price"]}
                        for point in item["anchors"]
                    ],
                }
                for item in shapes_found
            ],
        }

        drawings: list[dict[str, Any]] = []
        for item in shapes_found:
            anchors = item["anchors"]
            tone = item["bias"] if item["bias"] in cc.TONES else "neutral"
            for index in range(len(anchors) - 1):
                drawings.append(
                    cc.trendline(
                        anchors[index],
                        anchors[index + 1],
                        extend_right=False,
                        label=item["name"] if index == 0 else "",
                        tone=tone,
                    )
                )
        for bar in _markers(recent):
            drawings.append(
                cc.marker(
                    {"time": bar["time"], "price": bar["price"]},
                    bar["text"],
                    tone=bar["tone"],
                )
            )

        payload["drawn"] = self._emit([cc.draw(cc.GROUP_PATTERNS, drawings)])
        if not payload["drawn"]:
            payload["note"] = _NO_SINK
        return self._wrapped("find_patterns", payload, symbol=view.symbol)

    def draw_levels(self, count: int = 4, lookback_bars: int = 0, note: str = "") -> str:
        """Draw the strongest horizontal support and resistance levels on the chart.

        Levels come from clustered swing points, ranked by how many times price
        actually turned there, and each is a price that printed. Support and
        resistance are decided against the chart's live last price, so the same
        level is named the way the operator reads it now.

        Args:
            count: How many levels to draw, 1 to 8. Defaults to 4.
            lookback_bars: How many candles to search, 60 to 1500. Pass 0 for the
                default of 300.
            note: An optional short caption drawn with the levels, in words. It
                carries no numbers: the prices on the labels come from the
                candles, not from you.

        Returns:
            One line naming every level drawn, its role and its touch count.
        """
        view = self._view
        if not view.is_open:
            return wrap_tool_result("draw_levels", _NO_CHART)

        wanted = max(1, min(int(count or 4), MAX_LEVELS))
        window = self._window(lookback_bars)
        reference = (
            view.last_price if view.last_price is not None else window.bars.closes[window.hi]
        )
        found = geom.support_resistance(window.bars, window.lo, window.hi, reference=reference)[
            :wanted
        ]

        if not found:
            return wrap_tool_result(
                "draw_levels",
                f"No price on {view.symbol} {view.interval} was turned at twice in the "
                f"{window.meta['bars_analysed']} bars searched, so there is no level worth "
                f"drawing. "
                "Say so, and offer a longer lookback rather than drawing something arbitrary.",
            )

        caption = self._note(note)
        shapes = [
            cc.level(
                item["price"],
                time=item["first_time"],
                label=self._caption(
                    f"{item['role']} {format_price(item['price'])}", caption, index
                ),
                tone="bearish" if item["role"] == "resistance" else "bullish",
            )
            for index, item in enumerate(found)
        ]

        if not self._emit([cc.draw(cc.GROUP_LEVELS, shapes)]):
            return wrap_tool_result("draw_levels", _NO_SINK)

        described = ", ".join(
            f"{format_price(item['price'])} ({item['role']}, {item['touches']} touches)"
            for item in found
        )
        return wrap_tool_result(
            "draw_levels",
            f"Drew {len(shapes)} levels on {view.symbol} {view.interval} in your 'levels' "
            f"group, from {window.meta['bars_analysed']} bars: {described}. The operator can see "
            "them, so say what they mean rather than listing them again.",
            symbol=view.symbol,
        )

    def draw_trendline(self, side: str = "auto", lookback_bars: int = 0, note: str = "") -> str:
        """Draw a trendline through real swing points, or both rails of a channel.

        The line runs through two swing points that actually printed and is
        chosen as the one price has respected: a resistance rail with nothing
        above it and a support rail with nothing below it, from its anchor
        forward, before touch count is even looked at. So it touches the bars it
        claims to touch and holds where it claims to hold, rather than being
        fitted to a cloud.

        Args:
            side: Which swings to fit. ``support`` uses the swing lows,
                ``resistance`` the swing highs, ``both`` draws a rail through
                each, and ``auto`` picks whichever side has the better fit.
            lookback_bars: How many candles to search, 60 to 1500. Pass 0 for the
                default of 300.
            note: An optional short caption drawn with the line, in words. It
                carries no numbers.

        Returns:
            One line naming the anchors each rail was fitted on, its touch count,
            how many bars have pierced it since, and its slope per bar.
        """
        view = self._view
        if not view.is_open:
            return wrap_tool_result("draw_trendline", _NO_CHART)

        wanted = self._choice("side", side or "auto", _TREND_SIDES)
        window = self._window(lookback_bars)
        highs, lows = geom.significant_pivots(window.bars, window.lo, window.hi)
        seconds = geom.bar_seconds(window.bars)

        fits = _rails(window.bars, highs, lows)

        if not fits:
            return wrap_tool_result(
                "draw_trendline",
                f"Fewer than two swing points on {view.symbol} {view.interval} in the "
                f"{window.meta['bars_analysed']} bars searched, so there is nothing to draw a "
                f"line "
                "through. Ask for a longer lookback rather than drawing a guess.",
            )

        if wanted == "both":
            chosen = list(fits)
        elif wanted == "auto":
            chosen = [max(fits, key=lambda name: (fits[name]["touches"], fits[name]["r2"]))]
        elif wanted in fits:
            chosen = [wanted]
        else:
            other = next(iter(fits))
            return wrap_tool_result(
                "draw_trendline",
                f"There are fewer than two swing {'lows' if wanted == 'support' else 'highs'} "
                f"on {view.symbol} {view.interval} in the {window.meta['bars_analysed']} bars "
                f"searched, so a {wanted} line cannot be fitted. A {other} line can; ask the "
                "operator whether they want that instead.",
            )

        caption = self._note(note)
        shapes: list[Any] = []
        described: list[str] = []
        for index, name in enumerate(chosen):
            fit = fits[name]
            per_bar = fit["slope"] * seconds
            tone = "bullish" if per_bar > 0 else "bearish" if per_bar < 0 else "neutral"
            shapes.append(
                cc.trendline(
                    fit["from"],
                    fit["to"],
                    extend_right=True,
                    label=self._caption(name, caption, index),
                    tone=tone,
                )
            )
            described.append(
                f"{name} from {format_price(fit['from'].price)} on "
                f"{ist_label(fit['from'].time)} to {format_price(fit['to'].price)} on "
                f"{ist_label(fit['to'].time)}, {fit['touches']} touches, r2 {fit['r2']}, "
                f"{fit['breaks']} bars pierced it since, {round(per_bar, 4)} per bar"
            )

        if not self._emit([cc.draw(cc.GROUP_TRENDLINE, shapes)]):
            return wrap_tool_result("draw_trendline", _NO_SINK)

        return wrap_tool_result(
            "draw_trendline",
            f"Drew {len(shapes)} rail(s) on {view.symbol} {view.interval} in your "
            f"'trendline' group, extended right: {'; '.join(described)}.",
            symbol=view.symbol,
        )

    def draw_zone(self, kind: str = "demand", lookback_bars: int = 0, note: str = "") -> str:
        """Shade a demand or supply zone, derived from the bars around a real swing.

        A demand zone is the base price left behind before an advance: the lowest
        low around the most recent significant swing low, up to the highest candle
        body there. A supply zone is the mirror. Both edges therefore printed, and
        neither is a number anybody chose.

        Args:
            kind: ``demand`` for the base under price, ``supply`` for the ceiling
                above it, ``both`` to shade one of each, or ``range`` for a
                consolidation, meaning the longest stretch where price held one
                narrow band. Reach for ``range`` whenever the operator says
                consolidation, sideways, base, box or accumulation: those are
                not swings and a demand zone is not what they are describing.
            lookback_bars: How many candles to search, 60 to 1500. Pass 0 for the
                default of 300.
            note: An optional short caption drawn with the band, in words. It
                carries no numbers.

        Returns:
            One line naming each band drawn and the swing it was derived from.
        """
        view = self._view
        if not view.is_open:
            return wrap_tool_result("draw_zone", _NO_CHART)

        wanted = self._choice("kind", kind or "demand", _ZONE_KINDS)
        window = self._window(lookback_bars)
        kinds = ("demand", "supply") if wanted == "both" else (wanted,)

        caption = self._note(note)
        shapes: list[Any] = []
        described: list[str] = []

        if wanted == "range":
            # A consolidation has no pivot to hang off, so it comes from its own
            # detector rather than from zone(), which derives a band from a
            # swing. Same rectangle on the chart, different question answered.
            band = geom.consolidation(window.bars, window.lo, window.hi)
            if band is not None:
                shapes.append(
                    cc.zone(
                        {"time": band["from_time"], "price": band["high"]},
                        {"time": band["to_time"], "price": band["low"]},
                        label=self._caption("range", caption, 0),
                        tone="neutral",
                    )
                )
                described.append(
                    f"consolidation between {format_price(band['low'])} and "
                    f"{format_price(band['high'])}, {band['bars']} bars wide at "
                    f"{band['width_pct']} percent, {band['touches']} touches of an edge, "
                    f"price finishing {band['drift_pct']} percent of the band from where it "
                    f"started, from {ist_label(band['from_time'])} to "
                    f"{ist_label(band['to_time'])}"
                )
            kinds = ()

        for index, name in enumerate(kinds):
            band = geom.zone(window.bars, name, window.lo, window.hi)
            if band is None:
                continue
            shapes.append(
                cc.zone(
                    {"time": band["from_time"], "price": band["high"]},
                    {"time": band["to_time"], "price": band["low"]},
                    label=self._caption(name, caption, index),
                    tone="bullish" if name == "demand" else "bearish",
                )
            )
            described.append(
                f"{name} between {format_price(band['low'])} and {format_price(band['high'])}, "
                f"off the swing at {format_price(band['pivot_price'])} on "
                f"{ist_label(band['pivot_time'])}, {band['bars_since']} bars ago"
            )

        if not shapes:
            return wrap_tool_result(
                "draw_zone",
                f"Nothing of that kind on {view.symbol} {view.interval} in the "
                f"{window.meta['bars_analysed']} bars searched: no significant swing for a "
                "demand or supply base, and no stretch that held one narrow band long "
                "enough to call a consolidation. Ask for a longer lookback rather than "
                "shading an arbitrary band.",
            )

        if not self._emit([cc.draw(cc.GROUP_ZONE, shapes)]):
            return wrap_tool_result("draw_zone", _NO_SINK)

        return wrap_tool_result(
            "draw_zone",
            f"Shaded {len(shapes)} zone(s) on {view.symbol} {view.interval} in your 'zone' "
            f"group: {'; '.join(described)}.",
            symbol=view.symbol,
        )

    def list_chart_indicators(self, query: str = "") -> str:
        """List the indicators this chart can DRAW.

        These are not the indicators that compute values. The chart draws with
        ``openalgo-charts``, a JavaScript library of 102 indicators, while
        ``compute_indicator`` and its siblings use the Rust-backed Python
        library of 127. Only 34 names exist in both, so AlphaTrend and HalfTrend
        can be drawn and never tabulated, and ``bbands`` and ``adxr`` can be
        tabulated and never drawn. Consult THIS list before saying an indicator
        is unavailable on the chart, because the other one will not have it.

        The operator may also have written their own indicators, which the chart
        loads at runtime from ``strategies/indicators/``. Those cannot appear
        here, so a name absent from this list is worth trying rather than
        refusing: the chart checks its own registry and ignores what it does not
        recognise.

        Args:
            query: Optional filter, matched against the id and the name. Leave
                it empty for the whole catalogue, which is long.

        Returns:
            Matching ids with their names, grouped by category.
        """
        rows = _chart_indicator_catalogue()
        if not rows:
            return wrap_tool_result(
                "list_chart_indicators",
                "The chart indicator catalogue could not be read on this install, so use "
                "add_chart_indicator with the name the operator gave and let the chart "
                "accept or ignore it.",
            )

        needle = str(query or "").strip().lower()
        if needle:
            rows = [row for row in rows if needle in row["id"] or needle in row["name"].lower()]
        if not rows:
            return wrap_tool_result(
                "list_chart_indicators",
                f"No chart indicator matches '{query}'. Try a shorter query, or list them all.",
            )

        by_category: dict[str, list[str]] = {}
        for row in rows:
            by_category.setdefault(row["category"], []).append(f"{row['id']} ({row['name']})")
        parts = [f"{name}: {', '.join(items)}" for name, items in sorted(by_category.items())]
        return wrap_tool_result(
            "list_chart_indicators",
            f"{len(rows)} chart indicator(s). " + " | ".join(parts),
        )

    def add_chart_indicator(self, name: str, settings: dict | None = None) -> str:
        """Add an indicator to the chart the operator is looking at.

        The id is passed through to the chart, which checks its own registry and
        ignores an id it does not know. That is deliberate: the operator's own
        indicator modules are loaded in the browser and no list on this side can
        see them, so refusing here on a name this process has not heard of would
        block a working indicator.

        Adding one already on the chart does nothing rather than drawing a
        second identical line.

        Args:
            name: The indicator id, as listed by ``list_chart_indicators``, for
                example ``alphatrend``, ``halftrend`` or ``supertrend``. For an
                indicator that is not on that list, and so is one of the
                operator's own modules, keep their own words and join them with
                hyphens: "my UT Bot" is ``ut-bot``, not ``utbot``. Running the
                words together invents an id nothing is registered under, and
                the chart drops it without a word.
            settings: Optional per-indicator inputs, such as a period. Leave it
                out to take the indicator's own defaults, which is almost always
                what the operator meant.

        Returns:
            One line naming what was added.
        """
        view = self._view
        if not view.is_open:
            return wrap_tool_result("add_chart_indicator", _NO_CHART)

        indicator_id = str(name or "").strip().lower()
        if not _INDICATOR_ID.match(indicator_id):
            self.invalid_argument(
                "name",
                f"'{name}' is not an indicator id.",
                "Pass an id from list_chart_indicators, such as alphatrend.",
            )

        payload = settings if isinstance(settings, dict) else {}
        command = {"op": "indicator", "action": "add", "id": indicator_id, "settings": payload}
        if not self._emit([command]):
            return wrap_tool_result("add_chart_indicator", _NO_SINK)

        known = any(row["id"] == indicator_id for row in _chart_indicator_catalogue())
        note = (
            ""
            if known
            else " It is not in the built-in catalogue, so it will draw only if the operator "
            "has an indicator module of that name; the chart ignores an id it does not know."
        )
        return wrap_tool_result(
            "add_chart_indicator",
            f"Added {indicator_id} to the {view.symbol} {view.interval} chart.{note}",
            symbol=view.symbol,
        )

    def remove_chart_indicator(self, name: str) -> str:
        """Remove an indicator from the chart.

        Args:
            name: The indicator id to remove.

        Returns:
            One line naming what was removed.
        """
        view = self._view
        if not view.is_open:
            return wrap_tool_result("remove_chart_indicator", _NO_CHART)

        indicator_id = str(name or "").strip().lower()
        if not _INDICATOR_ID.match(indicator_id):
            self.invalid_argument(
                "name",
                f"'{name}' is not an indicator id.",
                "Pass the id it was added under, such as alphatrend.",
            )

        if not self._emit([{"op": "indicator", "action": "remove", "id": indicator_id}]):
            return wrap_tool_result("remove_chart_indicator", _NO_SINK)
        return wrap_tool_result(
            "remove_chart_indicator",
            f"Removed {indicator_id} from the {view.symbol} {view.interval} chart.",
            symbol=view.symbol,
        )

    def clear_drawings(self, group: str = "") -> str:
        """Remove your own markup from the chart. Never touches the operator's drawings.

        Your drawings live in named groups and are id'd separately from anything
        the operator placed by hand, so this can only ever remove yours.

        Args:
            group: Which of your groups to remove: ``levels``, ``trendline``,
                ``zone`` or ``patterns``. Leave it empty to remove all of them.

        Returns:
            One line saying what was removed.
        """
        wanted = str(group or "").strip().lower()
        if wanted and wanted not in cc.GROUPS:
            self.invalid_argument(
                "group",
                f"{group!r} is not one of your drawing groups",
                f"Use one of: {', '.join(cc.GROUPS)}, or leave it empty to clear all of them.",
            )

        if not self._emit([cc.clear(wanted or None)]):
            return wrap_tool_result("clear_drawings", _NO_SINK)

        return wrap_tool_result(
            "clear_drawings",
            f"Cleared your '{wanted}' markup from the chart."
            if wanted
            else "Cleared all of your markup from the chart. The operator's own drawings "
            "are untouched.",
        )

    # -- candles -------------------------------------------------------------

    def _window(self, lookback_bars: Any) -> _Window:
        """Fetch the chart's own candles and clip them to the viewport.

        The instrument, the exchange and the interval come from the chart
        context, never from an argument. That is what stops a poisoned string
        reaching the history service, and it is what makes every tool here answer
        about the chart in front of the operator rather than about whatever the
        model named.

        The fetch is cached for the run against the clamped bar count, so an
        analysis followed by a draw is one broker call, and the geometry and the
        indicators read the identical bars.

        Args:
            lookback_bars: The model's requested bar count, before clamping.

        Returns:
            The window, in both shapes, with the viewport bounds and the result
            accounting.

        Raises:
            RetryAgentRun: When the chart context names an instrument or an
                interval the platform cannot serve, or when history came back
                empty, carrying a message about the chart rather than about an
                argument the model never passed.
        """
        view = self._view
        try:
            symbol, exchange, notices = normalise_pair(view.symbol, view.exchange)
            interval, correction = normalise_interval(
                view.interval, "api", self._intervals.accepted()
            )
        except RetryAgentRun as exc:
            # normalise_pair and normalise_interval phrase their refusals as
            # "the 'exchange' argument is invalid", which would send the model
            # looking for an argument it does not have. The values came off the
            # chart, so the refusal has to say so.
            raise RetryAgentRun(
                f"The chart context is unusable: {exc}. It reported symbol "
                f"{view.symbol!r} on exchange {view.exchange!r} at interval "
                f"{view.interval!r}. Tell the operator their chart is on an instrument or a "
                "resolution this broker does not serve history for; do not retry."
            ) from exc
        if correction:
            notices.append(correction)

        wanted = int(lookback_bars) if isinstance(lookback_bars, (int, float)) else 0
        wanted = DEFAULT_LOOKBACK if wanted <= 0 else max(MIN_LOOKBACK, min(wanted, MAX_LOOKBACK))

        cached = self._windows.get(wanted)
        if cached is None:
            cached = self._fetch(symbol, exchange, interval, wanted)
            self._windows[wanted] = cached

        lo, hi = cached.bars.window(view.visible_from, view.visible_to)
        meta: dict[str, Any] = {
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "timezone": "Asia/Kolkata",
            "bars_fetched": len(cached.bars),
            "bars_analysed": hi - lo + 1,
            "window_from": ist_label(cached.bars.times[lo]),
            "window_to": ist_label(cached.bars.times[hi]),
        }
        if notices:
            meta["notices"] = list(dict.fromkeys(notices))
        return _Window(bars=cached.bars, frame=cached.frame, lo=lo, hi=hi, meta=meta)

    def _fetch(self, symbol: str, exchange: str, interval: str, bars: int) -> _Window:
        """Read one candle window from the history service.

        Args:
            symbol: The instrument, already normalised.
            exchange: Its exchange, already normalised.
            interval: The candle size, already validated.
            bars: How many candles are wanted.

        Returns:
            The window in both shapes, newest bar last. The viewport bounds and
            the accounting are filled in by :meth:`_window`, which knows the
            viewport; this method only knows the fetch.

        Raises:
            RetryAgentRun: When the service fails or returns nothing usable.
        """
        start, end = lookback_range(interval, bars)
        response = self.service_call(
            get_history,
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_date=start,
            end_date=end,
        )

        rows = response.get("data") if isinstance(response, Mapping) else response
        records = (
            [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []
        )
        columns = candle_columns(records[0]) if records else {}
        frame = candle_frame(records, columns)
        if len(frame) > bars:
            frame = frame.iloc[-bars:]

        window = geom.Bars.from_frame(frame)
        if len(window) < 2:
            raise RetryAgentRun(
                f"No usable candles came back for {symbol} on {exchange} at {interval} "
                f"between {start} and {end}, so there is nothing to measure. Tell the "
                "operator the broker served no history for the chart's instrument at this "
                "resolution, and do not read levels off the chart instead."
            )
        return _Window(bars=window, frame=frame)

    def _momentum(self, window: _Window) -> dict[str, Any]:
        """Compute the momentum block of an analysis over the same candles.

        Args:
            window: The fetch the rest of the analysis is describing, so the
                readings cannot be about a different set of bars.

        Returns:
            The latest value and direction of RSI, MACD, ADX and ATR, plus a one
            line verdict. An indicator that could not be computed is named in
            ``unavailable`` rather than silently missing.
        """
        readings: dict[str, Any] = {}
        unavailable: dict[str, str] = {}

        for name in ("rsi", "macd", "adx", "atr"):
            try:
                result = compute(name, window.frame, {}, None, 3)
            except IndicatorError as exc:
                unavailable[name] = str(exc)
                continue
            summary = result.get("summary") or {}
            readings[name] = {
                output: {
                    "latest": (summary.get(output) or {}).get("latest"),
                    "direction": (summary.get(output) or {}).get("direction"),
                }
                for output in result.get("outputs") or ()
            }

        block: dict[str, Any] = {
            "bars_used": len(window.bars),
            "readings": readings,
            "verdict": _momentum_verdict(readings),
        }
        if unavailable:
            block["unavailable"] = unavailable
        return block

    # -- plumbing ------------------------------------------------------------

    def _emit(self, commands: list[dict[str, Any]]) -> bool:
        """Queue chart commands for delivery to the panel.

        Also brings the run's own view of which groups are on screen up to date.
        The context arrives once, with the operator's message, so a model that
        clears its markup and then calls read_chart in the same turn was being
        told the markup it had just removed was still there. Doing it here, in
        the one place a command leaves this toolkit, is what stops that being a
        duty each tool has to remember.

        Args:
            commands: Command dicts from ``chart_contract``.

        Returns:
            True when they were queued, False when the surface created no sink,
            which every caller reports to the model rather than claiming a
            drawing that reached nobody.
        """
        if not emit_frame(self._sink, tool="chart", frame=ChartCommand(commands=commands)):
            return False
        self._view = replace(
            self._view, agent_groups=_groups_after(self._view.agent_groups, commands)
        )
        return True

    def _choice(self, field: str, value: Any, allowed: tuple[str, ...]) -> str:
        """Validate one closed-vocabulary argument.

        The only shape of string argument these tools accept beside ``note``, and
        it is validated against a fixed tuple rather than sanitised, so a value
        outside the vocabulary is refused rather than quietly reinterpreted.

        Args:
            field: The argument name, exactly as the model sees it.
            value: The value the model supplied.
            allowed: The permitted values.

        Returns:
            The value in lower case.

        Raises:
            RetryAgentRun: When the value is not in ``allowed``.
        """
        cleaned = str(value or "").strip().lower()
        if cleaned not in allowed:
            self.invalid_argument(
                field,
                f"{value!r} is not one of the values this tool accepts",
                f"Use one of: {', '.join(allowed)}.",
            )
        return cleaned

    def _note(self, note: Any) -> str:
        """Reduce a model-supplied caption to something safe to put on the chart.

        Two controls, in this order, and the order matters.

        First ``chart_contract.safe_note`` removes every digit, because a caption
        reading "support 1450" is a price the model chose wearing the clothes of
        one the candles gave, and the operator cannot tell them apart on a
        canvas.

        Then the taint boundary: ``websearch.constrain_query`` keeps only the
        whitespace-delimited tokens that appear in the operator's own message for
        this turn. A caption is therefore provably made of the operator's own
        words, so text the model invented, or copied out of a poisoned tool
        result, cannot reach the canvas by construction rather than by pattern
        matching. It is the same primitive web search builds its outgoing query
        with, imported rather than reimplemented.

        Nothing surviving means no caption, which is the right answer: the
        computed label already says what the level is, and falling back to the
        operator's whole message would put a sentence on a chart.

        Args:
            note: Whatever the model passed.

        Returns:
            The caption to draw, possibly empty.
        """
        cleaned = cc.safe_note(note)
        if not cleaned:
            return ""
        constrained = constrain_query(cleaned, operator_message(self.context))
        if constrained.decision not in (DECISION_VERBATIM, DECISION_CONSTRAINED):
            return ""
        return constrained.text[: cc.MAX_NOTE_CHARS]

    @staticmethod
    def _caption(computed: str, note: str, index: int) -> str:
        """Join a computed label to the operator-facing note, once.

        Attached to the first shape of a group alone, because the same caption
        repeated down eight levels is clutter rather than context.

        Args:
            computed: The label the tool built from real numbers.
            note: The cleaned note from :meth:`_note`, possibly empty.
            index: Position of the shape within its group.

        Returns:
            The label to draw.
        """
        if note and index == 0:
            return f"{computed} - {note}"
        return computed

    def _summary(self) -> str:
        """Render the chart context as one sentence.

        Returns:
            A plain sentence naming the instrument, the timeframe and what is on
            the chart, for a model that wants the shape of it rather than the
            fields.
        """
        view = self._view
        parts = [f"{view.symbol} on {view.exchange}, {view.interval}."]
        if view.bars_loaded:
            parts.append(f"{view.bars_loaded} bars loaded, {view.visible_bars} visible.")
        if view.last_price is not None:
            parts.append(f"Last price {format_price(view.last_price)}.")
        if view.indicators:
            parts.append("Indicators: " + ", ".join(item["name"] for item in view.indicators) + ".")
        if view.drawings:
            parts.append(f"{len(view.drawings)} drawing(s) the operator placed by hand.")
        if view.agent_groups:
            parts.append("Your markup on screen: " + ", ".join(view.agent_groups) + ".")
        return " ".join(parts)

    def _wrapped(self, tool: str, payload: Any, **labels: Any) -> str:
        """Serialise a result and label it as data before it re-enters context.

        Args:
            tool: The tool's registered name.
            payload: The result payload.
            **labels: Attributes for the opening tag. Each is escaped.

        Returns:
            The ``<tool_result>`` block to return to the model.
        """
        return wrap_tool_result(tool, self.to_json(payload), **labels)


def _rails(
    bars: geom.Bars, highs: Sequence[geom.Pivot], lows: Sequence[geom.Pivot]
) -> dict[str, Any]:
    """Fit the resistance and support rails of one window.

    Both tools that draw a line fit it the same way, and this is the one place
    that says how. It exists because they did not: ``fit_line`` grew ``bars``
    and ``side``, the two arguments that turn a regression through a cloud of
    swings into a line price has actually respected, and both call sites were
    written without them. Measured on real daily windows the difference is not
    cosmetic: the resistance rail on RELIANCE was pierced by 16 of the 96 bars
    after its own anchor and the support rail on INFY by 66 of 100, against 0
    for both once containment decides. A line price has crossed 66 times is not
    a trendline, and the docstring of ``fit_line`` has always said so.

    Args:
        bars: The candle window the pivots came from, for counting breaks.
        highs: Swing highs, for the resistance rail.
        lows: Swing lows, for the support rail.

    Returns:
        The fits that could be made, keyed ``resistance`` and ``support``. A
        side with fewer than two usable swings is absent rather than None, so a
        caller can test the dict itself for having nothing to draw.
    """
    fits: dict[str, Any] = {}
    for side, pivots in (("resistance", highs), ("support", lows)):
        fit = geom.fit_line(pivots, bars=bars, side=side)
        if fit is not None:
            fits[side] = fit
    return fits


def _groups_after(groups: Sequence[str], commands: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """Work out which agent groups are on the chart once these commands land.

    Pure, and the mirror of what the terminal does with the same list: a draw
    with shapes puts its group on screen, a draw with none takes it off (which
    is how "nothing found" clears a group), a clear naming a group removes that
    one, and a clear naming none removes them all.

    It is the agent's own groups only. Nothing here can name, count or remove a
    drawing the operator placed by hand.

    Args:
        groups: The groups believed to be on screen before these commands.
        commands: The commands just handed to the panel.

    Returns:
        The groups on screen afterwards, in the order they first appeared.
    """
    on_screen = dict.fromkeys(groups)
    for command in commands:
        op = command.get("op")
        group = command.get("group")
        if op == "draw" and isinstance(group, str):
            if command.get("shapes"):
                on_screen[group] = None
            else:
                on_screen.pop(group, None)
        elif op == "clear":
            if group is None:
                on_screen.clear()
            elif isinstance(group, str):
                on_screen.pop(group, None)
    return tuple(on_screen)


def _markers(hits: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Collapse the candlestick hits on one bar into a single marker.

    Three patterns often print on the same candle: a spinning top is also a
    harami is also an inside bar. Three markers at one price is a smudge on the
    chart rather than three pieces of information, so they become one label
    naming all of them, seated at the extreme the strongest bias belongs at.

    Args:
        hits: The candlestick hits, oldest first.

    Returns:
        One entry per bar: ``time``, ``price``, ``text`` and ``tone``. The tone
        is the first directional bias on that bar, because a neutral pattern
        beside a bullish engulfing does not make the bar neutral.
    """
    grouped: dict[float, dict[str, Any]] = {}
    for hit in hits:
        entry = grouped.get(hit["time"])
        if entry is None:
            grouped[hit["time"]] = {
                "time": hit["time"],
                "price": hit["price"],
                "names": [hit["name"]],
                "tone": hit["bias"],
            }
            continue
        entry["names"].append(hit["name"])
        if entry["tone"] == "neutral" and hit["bias"] != "neutral":
            entry["tone"] = hit["bias"]
            entry["price"] = hit["price"]

    return [
        {
            "time": entry["time"],
            "price": entry["price"],
            "text": ", ".join(entry["names"]),
            "tone": entry["tone"],
        }
        for entry in grouped.values()
    ]


def _momentum_verdict(readings: Mapping[str, Any]) -> str:
    """Turn the momentum readings into one plain sentence.

    Args:
        readings: The per-indicator block :meth:`ChartToolkit._momentum` built.

    Returns:
        A semicolon-joined verdict, or a plain admission when nothing was
        conclusive.
    """
    parts: list[str] = []

    rsi = next(iter((readings.get("rsi") or {}).values()), {})
    value = rsi.get("latest")
    if isinstance(value, (int, float)):
        state = "overbought" if value >= 70 else "oversold" if value <= 30 else "neutral"
        parts.append(f"RSI {round(value, 2)} is {state}")

    macd = readings.get("macd") or {}
    line = next((v.get("latest") for k, v in macd.items() if "macd" in k.lower()), None)
    signal = next((v.get("latest") for k, v in macd.items() if "signal" in k.lower()), None)
    if isinstance(line, (int, float)) and isinstance(signal, (int, float)):
        parts.append("MACD is above its signal" if line > signal else "MACD is below its signal")

    adx = next(iter((readings.get("adx") or {}).values()), {})
    value = adx.get("latest")
    if isinstance(value, (int, float)):
        strength = "strong" if value >= 25 else "weak"
        parts.append(f"ADX {round(value, 2)} shows a {strength} trend")

    return "; ".join(parts) or "no reading was conclusive"
