"""Visualization tools: charts the platform builds, never charts the model types.

Four read-only tools. Each one calls a ``services/*`` function, turns what came
back into a renderer payload, and hands that payload to the client on a
:class:`~services.agent.frames.Viz` frame. Nothing here mutates anything, so no
tool requires confirmation and none writes an audit row.

Two rules shape every line of this file.

**The tool fetches the data, so the model never types a price.** A chart of
invented prices is worse than no chart, because it reads as authoritative. The
model asks for a chart of NIFTY's last thirty days; it does not supply the
thirty closes. That is the whole difference between this tier and the OpenUI
tier, where the model composes the numbers itself and the provenance rule lives
in the prompt instead of in the plumbing. OpenUI is therefore for general data
and never for prices.

**The series does not go through the model's context.** The tool answers with
one or two lines and puts the payload on the run's sink, which
``services/agent/viz_sink.py`` drains into a frame after the call returns.
Charting five hundred candles costs the conversation a sentence. A tool here
that returns its series to the model has missed the point.

Which renderer draws what
-------------------------

Three renderers, chosen by domain, and none of them new: all three engines
already ship in this app.

===============================  ==============  ==========================
Domain                           ``kind``        Engine
===============================  ==============  ==========================
Candles, OHLC, price+indicators  ``candles``     ``openalgo-charts`` 1.9.2,
                                                 the engine ``/trading`` uses
Option analytics                 ``plotly``      ``lib/Plot2D`` and
                                                 ``lib/Plot3D``, as used by
                                                 ``/strategybuilder`` and the
                                                 option analytics pages
Everything else                  (no viz frame)  OpenUI, through the model's
                                                 own ``render_ui`` tool
===============================  ==============  ==========================

``kind`` selects the renderer and an unknown kind renders nothing, so adding a
renderer is one new kind here and one new branch in the client.

What is covered, and what is not
--------------------------------

Covered, each from the service the matching ``/tools`` page already uses: the
price chart (``history_service``), open interest by strike
(``option_chain_service``), gamma exposure by strike (``gex_service``) and the
volatility surface across expiries (``vol_surface_service``).

The instrument card, a fifth rendering, lives in
:mod:`services.agent.tools.instrument` rather than here. It emits the same kind
of frame through the same sink, but its work is a fan-out across five services
with a resilience rule per section, which has nothing in common with assembling
a Plotly figure. The shared reading of a history frame is in
:mod:`services.agent.tools.market`, so both files reach candles the same way.

Deliberately left out for now, and why:

* **Payoff diagrams.** A payoff is composed from legs the operator chose, and
  there is no service that takes a leg list and returns a payoff curve;
  ``/strategybuilder`` builds it in the browser. Charting one would mean the
  model supplying the legs, which is the provenance rule's exact failure case
  unless the legs come from the position book. Worth doing, but as its own tool
  fed by ``positionbook_service``.
* **Max pain.** Computed in the frontend today, with no service behind it.
* **OI profile and multi-strike OI over time.** ``oi_profile_service`` and
  ``multi_strike_oi_service`` both exist and both fit ``plotly`` unchanged; they
  are omitted only to keep the first cut small. Each is one method plus one
  entry in the tool list.
* **IV smile.** ``iv_smile_service`` exists and is the same shape of addition.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from services import history_service
from services.agent.prompts import wrap_tool_result
from services.agent.tools.base import (
    OpenAlgoToolkit,
    as_number,
    format_number,
    invalid_argument,
    json_safe,
)
from services.agent.tools.market import (
    BrokerIntervals,
    candle_columns,
    chart_bars,
    normalise_interval,
    normalise_pair,
    normalise_range,
    normalise_source,
    summarise_candles,
)
from services.agent.tools.options import (
    UNDERLYING_EXCHANGES,
    normalise_exchange,
    normalise_expiry,
    normalise_int,
    normalise_symbol,
)
from services.agent.viz_sink import emit, no_sink_message, sink_of
from services.gex_service import get_gex_data
from services.intervals_service import get_intervals
from services.option_chain_service import get_option_chain
from services.vol_surface_service import get_vol_surface_data
from utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from services.agent.tools import ToolContext

logger = get_logger(__name__)

__all__ = [
    "CALL_COLOUR",
    "CHART_TYPES",
    "PUT_COLOUR",
    "VIZ_KINDS",
    "VizToolkit",
    "plotly_spec",
    "tool_answer",
]

#: The two renderer selectors this toolkit emits. Adding a renderer is one more
#: entry here and one more branch in the client.
VIZ_KINDS: tuple[str, ...] = ("candles", "plotly")

#: Price chart shapes the ``/trading`` terminal already draws, so the chat chart
#: and the terminal chart are the same picture. Anything else is refused rather
#: than sent for the client to ignore.
CHART_TYPES: tuple[str, ...] = (
    "candlestick",
    "hollow-candle",
    "bar",
    "high-low",
    "line",
    "step",
    "area",
    "baseline",
    "heikin-ashi",
)

DEFAULT_CHART_TYPE = "candlestick"

#: Most bars one chart carries. Well past what a reader can see on a screen, and
#: it costs the conversation nothing because the bars never enter the model's
#: context; the cap is here so a five-year minute range cannot build a frame
#: measured in megabytes.
MAX_CHART_BARS = 1500

#: Most indicators one price chart may carry. The chart computes them from the
#: bars it was given, so they cost no data and no request; the cap is about a
#: readable chart.
MAX_INDICATORS = 6

#: Most inputs one indicator may declare.
MAX_INDICATOR_INPUTS = 8

#: Strikes each side of ATM for an open interest chart when the model does not
#: say. Wide enough to show both OI walls on a NIFTY weekly.
DEFAULT_OI_STRIKE_COUNT = 15

#: Upper bound on that, matching the option chain tool's own limit.
MAX_OI_STRIKE_COUNT = 100

#: Strikes each side of ATM for a volatility surface. A surface is a grid, so
#: the cost is strikes times expiries and each cell is an implied volatility
#: inversion; this stays small on purpose.
DEFAULT_SURFACE_STRIKE_COUNT = 8
MAX_SURFACE_STRIKE_COUNT = 25

#: Most expiries one surface may span.
MAX_SURFACE_EXPIRIES = 8

#: An ``openalgo-charts`` indicator id: lower case, letters, digits and
#: underscores. Validated for shape only. The client owns the real list, and an
#: id it does not know is skipped there, so a newer indicator does not need a
#: change here to be usable.
_INDICATOR_ID = re.compile(r"\A[a-z][a-z0-9_]{1,23}\Z")

_INDICATOR_INPUT_KEY = re.compile(r"\A[A-Za-z][A-Za-z0-9_]{0,23}\Z")

#: ``ema:20`` and ``ema(20)``, the two shorthands a model reaches for.
_INDICATOR_SHORTHAND = re.compile(r"\A([A-Za-z][A-Za-z0-9_]{1,23})\s*[:(]?\s*(\d{1,4})?\)?\Z")

#: The input key an ``openalgo-charts`` moving average and most oscillators call
#: their period, so a bare ``ema:20`` lands on the right field.
_LENGTH_KEY = "length"

#: Call and put colours, the only colours this module chooses. Which series is a
#: call and which is a put is meaning, not decoration, so it is set here; every
#: other colour, the background and the fonts included, belongs to the client's
#: own theme and is deliberately absent from the layout. Public because the
#: derived analytics in :mod:`services.agent.tools.option_viz` draw the same two
#: legs and a red call in one chart beside a green one in the next is worse than
#: either choice on its own.
#:
#: **Calls are green and puts are red**, matching the `/tools` option analytics.
#: That agreement had to be made rather than found: OI Tracker, OI Range and the
#: GEX dashboard drew calls red while OI Profile drew them green, so the suite
#: contradicted itself and a chart in the conversation could only match half of
#: it. The pages were moved onto this convention at the same time as this line.
#: There is a real argument for the other direction, since heavy call writing is
#: bearish, but a convention that holds everywhere beats the better argument
#: applied inconsistently.
CALL_COLOUR = "#22c55e"
PUT_COLOUR = "#ef4444"
_POSITIVE_COLOUR = "#22c55e"
_NEGATIVE_COLOUR = "#ef4444"

#: Handed to Plotly as-is. No mode bar, because the chart sits inside a
#: conversation rather than on an analytics page.
_PLOTLY_CONFIG: Mapping[str, Any] = {"displayModeBar": False, "responsive": True}

_NO_SINK = no_sink_message("chart")


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def _indicator_inputs(raw: Any) -> dict[str, Any]:
    """Normalise one indicator's inputs to the flat mapping the chart takes.

    Args:
        raw: Whatever the model put under ``inputs``.

    Returns:
        Scalar inputs only, keyed by identifier. Anything nested or unnamed is
        dropped: an indicator input is a number, a flag or a source name, and a
        structure there is a model mistake rather than a feature.

    Raises:
        RetryAgentRun: If more inputs were given than one indicator may carry.
    """
    if not isinstance(raw, Mapping):
        return {}
    if len(raw) > MAX_INDICATOR_INPUTS:
        invalid_argument(
            "indicators",
            f"one indicator declares {len(raw)} inputs, more than the "
            f"{MAX_INDICATOR_INPUTS} allowed",
            "Name only the inputs you are changing; the chart supplies its own defaults "
            "for the rest.",
        )

    inputs: dict[str, Any] = {}
    for key, value in raw.items():
        name = str(key).strip()
        if not _INDICATOR_INPUT_KEY.match(name):
            continue
        if isinstance(value, bool) or isinstance(value, (int, float)):
            inputs[name] = value
        elif isinstance(value, str) and value.strip():
            inputs[name] = value.strip()[:32]
    return inputs


def _indicator(item: Any, position: int) -> dict[str, Any]:
    """Normalise one indicator request to ``{"id": ..., "inputs": {...}}``.

    Both spellings a model reaches for are accepted: the shorthand string
    ``"ema:20"`` and the object ``{"id": "ema", "inputs": {"length": 20}}``. A
    bare number in the shorthand lands on ``length``, which is what
    ``openalgo-charts`` calls the period on its moving averages and most of its
    oscillators.

    Args:
        item: One entry of the ``indicators`` argument.
        position: Its place in the list, named in the failure message.

    Returns:
        The normalised descriptor.

    Raises:
        RetryAgentRun: If the entry is not a usable indicator.
    """
    if isinstance(item, Mapping):
        lowered = {str(key).strip().lower(): value for key, value in item.items()}
        raw_id = lowered.get("id") or lowered.get("name") or lowered.get("indicator")
        identifier = str(raw_id or "").strip().lower()
        inputs = _indicator_inputs(lowered.get("inputs"))
        length = lowered.get(_LENGTH_KEY) or lowered.get("period")
        if _LENGTH_KEY not in inputs and isinstance(length, (int, float)):
            inputs[_LENGTH_KEY] = int(length)
    elif isinstance(item, str):
        match = _INDICATOR_SHORTHAND.match(item.strip())
        if not match:
            invalid_argument(
                "indicators",
                f"entry {position} is {item!r}, which is not an indicator",
                "Use 'ema:20', or an object such as "
                '{"id": "supertrend", "inputs": {"length": 10, "multiplier": 3}}.',
            )
        identifier = match.group(1).lower()
        inputs = {_LENGTH_KEY: int(match.group(2))} if match.group(2) else {}
    else:
        invalid_argument(
            "indicators",
            f"entry {position} is {type(item).__name__}, not an indicator name or object",
            'Pass strings such as "ema:20", or objects carrying an "id".',
        )

    if not _INDICATOR_ID.match(identifier):
        invalid_argument(
            "indicators",
            f"entry {position} names {identifier or 'nothing'}, which is not an indicator id",
            "Use a lower-case id such as 'ema', 'sma', 'rsi', 'macd', 'bollinger', 'vwap', "
            "'atr' or 'supertrend'.",
        )
    return {"id": identifier, "inputs": inputs}


def _indicators(value: Any) -> list[dict[str, Any]]:
    """Normalise the ``indicators`` argument of the price chart.

    Args:
        value: Whatever the model passed, including a JSON string of a list,
            which a model that has been told to send an array still sometimes
            sends as text.

    Returns:
        The normalised descriptors, at most :data:`MAX_INDICATORS` of them.

    Raises:
        RetryAgentRun: If the argument is not a usable list of indicators.
    """
    raw = value
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("["):
            try:
                raw = json.loads(text)
            except ValueError:
                invalid_argument(
                    "indicators",
                    "it is a string that is not valid JSON",
                    'Pass a list, for example ["ema:20", "rsi:14"].',
                )
        else:
            raw = [part for part in re.split(r"[,\n]", text) if part.strip()]
    if isinstance(raw, Mapping):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        invalid_argument(
            "indicators",
            f"it is {type(raw).__name__}, not a list",
            'Pass a list, for example ["ema:20", "ema:50"].',
        )
    if len(raw) > MAX_INDICATORS:
        invalid_argument(
            "indicators",
            f"it carries {len(raw)} entries, more than the {MAX_INDICATORS} one chart shows",
            "Ask for the few that answer the question; a chart carrying more is unreadable.",
        )
    return [_indicator(item, index + 1) for index, item in enumerate(raw)]


def _overlay_label(indicator: Mapping[str, Any]) -> str:
    """Name one indicator for the confirmation line.

    Args:
        indicator: A descriptor from :func:`_indicator`.

    Returns:
        ``ema(20)`` where a length was given, otherwise just the id, so two
        moving averages of different lengths do not read as the same overlay.
    """
    length = indicator.get("inputs", {}).get(_LENGTH_KEY)
    return f"{indicator['id']}({length})" if length else str(indicator["id"])


def _chart_type(value: Any) -> str:
    """Validate the price chart shape.

    Args:
        value: The value the model supplied.

    Returns:
        One of :data:`CHART_TYPES`.

    Raises:
        RetryAgentRun: For anything else.
    """
    text = str(value or DEFAULT_CHART_TYPE).strip().lower().replace("_", "-")
    if text in ("candle", "candles"):
        text = "candlestick"
    if text not in CHART_TYPES:
        invalid_argument(
            "chart_type",
            f"{text!r} is not a chart shape this terminal draws",
            f"Use one of: {', '.join(CHART_TYPES)}.",
        )
    return text


def _expiries(value: Any) -> list[str]:
    """Normalise the ``expiry_dates`` argument of the volatility surface.

    Args:
        value: A list of DDMMMYY expiries, a comma separated string of them, or
            a JSON string of the list.

    Returns:
        The expiries, de-duplicated, in the order given.

    Raises:
        RetryAgentRun: If the argument is empty or any entry is malformed.
    """
    raw = value
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("["):
            try:
                raw = json.loads(text)
            except ValueError:
                invalid_argument(
                    "expiry_dates",
                    "it is a string that is not valid JSON",
                    'Pass a list, for example ["28NOV25", "26DEC25"].',
                )
        else:
            raw = [part for part in re.split(r"[,\s]+", text) if part]
    if not isinstance(raw, (list, tuple)) or not raw:
        invalid_argument(
            "expiry_dates",
            "it is empty or is not a list",
            'Pass at least one expiry, for example ["28NOV25", "26DEC25"]. Look the listed '
            "expiries up first rather than guessing them.",
        )
    if len(raw) > MAX_SURFACE_EXPIRIES:
        invalid_argument(
            "expiry_dates",
            f"it carries {len(raw)} expiries, more than the {MAX_SURFACE_EXPIRIES} one "
            "surface spans",
            "Ask for the near expiries that answer the question.",
        )

    expiries: list[str] = []
    for item in raw:
        expiry = normalise_expiry(item, "", allow_embedded=False)
        if expiry not in expiries:
            expiries.append(expiry)
    return expiries


def _underlying_exchange(value: Any) -> str:
    """Validate an underlying's exchange for the option analytics tools.

    A named binding of :func:`services.agent.tools.options.normalise_exchange`
    to the underlying exchange list, so the three option tools here spell the
    check once rather than three times.

    Args:
        value: The exchange the model supplied.

    Returns:
        The trimmed, upper-cased exchange code.

    Raises:
        RetryAgentRun: If it is not an exchange an underlying can be named on.
    """
    return normalise_exchange(value, UNDERLYING_EXCHANGES)


def _vertical(
    x: Any, colour: str, label: str, row: int = 0
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the shape and annotation that mark one price on a strike axis.

    Args:
        x: Where to draw it, on the x axis's own scale.
        colour: Line colour.
        label: Text above the line.
        row: Which line above the plot the label sits on, counting from zero.
            ATM and the spot are usually within a strike or two of each other,
            and two labels on one line overlap into an unreadable smear. One
            label per row keeps both legible however close the two prices are.

    Returns:
        The Plotly shape and its annotation, ready to append to a layout.
    """
    shape = {
        "type": "line",
        "x0": x,
        "x1": x,
        "yref": "paper",
        "y0": 0,
        "y1": 1,
        "line": {"color": colour, "width": 1, "dash": "dot"},
    }
    annotation = {
        "x": x,
        "yref": "paper",
        "y": 1.02 + 0.06 * max(0, row),
        "text": label,
        "showarrow": False,
        "font": {"size": 11, "color": colour},
    }
    return shape, annotation


