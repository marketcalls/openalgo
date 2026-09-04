"""Indicator tools: 127 indicators behind five tool slots.

One tool per indicator would spend 127 schema slots, cost that schema on every
turn whether or not the operator asks about an indicator, and swamp the model's
selection. Instead the model picks an indicator by **name**, discovered through
``list_indicators`` and pinned down by ``describe_indicator``, and one
dispatcher does the rest.

One tier, on purpose
--------------------

Values come from the Rust-backed ``openalgo.ta`` library, over candles this
process fetched from ``services.history_service``. Never from the chart canvas,
and never from the model. An indicator computed in the browser is invisible to
the model, so it could never answer "in table format", "is RSI oversold" or
"compare these two"; and a number the model supplies is not market data at all.
The chart's own overlays stay where they are, for drawing.

No dates, ever
--------------

The failure these tools exist to fix: asked for "reliance hourly data with
supertrend 3,10 and macd in table format", the agent asked which dates to use,
then answered with twelve hourly candles and both indicator columns blank. So
none of these tools takes a date. They take a **lookback in bars**, and pad the
fetch by the indicator's measured warm-up, because ``beta`` needs 253 bars
before its first finite value and ``lrslope`` 101. Ask for the last ten values
of ``beta`` over 60 bars and you get ten nulls; that is exactly what
``required_bars`` prevents.

One fetch per instrument per run
--------------------------------

``services.history_service`` serialises broker history calls behind a
process-wide 350ms gate, so five indicators on one symbol must not be five
fetches. ``compute_indicators_batch`` sizes one window from the longest warm-up
in the batch and computes every indicator over it, and a per-run frame cache
means a follow-up ``compute_indicator`` on the same instrument reuses it.

The cache is a plain dict on the toolkit instance, which exists for exactly one
run. ``services.indicator_service``'s TTL history cache is deliberately not used
here: its lock, its single-flight ``Event`` and its 60 second wait are all built
from ``threading`` primitives created after eventlet monkey-patches the stdlib,
so they are green, and this toolkit runs on the agent's real OS thread. A real
thread waiting on a green ``Event`` is the ``greenlet.error: Cannot switch to a
different thread`` failure CLAUDE.md documents, and it blocks that thread
forever. See "Nothing may block or be blocked across the eventlet boundary".

The token rule
--------------

Indicator values are the one thing that has to reach the model: a table the
operator asked for cannot be written out of a chart frame. So the values are
returned, bounded by ``last_n`` and by the character budget, and the result says
how many rows it carries and how many bars it read to produce them. Everything
else stays a summary.

``scan_symbols`` never calls ``eval``
-------------------------------------

Its parser accepts a comparison against a number, or a cross between two named
outputs, and nothing else. Anything else is refused with the valid output names.
A scanner that evaluated model-supplied text would be arbitrary code execution
inside a live trading account, and the model is untrusted input.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import pandas as pd
from agno.exceptions import RetryAgentRun

from services import intervals_service
from services.agent.indicators.compute import (
    IndicatorError,
    compute,
    required_bars,
    search_specs,
    spec_to_dict,
)
from services.agent.indicators.registry import CATEGORIES, CATEGORY_COUNTS, REGISTRY, get_spec
from services.agent.prompts import wrap_tool_result
from services.agent.tools.base import OpenAlgoToolkit
from services.agent.tools.market import (
    BrokerIntervals,
    candle_columns,
    candle_frame,
    fit_to_budget,
    lookback_range,
    normalise_interval,
    normalise_pair,
    normalise_source,
)
from services.history_service import get_history
from utils.logging import get_logger

logger = get_logger(__name__)

#: Candle interval used when the operator did not name one. Daily is what an
#: unqualified indicator question almost always means, it is the one resolution
#: every broker serves, and it is the cheapest window to fetch. The result says
#: which interval was used, so the operator can correct it in one word rather
#: than being asked first.
DEFAULT_INTERVAL = "D"

#: Most indicators one batch call may carry. Past this the result stops fitting
#: the character budget and the model would be reading a wall of numbers.
MAX_BATCH_INDICATORS = 8

#: Most instruments one scan may cover. Each is a separate broker history call
#: behind a 350ms gate, so fifteen is already five seconds of wall clock.
MAX_SCAN_SYMBOLS = 15

#: Most candles one call may compute over, when the model names the lookback
#: itself rather than letting the warm-up size it. Nothing else bounds it: the
#: date range this becomes is capped at eleven calendar years, which at a one
#: minute interval is over a million bars, and the run's frame cache would then
#: hold up to 24 of them. 5000 bars is far past the deepest common window
#: (SMA-200, beta's 253) and caps one frame at about 200 kB.
MAX_LOOKBACK_BARS = 5000

#: Most values one output may return. Bounding this is the honest answer to the
#: token rule: the operator asked for a table, so the rows travel, but a
#: thousand-row table costs more context than the answer is worth.
MAX_LAST_N = 120

#: Above this many matches ``list_indicators`` returns names grouped by
#: category instead of a description each, because the full catalogue with
#: descriptions does not fit the tool's character budget.
LIST_DETAIL_LIMIT = 45

#: Most cached candle frames one run keeps. A scan of fifteen symbols is the
#: worst case and each frame is a few hundred rows; the cap exists so a long
#: conversation cannot grow one without limit.
_MAX_CACHED_FRAMES = 24

#: A comparison of one named output against a literal number.
_CONDITION_RE = re.compile(
    r"^\s*(?P<left>[a-zA-Z_][a-zA-Z0-9_]*)\s*(?P<op><=|>=|<|>|==)\s*"
    r"(?P<right>-?\d+(\.\d+)?)\s*$"
)

#: A cross between two named outputs.
_CROSS_RE = re.compile(
    r"^\s*(?P<fn>crossover|crossunder|cross)\s*\(\s*(?P<a>[a-zA-Z_][a-zA-Z0-9_]*)\s*,\s*"
    r"(?P<b>[a-zA-Z_][a-zA-Z0-9_]*)\s*\)\s*$"
)

_CONDITION_HELP = (
    'Use a comparison against a number, such as "rsi < 30" or "adx > 25", or a cross '
    "between two of the indicator's own outputs, such as "
    '"crossover(macd_line, signal_line)". Nothing else is accepted: this is a fixed '
    "parser, not an expression evaluator."
)


# ---------------------------------------------------------------------------
# The restricted condition parser
# ---------------------------------------------------------------------------


def parse_condition(condition: str) -> dict[str, Any] | None:
    """Parse the two supported condition forms.

    Deliberately a pair of regular expressions and nothing more. There is no
    ``eval``, no ``compile``, no attribute access and no operator table the
    model can extend. A condition that does not match one of these two shapes
    is refused, which is the only safe answer when the text was written by an
    untrusted party into a process that can reach a live trading account.

    Args:
        condition: The expression the model supplied.

    Returns:
        A parsed form, or None when the text matches neither shape.
    """
    text = (condition or "").strip()

    match = _CONDITION_RE.match(text)
    if match:
        return {
            "kind": "compare",
            "left": match.group("left"),
            "op": match.group("op"),
            "right": float(match.group("right")),
        }

    match = _CROSS_RE.match(text)
    if match:
        return {
            "kind": "cross",
            "fn": match.group("fn"),
            "a": match.group("a"),
            "b": match.group("b"),
        }
    return None


def _pick(result: Mapping[str, Any], label: str) -> list[Any] | None:
    """Resolve an output name in a computed result.

    Args:
        result: One :func:`services.agent.indicators.compute.compute` result.
        label: The output name the condition referred to.

    Returns:
        That output's values, or None when the indicator has no such output.
        A single-output indicator also answers to its own name, so "rsi < 30"
        works without the caller knowing the output is also called ``rsi``.
    """
    values = result.get("values") or {}
    if label in values:
        return values[label]
    if label == result.get("indicator") and len(values) == 1:
        return next(iter(values.values()))
    return None


def _latest_finite(values: list[Any]) -> float | None:
    """Return the most recent finite value of an output.

    Args:
        values: The output's returned tail.

    Returns:
        The last value that is a real number, or None when every one is null,
        which is what a warm-up that has not completed looks like.
    """
    for value in reversed(values):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def evaluate_condition(
    parsed: Mapping[str, Any], result: Mapping[str, Any]
) -> tuple[bool, dict[str, Any]]:
    """Decide whether one computed result meets a parsed condition.

    Args:
        parsed: The output of :func:`parse_condition`.
        result: One computed indicator result.

    Returns:
        Whether the condition held, and the values that decided it, so a scan
        reports the number rather than only a verdict.
    """
    if parsed["kind"] == "compare":
        series = _pick(result, parsed["left"])
        if series is None:
            return False, {
                "error": f"no output named {parsed['left']!r}",
                "outputs": result.get("outputs"),
            }
        latest = _latest_finite(series)
        if latest is None:
            return False, {"error": "no finite value yet; the warm-up has not completed"}

        right = parsed["right"]
        hit = {
            "<": latest < right,
            "<=": latest <= right,
            ">": latest > right,
            ">=": latest >= right,
            "==": latest == right,
        }[parsed["op"]]
        return hit, {parsed["left"]: latest, "condition_met": hit}

    first = _pick(result, parsed["a"])
    second = _pick(result, parsed["b"])
    if first is None or second is None:
        return False, {
            "error": f"needs outputs {parsed['a']} and {parsed['b']}",
            "outputs": result.get("outputs"),
        }

    pairs = [
        (a, b)
        for a, b in zip(first, second, strict=False)
        if isinstance(a, (int, float))
        and isinstance(b, (int, float))
        and not isinstance(a, bool)
        and not isinstance(b, bool)
    ]
    if len(pairs) < 2:
        return False, {"error": "not enough finite values to detect a cross"}

    (prev_a, prev_b), (last_a, last_b) = pairs[-2], pairs[-1]
    up = prev_a <= prev_b and last_a > last_b
    down = prev_a >= prev_b and last_a < last_b
    hit = {"crossover": up, "crossunder": down, "cross": up or down}[parsed["fn"]]
    return hit, {parsed["a"]: last_a, parsed["b"]: last_b, "condition_met": hit}


# ---------------------------------------------------------------------------
# The toolkit
# ---------------------------------------------------------------------------


class IndicatorsToolkit(OpenAlgoToolkit):
    """Technical indicators computed over real candles.

    Every tool is read-only, so none requires confirmation and none writes an
    audit row. They are offered on both surfaces and to a session that has not
    enabled trading, because computing an RSI changes nothing.
    """

    def __init__(self, context: Any) -> None:
        """Register the five indicator tools.

        The interval cache and the frame cache are assigned before
        ``super().__init__`` because agno introspects the bound methods the
        moment it receives them, and a method reading an attribute the instance
        does not have yet would fail during registration rather than during a
        call.

        Args:
            context: The run's :class:`services.agent.tools.ToolContext`.
        """
        self._intervals = BrokerIntervals(
            lambda: self.service_call(intervals_service.get_intervals)
        )
        #: Candle frames already fetched during this run, keyed by instrument,
        #: interval and source. Lives exactly as long as the run.
        self._frames: dict[tuple[str, str, str, str], tuple[int, pd.DataFrame]] = {}

        super().__init__(
            context,
            name="indicators",
            tools=[
                self.list_indicators,
                self.describe_indicator,
                self.compute_indicator,
                self.compute_indicators_batch,
                self.scan_symbols,
            ],
        )

    # -- tools ---------------------------------------------------------------

    def list_indicators(self, query: str = "", category: str = "") -> str:
        """List the technical indicators that can be computed, by keyword or category.

        There are 127. Confirm a name here before computing it rather than
        guessing from memory: several are named differently from the textbook
        (the Relative Vigor Index is ``rvi``, the Ultimate Oscillator is
        ``ultimate_oscillator``), and a guessed name costs a whole round trip.

        Args:
            query: Keyword matched against the name, the category, the
                description and the caveats, so an intent works as well as a
                name: "bollinger", "trend strength", "money flow", "volatility".
                Leave it out to see the whole catalogue grouped by category.
            category: Exact category filter. One of trend, momentum,
                volatility, volume, oscillators, statistical, hybrid,
                talib_extra, utility.

        Returns:
            JSON listing the matching indicators with a one-line description
            each, or, when the match is too broad to describe in full, their
            names grouped by category.
        """
        wanted = (category or "").strip().lower()
        if wanted and wanted not in CATEGORIES:
            self.invalid_argument(
                "category",
                f"{wanted!r} is not one of the catalogue's categories",
                f"Use one of: {', '.join(CATEGORIES)}.",
            )

        specs = search_specs(query=query, category=wanted)
        if not specs:
            self.invalid_argument(
                "query",
                f"nothing in the catalogue matches {query!r}",
                "Try a broader keyword, or call list_indicators with no arguments to see "
                "every category.",
            )

        if len(specs) > LIST_DETAIL_LIMIT:
            grouped: dict[str, list[str]] = {}
            for spec in specs:
                grouped.setdefault(spec.category, []).append(spec.name)
            payload: dict[str, Any] = {
                "total": len(specs),
                "detail_omitted": True,
                "by_category": grouped,
                "category_counts": CATEGORY_COUNTS,
                "note": (
                    "Names only, because the whole catalogue with a description each does "
                    "not fit one result. Pass a query such as 'bollinger' or a category to "
                    "get descriptions, or call describe_indicator for one name."
                ),
            }
            return self._wrapped("list_indicators", payload)

        payload = {
            "total": len(specs),
            "categories": list(CATEGORIES),
            "indicators": [spec_to_dict(spec) for spec in specs],
        }
        return self._wrapped("list_indicators", payload)

    def describe_indicator(self, name: str) -> str:
        """Show the exact call signature of one indicator before computing it.

        Use this when you need an output's name for a scan condition, when you
        want to override a parameter and do not know what it is called, or when
        an indicator returned something you did not expect. It reports which
        price series the indicator needs, every parameter with its type and the
        library's own default, the output names in return order, and how many
        bars of warm-up it needs before its first real value.

        Args:
            name: Indicator method name, for example ``macd``, ``supertrend``
                or ``adx``. Case does not matter.

        Returns:
            JSON with the indicator's inputs, parameters, outputs, warm-up and
            any caveat that applies to it.
        """
        cleaned = (name or "").strip().lower()
        spec = get_spec(cleaned)
        if spec is None:
            self.invalid_argument("name", *self._unknown_indicator(name))
        return self._wrapped("describe_indicator", spec_to_dict(spec, verbose=True), name=cleaned)

    def compute_indicator(
        self,
        symbol: str,
        exchange: str,
        indicator: str,
        interval: str = DEFAULT_INTERVAL,
        params: dict | None = None,
        last_n: int = 10,
        lookback_bars: int = 0,
        compare_symbol: str = "",
        compare_exchange: str = "",
        source: str = "api",
    ) -> str:
        """Compute one technical indicator over real candles.

        Fetches the candles itself, cleans them, computes the indicator over the
        whole series and returns the most recent values with a summary. **Do not
        pass dates**: the range is derived from the lookback and padded
        automatically by the indicator's warm-up, so ``beta`` fetches the 253
        bars it needs even when you asked for ten values.

        For more than one indicator on the same instrument use
        ``compute_indicators_batch``: it shares a single candle fetch, and the
        broker's history calls are rate limited.

        Args:
            symbol: OpenAlgo symbol, in capitals, exactly as the instrument is
                listed. For example ``RELIANCE``, ``NIFTY`` or
                ``BANKNIFTY24APR24FUT``.
            exchange: Exchange code the symbol is listed on: NSE, BSE, NFO, BFO,
                CDS, BCD, MCX, NCDEX, NCO, CRYPTO, or an index code such as
                NSE_INDEX for an index.
            indicator: Indicator name from ``list_indicators``, for example
                ``rsi``, ``supertrend`` or ``macd``.
            interval: Candle size. Defaults to ``D`` (daily), which is what an
                unqualified question means. Use ``1h`` for hourly, ``5m`` for
                five minute, and call ``get_intervals`` when unsure. Case
                matters: ``1m`` is one minute and ``M`` is one month.
            params: Indicator parameters, for example ``{"period": 21}`` or
                ``{"period": 10, "multiplier": 3}``. Call
                ``describe_indicator`` for the names and defaults. Leave it out
                to use the library's own defaults.
            last_n: How many recent values to return per output, at most 120.
                Defaults to 10. Ask for what the answer needs: every value costs
                context.
            lookback_bars: How many candles to compute over. Leave it 0 to size
                it automatically from the indicator's warm-up, which is almost
                always right. Raise it only when you want a longer history than
                the warm-up requires.
            compare_symbol: The second instrument, needed only by ``beta`` and
                ``correlation``, which compare two price series. For example
                ``NIFTY``.
            compare_exchange: Exchange of the comparison instrument, for example
                ``NSE_INDEX``. Defaults to the same exchange as ``symbol``.
            source: Where the candles come from. ``api`` (the default) asks the
                broker. ``db`` reads the local Historify store, which only holds
                what the operator has already downloaded.

        Returns:
            JSON with the recent values per output, the timestamps they belong
            to, the OHLC candles for those same bars, and the latest, minimum,
            maximum and direction of each output computed over the whole series.
        """
        name = (indicator or "").strip().lower()
        spec = get_spec(name)
        if spec is None:
            self.invalid_argument("indicator", *self._unknown_indicator(indicator))

        symbol, exchange, notices = normalise_pair(symbol, exchange)
        source = normalise_source(source)
        interval, interval_notice = normalise_interval(interval, source, self._intervals.accepted())
        if interval_notice:
            notices.append(interval_notice)

        tail = self._tail(last_n, 10)
        arguments = params if isinstance(params, Mapping) else {}
        bars = self._lookback(lookback_bars) or required_bars(spec, arguments, tail)

        frame, fetched = self._frame(symbol, exchange, interval, source, bars)

        second: pd.Series | None = None
        if spec.needs_second_series:
            if not str(compare_symbol or "").strip():
                self.invalid_argument(
                    "compare_symbol",
                    f"it is empty, and {name} compares two instruments",
                    "Pass the benchmark as well, for example compare_symbol='NIFTY', "
                    "compare_exchange='NSE_INDEX'.",
                )
            other_symbol, other_exchange, other_notices = normalise_pair(
                compare_symbol, compare_exchange or exchange
            )
            notices.extend(other_notices)
            other_frame, other_fetched = self._frame(
                other_symbol, other_exchange, interval, source, bars
            )
            fetched += other_fetched
            if "close" not in other_frame.columns or other_frame.empty:
                self.invalid_argument(
                    "compare_symbol",
                    f"no candles came back for {other_symbol} on {other_exchange}",
                    "Check the symbol and exchange, and that it traded over this range.",
                )
            second = other_frame["close"]

        try:
            result = compute(name, frame, arguments, second_series=second, last_n=tail)
        except IndicatorError as exc:
            raise RetryAgentRun(str(exc)) from None

        def build(limit: int) -> dict[str, Any]:
            return self._table(
                result,
                frame,
                limit,
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                source=source,
                bars_fetched=fetched,
                notices=notices,
            )

        payload = fit_to_budget(build, tail)
        return self._wrapped(
            "compute_indicator", payload, symbol=symbol, exchange=exchange, indicator=name
        )

    def compute_indicators_batch(
        self,
        symbol: str,
        exchange: str,
        indicators: list,
        interval: str = DEFAULT_INTERVAL,
        last_n: int = 10,
        lookback_bars: int = 0,
        source: str = "api",
    ) -> str:
        """Compute several indicators on one instrument in a single call.

        This is the tool for "show me RSI, MACD and ADX", and for anything the
        operator wants as one table. All of them share one candle fetch, so it
        is one broker request instead of several behind a rate limiter, and the
        values line up bar for bar because they came from the same bars.

        **Do not pass dates.** The window is sized from the longest warm-up in
        the batch.

        Args:
            symbol: OpenAlgo symbol, in capitals. For example ``RELIANCE``.
            exchange: Exchange code the symbol is listed on, for example ``NSE``.
            indicators: The indicators to compute, at most 8. Either plain names
                or objects carrying a ``name`` and optional ``params``, and the
                two can be mixed. For example ``["macd", {"name":
                "supertrend", "params": {"period": 10, "multiplier": 3}},
                {"name": "sma", "params": {"period": 50}}]``.
            interval: Candle size. Defaults to ``D`` (daily). Use ``1h`` for
                hourly. Case matters: ``1m`` is one minute and ``M`` is one
                month.
            last_n: How many recent values to return per output, at most 120.
                Defaults to 10, which is the right size for a table the operator
                will read.
            lookback_bars: How many candles to compute over. Leave it 0 to size
                it automatically from the longest warm-up in the batch.
            source: ``api`` for the broker (the default), or ``db`` for the
                local Historify store.

        Returns:
            JSON with the shared timestamps and candles, one result per
            indicator with its values aligned to those timestamps, and any
            indicator that failed reported by name with its reason rather than
            failing the whole call.
        """
        requests = self._batch_requests(indicators)

        symbol, exchange, notices = normalise_pair(symbol, exchange)
        source = normalise_source(source)
        interval, interval_notice = normalise_interval(interval, source, self._intervals.accepted())
        if interval_notice:
            notices.append(interval_notice)

        tail = self._tail(last_n, 10)
        bars = self._lookback(lookback_bars)
        if not bars:
            # One window, sized by the longest warm-up in the batch. Every name
            # was resolved by _batch_requests, so get_spec cannot answer None.
            bars = max(
                required_bars(get_spec(name), arguments, tail) for name, arguments in requests
            )

        frame, fetched = self._frame(symbol, exchange, interval, source, bars)

        results: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        for name, arguments in requests:
            try:
                results.append(compute(name, frame, arguments, last_n=tail))
            except IndicatorError as exc:
                failures.append({"indicator": name, "error": str(exc)})

        if not results:
            raise RetryAgentRun("; ".join(item["error"] for item in failures)) from None

        def build(limit: int) -> dict[str, Any]:
            payload = self._shared(
                frame,
                limit,
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                source=source,
                bars_fetched=fetched,
                notices=notices,
            )
            payload["results"] = [self._trimmed(result, limit) for result in results]
            if failures:
                payload["failed"] = failures
            return payload

        payload = fit_to_budget(build, tail)
        return self._wrapped(
            "compute_indicators_batch",
            payload,
            symbol=symbol,
            exchange=exchange,
            count=len(results),
        )

    def scan_symbols(
        self,
        symbols: list,
        exchange: str,
        indicator: str,
        condition: str,
        interval: str = DEFAULT_INTERVAL,
        params: dict | None = None,
        source: str = "api",
    ) -> str:
        """Screen several instruments for one indicator condition.

        Use it for "which of these is oversold", "which have MACD crossing up",
        "which are trending". Each instrument is a separate broker history call
        behind a rate limiter, so keep the list to the ones the operator named.

        Args:
            symbols: The instruments to scan, at most 15. For example
                ``["SBIN", "RELIANCE", "INFY"]``.
            exchange: Exchange code shared by all of them, for example ``NSE``.
            indicator: Indicator name, for example ``rsi``, ``adx`` or ``macd``.
            condition: What counts as a match. Either a comparison of one output
                against a number, such as ``"rsi < 30"`` or ``"adx > 25"``, or a
                cross between two of that indicator's outputs, such as
                ``"crossover(macd_line, signal_line)"``. Output names come from
                ``describe_indicator``. Nothing else is accepted: this is a
                fixed parser, not an expression evaluator, so no arithmetic, no
                ``and``, no ``or`` and no function other than ``crossover``,
                ``crossunder`` and ``cross``.
            interval: Candle size. Defaults to ``D`` (daily).
            params: Indicator parameters, for example ``{"period": 21}``.
            source: ``api`` for the broker (the default), or ``db`` for the
                local Historify store.

        Returns:
            JSON naming which instruments matched and the value that decided
            each one, every instrument's value whether it matched or not, and
            any instrument that could not be scanned with its reason.
        """
        name = (indicator or "").strip().lower()
        spec = get_spec(name)
        if spec is None:
            self.invalid_argument("indicator", *self._unknown_indicator(indicator))
        if spec.needs_second_series:
            self.invalid_argument(
                "indicator",
                f"{name} compares two instruments and cannot be scanned across a list",
                "Use compute_indicator with compare_symbol instead, once per instrument.",
            )

        parsed = parse_condition(condition)
        if parsed is None:
            self.invalid_argument(
                "condition",
                f"{condition!r} is not one of the two accepted shapes",
                f"{_CONDITION_HELP} Valid output names for {name}: {', '.join(spec.outputs)}.",
            )

        wanted = self._scan_symbols(symbols)
        source = normalise_source(source)
        interval, interval_notice = normalise_interval(interval, source, self._intervals.accepted())
        arguments = params if isinstance(params, Mapping) else {}
        bars = required_bars(spec, arguments, 5)

        matched: list[dict[str, Any]] = []
        checked: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        notices: list[str] = [interval_notice] if interval_notice else []

        for raw in wanted:
            try:
                pair_symbol, pair_exchange, pair_notices = normalise_pair(raw, exchange)
                frame, _ = self._frame(pair_symbol, pair_exchange, interval, source, bars)
                result = compute(name, frame, arguments, last_n=5)
            except IndicatorError as exc:
                failures.append({"symbol": str(raw).strip().upper(), "error": str(exc)[:200]})
                continue
            except Exception as exc:
                # One unreachable instrument costs its own row, never the scan.
                logger.exception("Agent indicator scan could not evaluate %s", raw)
                failures.append({"symbol": str(raw).strip().upper(), "error": str(exc)[:200]})
                continue

            notices.extend(pair_notices)
            hit, detail = evaluate_condition(parsed, result)
            entry = {"symbol": pair_symbol, "exchange": pair_exchange, **detail}
            checked.append(entry)
            if hit:
                matched.append(entry)

        if not checked:
            raise RetryAgentRun(
                "No instrument could be scanned. First failure: "
                + (failures[0]["error"] if failures else "no symbols were usable.")
            ) from None

        payload: dict[str, Any] = {
            "indicator": name,
            "condition": condition,
            "exchange": str(exchange or "").strip().upper(),
            "interval": interval,
            "source": source,
            "params_used": dict(arguments),
            "scanned": len(checked),
            "matched_count": len(matched),
            "matches": matched,
            "all_results": checked,
        }
        if failures:
            payload["failed"] = failures
        if notices:
            payload["notices"] = list(dict.fromkeys(notices))
        return self._wrapped("scan_symbols", payload, indicator=name, matched=len(matched))

    # -- candle access -------------------------------------------------------

    def _frame(
        self, symbol: str, exchange: str, interval: str, source: str, bars: int
    ) -> tuple[pd.DataFrame, int]:
        """Fetch a cleaned candle frame, reusing this run's copy when it is long enough.

        Args:
            symbol: The instrument, already normalised.
            exchange: Its exchange, already normalised.
            interval: The candle size, already validated.
            source: ``api`` or ``db``.
            bars: How many candles are wanted, warm-up already included.

        Returns:
            The frame and how many bars were fetched from the service to
            produce it. The fetch count is zero on a cache hit, which is what
            lets the result say honestly what it cost.

        Raises:
            RetryAgentRun: When the history service fails, or when it returned
                nothing usable.
        """
        key = (symbol, exchange, interval, source)
        cached = self._frames.get(key)
        if cached is not None and cached[0] >= bars:
            return cached[1], 0

        start, end = lookback_range(interval, bars)
        response = self.service_call(
            get_history,
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
        frame = candle_frame(records, columns)

        if frame.empty:
            raise RetryAgentRun(
                f"No usable candles came back for {symbol} on {exchange} at {interval} "
                f"between {start} and {end}. Check the symbol and exchange, confirm the "
                "interval is one this broker serves, and remember an index is quoted on an "
                "index exchange."
            ) from None

        # Keep only the tail asked for, so a broker that over-serves the range
        # does not make every indicator run over years of bars.
        if len(frame) > bars:
            frame = frame.iloc[-bars:]

        if len(self._frames) >= _MAX_CACHED_FRAMES:
            self._frames.pop(next(iter(self._frames)))
        self._frames[key] = (bars, frame)
        return frame, len(records)

    # -- result shaping ------------------------------------------------------

    def _shared(
        self,
        frame: pd.DataFrame,
        limit: int,
        *,
        symbol: str,
        exchange: str,
        interval: str,
        source: str,
        bars_fetched: int,
        notices: list[str],
    ) -> dict[str, Any]:
        """Build the part of a result every indicator on one instrument shares.

        Args:
            frame: The cleaned candle frame the indicators ran over.
            limit: How many recent bars the result carries.
            symbol: The instrument.
            exchange: Its exchange.
            interval: The candle size actually used.
            source: Where the candles came from.
            bars_fetched: Rows the history service returned, or 0 on a reuse.
            notices: Corrections this call made, which the model must be able to
                repeat to the operator.

        Returns:
            The instrument, the window, the candle tail and the bar accounting.
        """
        tail = frame.iloc[-limit:] if limit else frame.iloc[0:0]
        candles = [
            {
                "timestamp": moment.isoformat(),
                **{
                    column: None if pd.isna(value) else float(value)
                    for column, value in row.items()
                },
            }
            for moment, row in tail.iterrows()
        ]

        payload: dict[str, Any] = {
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "source": source,
            "timezone": "Asia/Kolkata",
            "bars_computed_over": int(len(frame)),
            "bars_fetched": int(bars_fetched),
            "values_returned": len(candles),
            "timestamps": [candle["timestamp"] for candle in candles],
            "candles": candles,
        }
        if len(frame) > len(candles):
            payload["note"] = (
                f"Every value was computed over all {len(frame)} bars; the {len(candles)} "
                "most recent are returned, oldest first. Raise last_n for a longer table."
            )
        if notices:
            payload["notices"] = list(dict.fromkeys(notices))
        return payload

    def _table(
        self,
        result: dict[str, Any],
        frame: pd.DataFrame,
        limit: int,
        **shared: Any,
    ) -> dict[str, Any]:
        """Build a single-indicator result around the shared instrument block.

        Args:
            result: One computed indicator result.
            frame: The frame it ran over.
            limit: How many recent values to carry.
            **shared: Arguments for :meth:`_shared`.

        Returns:
            The merged payload.
        """
        payload = self._shared(frame, limit, **shared)
        payload.update(self._trimmed(result, limit))
        return payload

    @staticmethod
    def _trimmed(result: Mapping[str, Any], limit: int) -> dict[str, Any]:
        """Narrow one computed result to ``limit`` values per output.

        The timestamps live once on the shared block rather than once per
        indicator, so a batch of eight does not repeat them eight times.

        Args:
            result: One computed indicator result.
            limit: How many recent values to keep.

        Returns:
            The result without its own timestamps and with each output cut to
            the same length as the shared candle tail.
        """
        out = {key: value for key, value in result.items() if key != "timestamps"}
        out["values"] = {
            label: (values[-limit:] if limit else [])
            for label, values in (result.get("values") or {}).items()
        }
        # Counted from what survived the slice, not from the limit asked for, so
        # a frame shorter than last_n reports the rows it actually carries
        # rather than the rows somebody hoped for.
        out["values_returned"] = max((len(values) for values in out["values"].values()), default=0)
        return out

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

    # -- argument handling ---------------------------------------------------

    @staticmethod
    def _unknown_indicator(name: Any) -> tuple[str, str]:
        """Compose the rejection for an indicator name that is not registered.

        Args:
            name: Whatever the model passed.

        Returns:
            The reason and the fix, for :meth:`invalid_argument`. The fix names
            the nearest matches when the catalogue has any, because a model that
            asked for "bollinger" wants to be told about ``bbands`` rather than
            told to call another tool.
        """
        cleaned = str(name or "").strip().lower()
        near = search_specs(query=cleaned) if cleaned else []
        if near:
            return (
                f"{name!r} is not an indicator on this build",
                f"Did you mean: {', '.join(spec.name for spec in near[:5])}?",
            )
        return (
            f"{name!r} is not one of the {len(REGISTRY)} indicators",
            "Call list_indicators with a keyword to find the right name.",
        )

    def _tail(self, last_n: Any, fallback: int) -> int:
        """Validate the ``last_n`` argument.

        Args:
            last_n: Whatever the model passed.
            fallback: The value to use when it passed nothing usable.

        Returns:
            A row count between 1 and :data:`MAX_LAST_N`.

        Raises:
            RetryAgentRun: When the value is above the cap, because silently
                returning fewer rows than asked for would leave the model
                describing a table it did not receive.
        """
        try:
            wanted = int(last_n)
        except (TypeError, ValueError):
            return fallback
        if wanted < 1:
            return fallback
        if wanted > MAX_LAST_N:
            self.invalid_argument(
                "last_n",
                f"{wanted} values per output is more than the {MAX_LAST_N} one result carries",
                f"Ask for at most {MAX_LAST_N}, or narrow the question. Every value costs "
                "context, and a table longer than this is not read.",
            )
        return wanted

    def _lookback(self, lookback_bars: Any) -> int:
        """Validate the ``lookback_bars`` argument.

        One helper for both compute tools, because an unbounded bar count is a
        memory bound as well as an argument: the fetched window becomes a
        DataFrame this run's cache holds, and the cache holds up to
        :data:`_MAX_CACHED_FRAMES` of them in a worker that never restarts.

        Args:
            lookback_bars: Whatever the model passed.

        Returns:
            A bar count, or 0 meaning "size it from the indicator's warm-up",
            which is the default and the right answer almost always.

        Raises:
            RetryAgentRun: When the value is above the cap, rather than silently
                computing over fewer bars than the model believes it asked for.
        """
        try:
            wanted = int(lookback_bars)
        except (TypeError, ValueError):
            return 0
        if wanted <= 0:
            return 0
        if wanted > MAX_LOOKBACK_BARS:
            self.invalid_argument(
                "lookback_bars",
                f"{wanted} candles is more than the {MAX_LOOKBACK_BARS} one call computes over",
                f"Ask for at most {MAX_LOOKBACK_BARS}, or leave it 0 and let the indicator's "
                "own warm-up size the window, which is what you want unless you are "
                "deliberately looking further back.",
            )
        return wanted

    def _batch_requests(self, indicators: Any) -> list[tuple[str, dict[str, Any]]]:
        """Normalise the ``indicators`` argument of :meth:`compute_indicators_batch`.

        Args:
            indicators: Whatever the model passed: names, objects, or a mixture.

        Returns:
            One ``(name, params)`` pair per requested indicator, de-duplicated
            on the pair so the same indicator with two parameter sets is kept
            but an accidental repeat is not computed twice.

        Raises:
            RetryAgentRun: When the argument is empty, too long, or carries no
                usable entry.
        """
        if isinstance(indicators, (str, Mapping)):
            indicators = [indicators]
        if not isinstance(indicators, (list, tuple)) or not indicators:
            self.invalid_argument(
                "indicators",
                "it is empty or is not a list",
                'Pass a list, for example ["rsi", {"name": "sma", "params": {"period": 50}}].',
            )
        if len(indicators) > MAX_BATCH_INDICATORS:
            self.invalid_argument(
                "indicators",
                f"it carries {len(indicators)} entries, more than the "
                f"{MAX_BATCH_INDICATORS} one call computes",
                f"Split it into batches of at most {MAX_BATCH_INDICATORS}.",
            )

        requests: list[tuple[str, dict[str, Any]]] = []
        seen: set[str] = set()
        for index, item in enumerate(indicators):
            if isinstance(item, str):
                name, arguments = item.strip().lower(), {}
            elif isinstance(item, Mapping):
                lowered = {str(key).strip().lower(): value for key, value in item.items()}
                # "indicator" is accepted alongside "name" because the sibling
                # tool's argument is called indicator, so a model that has just
                # used compute_indicator reaches for that word. Refusing it
                # costs a whole round trip to learn one synonym.
                name = str(lowered.get("name") or lowered.get("indicator") or "").strip().lower()
                raw = lowered.get("params")
                arguments = dict(raw) if isinstance(raw, Mapping) else {}
            else:
                self.invalid_argument(
                    "indicators",
                    f"entry {index + 1} is {type(item).__name__}, not a name or an object",
                    'Every entry is either "rsi" or {"name": "rsi", "params": {"period": 21}}.',
                )
            if not name:
                self.invalid_argument(
                    "indicators",
                    f"entry {index + 1} carries no indicator name",
                    'Every object entry needs a "name", for example {"name": "macd"}. '
                    '"indicator" is accepted as well.',
                )
            if get_spec(name) is None:
                self.invalid_argument("indicators", *self._unknown_indicator(name))

            marker = f"{name}:{sorted(arguments.items())}"
            if marker in seen:
                continue
            seen.add(marker)
            requests.append((name, arguments))
        return requests

    def _scan_symbols(self, symbols: Any) -> list[str]:
        """Normalise the ``symbols`` argument of :meth:`scan_symbols`.

        Args:
            symbols: Whatever the model passed.

        Returns:
            The de-duplicated symbols to scan, in the order given.

        Raises:
            RetryAgentRun: When the argument is empty, not a list, or longer
                than the cap.
        """
        if isinstance(symbols, str):
            symbols = [symbols]
        if not isinstance(symbols, (list, tuple)) or not symbols:
            self.invalid_argument(
                "symbols",
                "it is empty or is not a list",
                'Pass a list, for example ["SBIN", "RELIANCE", "INFY"].',
            )
        if len(symbols) > MAX_SCAN_SYMBOLS:
            self.invalid_argument(
                "symbols",
                f"it carries {len(symbols)} instruments, more than the {MAX_SCAN_SYMBOLS} "
                "one scan covers",
                f"Scan at most {MAX_SCAN_SYMBOLS} at a time; each one is a separate broker "
                "history call behind a rate limiter.",
            )

        cleaned: list[str] = []
        for item in symbols:
            text = str(item or "").strip().upper()
            if text and text not in cleaned:
                cleaned.append(text)
        if not cleaned:
            self.invalid_argument(
                "symbols",
                "none of the entries is a symbol",
                'Pass a list of OpenAlgo symbols, for example ["SBIN", "RELIANCE"].',
            )
        return cleaned