def _markers(atm: Any, spot: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build the ATM and spot markers for a strike-axis chart.

    One function rather than the same loop in every strike chart. Both the
    open-interest and the gamma charts want the identical pair of dotted lines,
    and two copies of that loop drift: the one that goes wrong is the one in the
    chart nobody is looking at.

    A value the service did not supply is skipped rather than drawn at zero,
    which would put a line at the left edge and read as a real strike.

    Args:
        atm: The at-the-money strike, or None.
        spot: The underlying's last traded price, or None.

    Returns:
        The layout's ``shapes`` and ``annotations``, in that order.
    """
    shapes: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    for value, colour, label in ((atm, "#94a3b8", "ATM"), (spot, "#0ea5e9", "Spot")):
        if as_number(value) is None:
            continue
        shape, annotation = _vertical(value, colour, label, row=len(annotations))
        shapes.append(shape)
        annotations.append(annotation)
    return shapes, annotations


def plotly_spec(
    *,
    data: list[dict[str, Any]],
    layout: dict[str, Any],
    engine: str = "2d",
) -> dict[str, Any]:
    """Assemble a Plotly figure spec for a ``plotly`` viz frame.

    The layout carries no colours of its own beyond the meaning-bearing ones on
    the traces, and no font or paper colour at all, so the client merges its own
    theme in and a chart looks like the page it sits on in both light and dark.

    Module level rather than a method, because the derived option analytics in
    :mod:`services.agent.tools.option_viz` build the same envelope. A second
    copy would drift on the margins, the config or the engine key, and the copy
    that goes wrong is the one in the chart nobody is looking at.

    Args:
        data: The traces.
        layout: Layout keys this chart needs.
        engine: ``2d`` for the ``Plot2D`` build, ``3d`` for ``Plot3D``. The two
            are separate Plotly bundles, so the spec has to say which.

    Returns:
        The spec for a ``plotly`` viz frame.
    """
    merged: dict[str, Any] = {
        "autosize": True,
        "margin": {"l": 56, "r": 24, "t": 32, "b": 48},
    }
    merged.update(layout)
    return {
        "engine": engine,
        "data": json_safe(data),
        "layout": json_safe(merged),
        "config": dict(_PLOTLY_CONFIG),
    }


def tool_answer(tool: str, message: str, notices: Sequence[str] = (), **labels: Any) -> str:
    """Wrap the short confirmation a rendering tool returns to the model.

    Labelled as data like every other tool result, so nothing a symbol name or a
    broker message carries can read as an instruction. Module level so every
    rendering tool in this package labels its answer the same way; a second copy
    is how one of them ends up returning bare text.

    Args:
        tool: The tool's registered name.
        message: The confirmation, one or two lines.
        notices: Corrections and caveats, appended as one trailing sentence.
        **labels: Attributes for the opening tag. A label whose value is None is
            dropped rather than rendered as the word ``None``.

    Returns:
        The ``<tool_result>`` block.
    """
    if notices:
        message = f"{message} Note: {' '.join(str(item) for item in notices)}"
    clean = {name: value for name, value in labels.items() if value is not None}
    return wrap_tool_result(tool, message, **clean)


def _peak(strikes: Sequence[Any], values: Sequence[Any]) -> Any:
    """The strike carrying the largest value, or None when nothing is positive.

    Args:
        strikes: The strike ladder.
        values: One value per strike.

    Returns:
        The strike at the maximum, or None.
    """
    best: Any = None
    best_value = 0.0
    for strike, value in zip(strikes, values, strict=False):
        number = as_number(value)
        if number is not None and number > best_value:
            best_value = number
            best = strike
    return best


# ---------------------------------------------------------------------------
# The toolkit
# ---------------------------------------------------------------------------


class VizToolkit(OpenAlgoToolkit):
    """Charts drawn from platform data, on both surfaces.

    Every tool is read-only, so none requires confirmation and none writes an
    audit row. Each one returns a short confirmation and leaves the payload on
    the run's sink for ``services/agent/viz_sink.py`` to turn into a frame.
    """

    def __init__(self, context: ToolContext) -> None:
        """Register the four visualization tools.

        The interval cache and the sink are bound before ``super().__init__``
        because agno introspects the bound methods the moment it receives them,
        and a method reading an attribute the instance does not have yet would
        fail during registration rather than during a call.

        Args:
            context: The run's tool context. Its ``extras`` carry the sink the
                surface created for this run.
        """
        self._sink = sink_of(context)
        self._intervals = BrokerIntervals(lambda: self.service_call(get_intervals))

        super().__init__(
            context,
            name="viz",
            tools=[
                self.plot_price_chart,
                self.plot_open_interest,
                self.plot_gamma_exposure,
                self.plot_volatility_surface,
            ],
        )

    # -- tools ---------------------------------------------------------------

    def plot_price_chart(
        self,
        symbol: str,
        exchange: str,
        interval: str,
        start_date: str,
        end_date: str,
        chart_type: str = DEFAULT_CHART_TYPE,
        indicators: list[str] | None = None,
        source: str = "api",
    ) -> str:
        """Draw a price chart of one instrument in the conversation.

        Use this whenever the operator asks to see, plot, chart or graph a
        price, a trend, a range or a pattern. The candles are fetched here, from
        the same service ``get_history`` uses, so the chart cannot show a bar
        the platform did not return, and none of the series reaches you: you get
        a one line summary and the operator gets the chart.

        Do not follow this with ``get_history`` for the same range unless you
        need to reason about individual bars. The summary this returns already
        carries the open, close, high, low and change.

        Args:
            symbol: OpenAlgo symbol, in capitals, exactly as the instrument is
                listed. For example ``INFY``, ``NIFTY`` or
                ``BANKNIFTY24APR24FUT``.
            exchange: Exchange code the symbol is listed on: NSE, BSE, NFO, BFO,
                CDS, BCD, MCX, NCDEX, NCO, CRYPTO, or an index code such as
                NSE_INDEX or BSE_INDEX for an index.
            interval: Candle size. Call ``get_intervals`` for the ones this
                broker accepts. Case matters: ``1m`` is one minute and ``M`` is
                one month.
            start_date: First day of the range, as ``YYYY-MM-DD``. Inclusive,
                and interpreted in IST.
            end_date: Last day of the range, as ``YYYY-MM-DD``. Inclusive, and
                interpreted in IST. It must not be before ``start_date``.
            chart_type: The shape to draw: ``candlestick`` (the default),
                ``hollow-candle``, ``bar``, ``high-low``, ``line``, ``step``,
                ``area``, ``baseline`` or ``heikin-ashi``. Use ``line`` or
                ``area`` for a long daily range where individual candles are too
                small to read.
            indicators: Overlays and oscillators the chart computes from those
                same bars, at most six. Either shorthand strings such as
                ``["ema:20", "ema:50", "rsi:14"]`` or objects such as
                ``[{"id": "supertrend", "inputs": {"length": 10, "multiplier":
                3}}]``. Ids are the chart's own: ``sma``, ``ema``, ``wma``,
                ``hma``, ``vwap``, ``bollinger``, ``supertrend``, ``rsi``,
                ``macd``, ``atr``, ``adx``, ``stochastic``, ``obv`` and the
                rest. Leave it out when the question is about price alone.
            source: Where the candles come from. ``api`` (the default) asks the
                broker. ``db`` reads the local Historify store, which only holds
                what the operator has already downloaded.

        Returns:
            One line confirming what was drawn, with the range summary. The
            candles travel to the operator's screen, not through this answer.
        """
        symbol, exchange, notices = normalise_pair(symbol, exchange)
        source = normalise_source(source)
        interval, interval_notice = normalise_interval(interval, source, self._intervals.accepted())
        if interval_notice:
            notices.append(interval_notice)
        start, end = normalise_range(start_date, end_date)
        shape = _chart_type(chart_type)
        overlays = _indicators(indicators)

        response = self.service_call(
            history_service.get_history,
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_date=start,
            end_date=end,
            source=source,
        )

        rows = response.get("data") if isinstance(response, Mapping) else response
        records = (
            [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []
        )
        columns = candle_columns(records[0]) if records else {}
        summary = summarise_candles(records, columns)
        bars = chart_bars(records, columns)

        total = len(bars)
        omitted = max(0, total - MAX_CHART_BARS)
        if omitted:
            bars = bars[-MAX_CHART_BARS:]
            notices.append(
                f"{omitted} of {total} bars were older than the {MAX_CHART_BARS} the chart "
                "carries, so the chart starts later than the range asked for. The summary "
                "covers the whole range."
            )

        if not bars:
            return self._answer(
                "plot_price_chart",
                f"No candles came back for {symbol} on {exchange} at {interval} between "
                f"{start} and {end}, so nothing was drawn. Check the dates against the "
                "trading calendar and confirm the interval is one this broker supports.",
                symbol=symbol,
                exchange=exchange,
            )

        spec: dict[str, Any] = {
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "chart_type": shape,
            "start_date": start,
            "end_date": end,
            "source": source,
            "timezone": "Asia/Kolkata",
            "bar_count": len(bars),
            "bars": bars,
            "indicators": overlays,
            "summary": json_safe(summary),
        }
        if notices:
            spec["notices"] = list(notices)

        title = f"{symbol} {exchange} {interval}"
        drawn = self._deliver(
            tool="plot_price_chart",
            kind="candles",
            spec=spec,
            title=title,
            source="history_service",
        )
        if not drawn:
            return self._answer("plot_price_chart", _NO_SINK, symbol=symbol, exchange=exchange)

        overlay_text = (
            " with " + ", ".join(_overlay_label(item) for item in overlays) if overlays else ""
        )
        message = (
            f"Drew a {shape} chart of {symbol} on {exchange} at {interval}{overlay_text}, "
            f"{len(bars)} bars from {start} to {end}. "
            f"Open {format_number(summary.get('first_open'))}, "
            f"close {format_number(summary.get('last_close'))}, "
            f"high {format_number(summary.get('highest_high'))}, "
            f"low {format_number(summary.get('lowest_low'))}, "
            f"change {format_number(summary.get('change_percent'))} percent. "
            "The operator can see it, so describe what it shows rather than listing bars."
        )
        return self._answer(
            "plot_price_chart", message, symbol=symbol, exchange=exchange, notices=notices
        )

    def plot_open_interest(
        self,
        underlying: str,
        exchange: str,
        expiry_date: str,
        strike_count: int = DEFAULT_OI_STRIKE_COUNT,
    ) -> str:
        """Draw call and put open interest by strike for one expiry.

        This is the OI wall picture: where the market has written the most
        contracts, which strikes are acting as resistance and support, and what
        the put-call ratio is. Reach for it whenever the operator asks about
        open interest, OI walls, max OI strikes, PCR or where the market expects
        an expiry to land.

        Args:
            underlying: Underlying symbol, not an option symbol. ``NIFTY``,
                ``BANKNIFTY``, ``SENSEX``, ``RELIANCE``, ``CRUDEOIL``.
            exchange: Exchange of the **underlying**, not of the options.
                ``NSE_INDEX`` for NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY;
                ``BSE_INDEX`` for SENSEX, BANKEX; ``NSE`` or ``BSE`` for a
                stock; ``MCX`` for a commodity. ``NFO`` and ``BFO`` are accepted
                and mapped back to the right underlying automatically.
            expiry_date: Expiry in DDMMMYY format, for example ``28NOV25``. Look
                the listed expiries up first rather than guessing a date.
            strike_count: Strikes each side of ATM, so the ladder is
                ``2 * strike_count + 1`` wide. Defaults to 15, which shows both
                walls on an index weekly. The maximum is 100.

        Returns:
            One line naming the OI peaks, the totals and the put-call ratio. The
            per-strike series travels to the operator's screen, not through this
            answer.
        """
        underlying = normalise_symbol(underlying, "underlying")
        exchange = _underlying_exchange(exchange)
        expiry = normalise_expiry(expiry_date, underlying, allow_embedded=True)
        count = normalise_int(strike_count, "strike_count", 1, MAX_OI_STRIKE_COUNT)

        payload = self.service_call(
            get_option_chain,
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry,
            strike_count=count,
            with_greeks=False,
        )

        chain = payload.get("chain") if isinstance(payload, Mapping) else None
        rows = [row for row in chain if isinstance(row, Mapping)] if isinstance(chain, list) else []
        if not rows:
            return self._answer(
                "plot_open_interest",
                f"The chain for {underlying} {expiry} came back with no strikes, so nothing "
                "was drawn. Confirm the expiry is listed.",
                underlying=underlying,
                expiry=expiry or None,
            )

        strikes = [row.get("strike") for row in rows]
        call_oi = [as_number((row.get("ce") or {}).get("oi")) for row in rows]
        put_oi = [as_number((row.get("pe") or {}).get("oi")) for row in rows]

        atm = payload.get("atm_strike")
        spot = payload.get("underlying_ltp")

        shapes, annotations = _markers(atm, spot)

        spec = self._plotly(
            data=[
                {
                    "type": "bar",
                    "name": "Call OI",
                    "x": strikes,
                    "y": call_oi,
                    "marker": {"color": CALL_COLOUR},
                },
                {
                    "type": "bar",
                    "name": "Put OI",
                    "x": strikes,
                    "y": put_oi,
                    "marker": {"color": PUT_COLOUR},
                },
            ],
            layout={
                "barmode": "group",
                "xaxis": {"title": {"text": "Strike"}},
                "yaxis": {"title": {"text": "Open interest"}},
                "shapes": shapes,
                "annotations": annotations,
                "legend": {"orientation": "h"},
            },
        )

        drawn = self._deliver(
            tool="plot_open_interest",
            kind="plotly",
            spec=spec,
            title=f"{underlying} {expiry} open interest by strike",
            source="option_chain_service",
        )
        if not drawn:
            return self._answer("plot_open_interest", _NO_SINK, underlying=underlying)

        call_total = sum(value for value in call_oi if value)
        put_total = sum(value for value in put_oi if value)
        ratio = round(put_total / call_total, 2) if call_total else None
        message = (
            f"Drew open interest by strike for {underlying} {expiry}: {len(rows)} strikes, "
            f"ATM {format_number(atm)}, spot {format_number(spot)}. "
            f"Call OI peaks at {format_number(_peak(strikes, call_oi))} "
            f"and put OI at {format_number(_peak(strikes, put_oi))}; "
            f"total call OI {format_number(call_total)}, "
            f"total put OI {format_number(put_total)}, PCR {format_number(ratio)}."
        )
        return self._answer(
            "plot_open_interest", message, underlying=underlying, expiry=expiry or None
        )

    def plot_gamma_exposure(self, underlying: str, exchange: str, expiry_date: str) -> str:
        """Draw net gamma exposure by strike for one expiry.

        GEX is gamma times open interest times lot size, called minus put, so a
        positive bar is a strike where dealers are long gamma and tend to damp
        movement, and a negative one is where they are short it and tend to
        amplify. Reach for it when the operator asks about gamma, GEX, dealer
        positioning, pinning, or where price is likely to be held or accelerated.

        This one is slow: it prices the Greeks of every listed strike around
        ATM, so it costs a full chain fetch plus an inversion per leg. Ask for it
        when it is what the question is about, not as background.

        Args:
            underlying: Underlying symbol, for example ``NIFTY`` or
                ``BANKNIFTY``.
            exchange: Exchange of the underlying. ``NSE_INDEX``, ``BSE_INDEX``,
                ``NSE``, ``BSE``, or the option exchange ``NFO`` or ``BFO``.
            expiry_date: Expiry in DDMMMYY format, for example ``28NOV25``.

        Returns:
            One line naming the totals, the spot and the strikes at the extremes
            of gamma. The per-strike series travels to the operator's screen.
        """
        underlying = normalise_symbol(underlying, "underlying")
        exchange = _underlying_exchange(exchange)
        expiry = normalise_expiry(expiry_date, underlying, allow_embedded=True)

        payload = self.service_call(
            get_gex_data,
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry,
        )

        chain = payload.get("chain") if isinstance(payload, Mapping) else None
        rows = [row for row in chain if isinstance(row, Mapping)] if isinstance(chain, list) else []
        if not rows:
            return self._answer(
                "plot_gamma_exposure",
                f"No gamma exposure came back for {underlying} {expiry}, so nothing was "
                "drawn. Confirm the expiry is listed and that the chain is quoting.",
                underlying=underlying,
                expiry=expiry or None,
            )

        strikes = [row.get("strike") for row in rows]
        net = [as_number(row.get("net_gex")) for row in rows]
        colours = [
            _NEGATIVE_COLOUR if (value is not None and value < 0) else _POSITIVE_COLOUR
            for value in net
        ]

        atm = payload.get("atm_strike")
        spot = payload.get("spot_price")

        shapes, annotations = _markers(atm, spot)

        spec = self._plotly(
            data=[
                {
                    "type": "bar",
                    "name": "Net GEX",
                    "x": strikes,
                    "y": net,
                    "marker": {"color": colours},
                }
            ],
            layout={
                "xaxis": {"title": {"text": "Strike"}},
                "yaxis": {"title": {"text": "Net gamma exposure"}, "zeroline": True},
                "shapes": shapes,
                "annotations": annotations,
                "showlegend": False,
            },
        )

        drawn = self._deliver(
            tool="plot_gamma_exposure",
            kind="plotly",
            spec=spec,
            title=f"{underlying} {expiry} net gamma exposure by strike",
            source="gex_service",
        )
        if not drawn:
            return self._answer("plot_gamma_exposure", _NO_SINK, underlying=underlying)

        positive = _peak(strikes, net)
        negative = _peak(strikes, [-value if value is not None else None for value in net])
        message = (
            f"Drew net gamma exposure for {underlying} {expiry}: {len(rows)} strikes, ATM "
            f"{format_number(atm)}, spot {format_number(spot)}. Total net GEX "
            f"{format_number(payload.get('total_net_gex'))}, PCR "
            f"{format_number(payload.get('pcr_oi'))}. "
            f"Longest gamma at strike {format_number(positive)}, "
            f"shortest at {format_number(negative)}."
        )
        return self._answer(
            "plot_gamma_exposure", message, underlying=underlying, expiry=expiry or None
        )

    def plot_volatility_surface(
        self,
        underlying: str,
        exchange: str,
        expiry_dates: list[str],
        strike_count: int = DEFAULT_SURFACE_STRIKE_COUNT,
    ) -> str:
        """Draw a 3D implied volatility surface across strikes and expiries.

        The surface shows the smile across strikes and the term structure across
        expiries at once, which is what makes a skew or an expiry trading rich
        visible rather than arithmetic. Reach for it when the operator asks about
        the volatility surface, the term structure, or how IV differs between
        expiries.

        Every cell is an implied volatility inversion, so the cost is strikes
        times expiries. Keep both small.

        Args:
            underlying: Underlying symbol, for example ``NIFTY``.
            exchange: Exchange of the underlying, such as ``NSE_INDEX``.
            expiry_dates: The expiries to span, in DDMMMYY format, nearest
                first, for example ``["28NOV25", "26DEC25", "29JAN26"]``. At
                most eight. Look the listed expiries up first.
            strike_count: Strikes each side of ATM, defaulting to 8. The maximum
                is 25, and a wide surface is slow as well as unreadable.

        Returns:
            One line naming the grid that was drawn. The surface itself travels
            to the operator's screen.
        """
        underlying = normalise_symbol(underlying, "underlying")
        exchange = _underlying_exchange(exchange)
        expiries = _expiries(expiry_dates)
        count = normalise_int(strike_count, "strike_count", 1, MAX_SURFACE_STRIKE_COUNT)

        response = self.service_call(
            get_vol_surface_data,
            underlying=underlying,
            exchange=exchange,
            expiry_dates=expiries,
            strike_count=count,
        )

        payload = response.get("data") if isinstance(response, Mapping) else None
        if not isinstance(payload, Mapping):
            payload = response if isinstance(response, Mapping) else {}

        strikes = payload.get("strikes")
        surface = payload.get("surface")
        expiry_rows = payload.get("expiries")
        if not isinstance(strikes, list) or not isinstance(surface, list) or not surface:
            return self._answer(
                "plot_volatility_surface",
                f"No volatility surface came back for {underlying} across "
                f"{', '.join(expiries)}, so nothing was drawn. Confirm the expiries are "
                "listed and that the chain is quoting.",
                underlying=underlying,
            )

        rows = expiry_rows if isinstance(expiry_rows, list) else []
        days = [
            as_number(row.get("dte")) if isinstance(row, Mapping) else None for row in rows
        ] or list(range(len(surface)))
        labels = [str(row.get("date")) if isinstance(row, Mapping) else "" for row in rows] or list(
            expiries
        )

        spec = self._plotly(
            engine="3d",
            data=[
                {
                    "type": "surface",
                    "name": "Implied volatility",
                    "x": strikes,
                    "y": days,
                    "z": surface,
                    "connectgaps": False,
                    "colorbar": {"title": {"text": "IV %"}},
                }
            ],
            layout={
                "scene": {
                    "xaxis": {"title": {"text": "Strike"}},
                    "yaxis": {"title": {"text": "Days to expiry"}},
                    "zaxis": {"title": {"text": "Implied volatility %"}},
                },
                "showlegend": False,
            },
        )
        spec["expiry_labels"] = labels

        drawn = self._deliver(
            tool="plot_volatility_surface",
            kind="plotly",
            spec=spec,
            title=f"{underlying} implied volatility surface",
            source="vol_surface_service",
        )
        if not drawn:
            return self._answer("plot_volatility_surface", _NO_SINK, underlying=underlying)

        message = (
            f"Drew an implied volatility surface for {underlying}: {len(strikes)} strikes "
            f"across {len(surface)} expiries ({', '.join(labels)}), ATM "
            f"{format_number(payload.get('atm_strike'))}, spot "
            f"{format_number(payload.get('underlying_ltp'))}."
        )
        return self._answer("plot_volatility_surface", message, underlying=underlying)

    # -- delivery ------------------------------------------------------------

    #: The figure envelope, shared with the derived option analytics. See
    #: :func:`plotly_spec`.
    _plotly = staticmethod(plotly_spec)

    def _deliver(
        self,
        *,
        tool: str,
        kind: str,
        spec: dict[str, Any],
        title: str,
        source: str,
    ) -> bool:
        """Put one chart on the run's sink.

        Args:
            tool: The tool drawing it.
            kind: Which renderer draws it.
            spec: The renderer payload.
            title: Heading shown above the chart.
            source: The service the data came from.

        Returns:
            True when it was queued for delivery.
        """
        return emit(
            self._sink,
            tool=tool,
            kind=kind,
            spec=json_safe(spec),
            title=title,
            source=source,
        )

    def _answer(self, tool: str, message: str, **labels: Any) -> str:
        """Wrap the short confirmation the model receives.

        A thin binding of :func:`tool_answer` that keeps ``notices`` spelled as
        a keyword at the call sites in this file.

        Args:
            tool: The tool's registered name.
            message: The confirmation, one or two lines.
            **labels: Attributes for the opening tag, plus an optional
                ``notices`` sequence.

        Returns:
            The ``<tool_result>`` block.
        """
        notices = labels.pop("notices", None) or ()
        return tool_answer(tool, message, notices, **labels)
