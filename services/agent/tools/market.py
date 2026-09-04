"""Market data tools: quotes, depth, candles and the broker's interval list.

Five read-only tools, all of them calling OpenAlgo's internal service layer
directly. Nothing here makes an HTTP request back into this process and nothing
here uses the ``openalgo`` SDK, which is for generated strategy code rather than
for platform internals.

Three decisions in this file are worth knowing about before changing it.

**A history frame is summarised, not dumped.** ``get_history`` on a minute
interval over a month is tens of thousands of candles, and handing that to a
model wastes the whole context window to answer a question about the last few
bars. The tool computes the summary over **every** row it received (first open,
last close, the true high and low, total volume, the change across the range)
and then returns only a bounded tail of candles, saying in the result how many
older ones were dropped. The base class would otherwise cap the string
mid-value, which reads to the model as a broken result rather than a deliberate
one.

**The interval is checked against the broker, not against a list in this file.**
Every broker advertises its own resolutions through
``services.intervals_service``, so a hardcoded list would either refuse an
interval that works or accept one that 400s. When that lookup itself fails the
check is skipped rather than failing closed: this is a read-only tool, and
refusing a history call because the intervals endpoint hiccuped is the worse
failure. The history service still validates, so nothing unsafe gets through.

**An index is quoted on an index exchange.** ``NIFTY`` on ``NSE`` does not
exist; it lives on ``NSE_INDEX``. Rather than failing, the tools ask the symbol
database whether the pair the model gave actually resolves, and if it does not
but the same symbol resolves on an index exchange, they use that one and say so
in the result. The correction is data-driven, never a guess from the symbol's
spelling, and it only ever moves **towards** an index exchange, so a genuine
"symbol not found" is still reported as one.

Every result leaves through :func:`services.agent.prompts.wrap_tool_result`, so
what re-enters the model's context is labelled as data rather than as something
it should obey.

**The argument handling is module level, not private to the toolkit.** The
visualization toolkit charts the same candles this one summarises, so it reaches
history through :func:`normalise_pair`, :func:`normalise_source`,
:func:`normalise_range`, :func:`normalise_interval` and :class:`BrokerIntervals`
here rather than through a second copy of them. A copy would drift, and the copy
in the chart path is the one nobody notices is wrong. The same reasoning puts
:func:`candle_columns`, :func:`summarise_candles`, :func:`epoch_seconds`,
:func:`chart_bars` and :func:`candle_frame` here: they are the shared reading of
a history frame, and the chart tools, the instrument card and the indicator
tools all go through them. :func:`lookback_range` and :func:`fit_to_budget` are
here for the same reason, one sizing a fetch from a bar count and the other
bounding a result to the character budget. :func:`symbol_pairs` and
:func:`pair_fields` join them because a live subscription card takes the same
list of instruments this toolkit's batched quote does.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from database.token_db import get_token
from services import depth_service, history_service, intervals_service, quotes_service
from services.agent.prompts import wrap_tool_result
from services.agent.tools.base import (
    MAX_JSON_CHARS,
    OpenAlgoToolkit,
    as_number,
    invalid_argument,
    json_safe,
)
from services.indicator_service import MAX_HISTORY_CALENDAR_DAYS, calendar_days_for_bars
from utils.constants import VALID_EXCHANGES
from utils.logging import get_logger

logger = get_logger(__name__)

#: The platform states every timestamp in IST, and a broker's market timestamps
#: are IST, so the conversion is fixed rather than taken from the server locale.
IST = ZoneInfo("Asia/Kolkata")

#: Quote-only exchanges an index is listed on, in the order they are tried when
#: the pair the model asked for does not resolve.
INDEX_EXCHANGES: tuple[str, ...] = ("NSE_INDEX", "BSE_INDEX", "MCX_INDEX", "GLOBAL_INDEX")

#: The index exchange to try first, given the exchange the model asked for. A
#: request for NIFTY on NSE is far more likely to mean NSE_INDEX than BSE_INDEX.
_INDEX_FIRST_CHOICE: Mapping[str, str] = {
    "NSE": "NSE_INDEX",
    "NFO": "NSE_INDEX",
    "BSE": "BSE_INDEX",
    "BFO": "BSE_INDEX",
    "MCX": "MCX_INDEX",
}

#: Most symbols one ``get_quotes`` call may carry. A broker multiquote request
#: is batched upstream, but an unbounded list is a slow call whose result cannot
#: fit anyway.
MAX_MULTIQUOTE_SYMBOLS = 50

#: Most candles ``get_history`` returns, before the character budget is even
#: considered. A model answers questions about a trend from the recent tail plus
#: the summary; it does not need five thousand bars, and asking it to read them
#: costs more than the answer is worth.
MAX_HISTORY_ROWS = 200

#: Character budget for the JSON inside a result, kept under the base class cap
#: so a payload this module sized itself is never truncated by ``to_json``.
_JSON_BUDGET = MAX_JSON_CHARS - 256

#: The columns a history frame carries, in the order they are emitted.
_CANDLE_FIELDS: tuple[str, ...] = ("timestamp", "open", "high", "low", "close", "volume", "oi")

#: Epoch values at or above this are milliseconds rather than seconds. The
#: boundary is far past any plausible seconds timestamp (year 5138) and far
#: below any plausible milliseconds one (1973).
_EPOCH_MILLISECOND_FLOOR = 100_000_000_000

_DATE_FORMAT = "%Y-%m-%d"


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def _rendered_length(payload: Any) -> int:
    """Measure how many characters a payload occupies once serialised.

    Args:
        payload: The object about to be returned to the model.

    Returns:
        The length of its compact JSON form, or a value above the budget when
        it cannot be serialised at all, so the caller shrinks it rather than
        assuming it fits.
    """
    try:
        return len(
            json.dumps(json_safe(payload), ensure_ascii=False, separators=(",", ":"), default=str)
        )
    except (TypeError, ValueError):
        logger.exception("Could not measure the size of an agent market-data payload")
        return _JSON_BUDGET + 1


def _ist_timestamp(value: Any) -> Any:
    """Render a candle timestamp as an ISO-8601 string in IST.

    A broker frame carries the timestamp as epoch seconds, epoch milliseconds,
    a pandas ``Timestamp`` or an ISO string depending on the plugin. The model
    reads dates, not epochs, so everything numeric is converted and everything
    else is passed through untouched.

    Args:
        value: The raw ``timestamp`` field of one candle.

    Returns:
        An ISO-8601 string in Asia/Kolkata when the value was a usable epoch,
        otherwise the value unchanged.
    """
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value

    seconds = float(value)
    if abs(seconds) >= _EPOCH_MILLISECOND_FLOOR:
        seconds /= 1000.0
    try:
        return datetime.fromtimestamp(seconds, IST).isoformat()
    except (OSError, OverflowError, ValueError):
        return value


def epoch_seconds(value: Any) -> int | None:
    """Render a candle timestamp as UTC epoch seconds for a chart series.

    The counterpart to :func:`_ist_timestamp`, which renders the same field for
    a model to read. A chart needs the number, and it needs the same number
    ``openalgo-charts`` computes for itself when it fetches history directly:
    epoch values are taken verbatim (milliseconds scaled down), and a string or
    a naive datetime is read as an IST wall clock, because that is what the
    platform states every timestamp in.

    Args:
        value: The raw ``timestamp`` field of one candle.

    Returns:
        UTC epoch seconds, or None when the value is not a usable timestamp, in
        which case the candle is dropped rather than plotted at the epoch.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        moment = value if value.tzinfo is not None else value.replace(tzinfo=IST)
        return int(moment.timestamp())
    if isinstance(value, date):
        return int(datetime(value.year, value.month, value.day, tzinfo=IST).timestamp())

    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(text.replace(" ", "T", 1))
            except ValueError:
                return None
            return epoch_seconds(parsed)

    if not math.isfinite(number):
        return None
    if abs(number) >= _EPOCH_MILLISECOND_FLOOR:
        number /= 1000.0
    return int(number)


def ist_label(seconds: Any) -> str:
    """Render UTC epoch seconds as the IST wall clock a person reads.

    The inverse of :func:`epoch_seconds`, and here beside it for that reason:
    the chart tools speak epoch seconds to the canvas and IST strings to the
    model, and the two conversions drifting apart would put a level on the wrong
    day in the narration while drawing it on the right one.

    Args:
        seconds: UTC epoch seconds, as a number.

    Returns:
        ``YYYY-MM-DD HH:MM`` in Asia/Kolkata, or an empty string when the value
        is not a usable timestamp.
    """
    number = as_number(seconds)
    if number is None:
        return ""
    try:
        return datetime.fromtimestamp(number, IST).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return ""


def candle_columns(row: Mapping[str, Any]) -> dict[str, str]:
    """Map the candle field names this module uses onto a frame's own keys.

    Args:
        row: One record from the history frame.

    Returns:
        Field name to the key it is stored under, for the fields present. Built
        once from the first row, because a frame's records are uniform.
    """
    lowered = {str(key).strip().lower(): str(key) for key in row}
    return {field: lowered[field] for field in _CANDLE_FIELDS if field in lowered}


def _candle(row: Mapping[str, Any], columns: Mapping[str, str]) -> dict[str, Any]:
    """Build one returned candle from a frame record.

    Args:
        row: The record.
        columns: The mapping from :func:`candle_columns`.

    Returns:
        The candle with its timestamp rendered in IST. A record whose columns
        were unrecognisable is returned as-is rather than emptied.
    """
    if not columns:
        return dict(row)

    out: dict[str, Any] = {}
    for field, key in columns.items():
        value = row.get(key)
        out[field] = _ist_timestamp(value) if field == "timestamp" else value
    return out


def summarise_candles(rows: list[Mapping[str, Any]], columns: Mapping[str, str]) -> dict[str, Any]:
    """Reduce a whole history frame to the numbers an answer usually needs.

    Computed over every row, including the ones that will not be returned, so
    the high, the low and the volume describe the range that was asked for
    rather than only the tail that fitted.

    Args:
        rows: Every record the service returned, oldest first.
        columns: The mapping from :func:`candle_columns`.

    Returns:
        First open, last close, highest high, lowest low, total volume and the
        change across the range, plus the IST timestamps of the bars the high
        and the low were set on. A statistic no row supplied is omitted rather
        than reported as zero.

        The two extreme timestamps are what turns a 52 week high into a date the
        operator can act on rather than a bare number, so they are computed here
        beside the extremes themselves rather than by a second pass somewhere
        else that could disagree about which bar won a tie.
    """
    summary: dict[str, Any] = {}
    if not rows:
        return summary

    first_open: float | None = None
    last_close: float | None = None
    highest: float | None = None
    lowest: float | None = None
    highest_at: Any = None
    lowest_at: Any = None
    volume_total = 0.0
    volume_seen = False

    open_key = columns.get("open")
    high_key = columns.get("high")
    low_key = columns.get("low")
    close_key = columns.get("close")
    volume_key = columns.get("volume")
    timestamp_key = columns.get("timestamp")

    for row in rows:
        if open_key and first_open is None:
            first_open = as_number(row.get(open_key))
        if close_key:
            close = as_number(row.get(close_key))
            if close is not None:
                last_close = close
        if high_key:
            high = as_number(row.get(high_key))
            if high is not None and (highest is None or high > highest):
                highest = high
                highest_at = row.get(timestamp_key) if timestamp_key else None
        if low_key:
            low = as_number(row.get(low_key))
            if low is not None and (lowest is None or low < lowest):
                lowest = low
                lowest_at = row.get(timestamp_key) if timestamp_key else None
        if volume_key:
            volume = as_number(row.get(volume_key))
            if volume is not None:
                volume_total += volume
                volume_seen = True

    if timestamp_key:
        summary["first_timestamp"] = _ist_timestamp(rows[0].get(timestamp_key))
        summary["last_timestamp"] = _ist_timestamp(rows[-1].get(timestamp_key))
    if first_open is not None:
        summary["first_open"] = first_open
    if last_close is not None:
        summary["last_close"] = last_close
    if highest is not None:
        summary["highest_high"] = highest
        if highest_at is not None:
            summary["highest_high_timestamp"] = _ist_timestamp(highest_at)
    if lowest is not None:
        summary["lowest_low"] = lowest
        if lowest_at is not None:
            summary["lowest_low_timestamp"] = _ist_timestamp(lowest_at)
    if volume_seen:
        summary["total_volume"] = round(volume_total, 4)
    if first_open is not None and last_close is not None:
        summary["change"] = round(last_close - first_open, 6)
        if first_open:
            summary["change_percent"] = round((last_close - first_open) / first_open * 100.0, 4)

    return summary


def chart_bars(
    records: Sequence[Mapping[str, Any]], columns: Mapping[str, str]
) -> list[dict[str, Any]]:
    """Turn a history frame into the bar series a chart draws.

    The shape is ``openalgo-charts``'s own ``Bar``: ``time`` in UTC epoch
    seconds, then ``open``, ``high``, ``low``, ``close`` and an optional
    ``volume``. It is exactly what the library's ``OpenAlgoDataFeed`` builds when
    the terminal fetches history itself, so a chart in the conversation and a
    chart on ``/trading`` are drawn from identically shaped data.

    Module level, and here rather than in a chart module, because every tool
    that draws price over time needs the same conversion: the candle chart, the
    instrument card's intraday strip, and whatever comes next. One conversion is
    what keeps them agreeing about which bars were dropped and why.

    Args:
        records: The service's rows, oldest first.
        columns: The mapping from :func:`candle_columns`.

    Returns:
        The bars, oldest first, with any row carrying no usable timestamp or no
        close dropped rather than plotted at the epoch.
    """
    if not columns:
        return []

    time_key = columns.get("timestamp")
    open_key = columns.get("open")
    high_key = columns.get("high")
    low_key = columns.get("low")
    close_key = columns.get("close")
    volume_key = columns.get("volume")
    if not time_key or not close_key:
        return []

    bars: list[dict[str, Any]] = []
    for row in records:
        moment = epoch_seconds(row.get(time_key))
        close = as_number(row.get(close_key))
        if moment is None or close is None:
            continue
        bar: dict[str, Any] = {
            "time": moment,
            "open": as_number(row.get(open_key)) if open_key else close,
            "high": as_number(row.get(high_key)) if high_key else close,
            "low": as_number(row.get(low_key)) if low_key else close,
            "close": close,
        }
        for field in ("open", "high", "low"):
            if bar[field] is None:
                bar[field] = close
        if volume_key:
            volume = as_number(row.get(volume_key))
            if volume is not None:
                bar["volume"] = volume
        bars.append(bar)

    bars.sort(key=lambda item: item["time"])
    return bars


def candle_frame(records: Sequence[Mapping[str, Any]], columns: Mapping[str, str]) -> pd.DataFrame:
    """Turn a history frame into the cleaned DataFrame an indicator can run on.

    The third reading of a history frame that lives here, beside
    :func:`summarise_candles` and :func:`chart_bars`, for the same reason: the
    indicator tools and the chart tools must agree about which bars a broker
    actually returned, and a second copy of this conversion is how they would
    stop agreeing.

    Cleaning is not cosmetic. The ``ta`` backend's ``sma`` and ``rolling_sum``
    are cumulative-sum based, so **one** NaN anywhere in the input poisons every
    later value: measured on this build, a single NaN at bar 50 of 900 left
    ``ta.sma`` with 37 finite values out of 900. A column that is entirely
    missing is dropped rather than emptying the frame, so an index with no
    volume still computes its price indicators and refuses only the volume ones,
    naming the column it lacks.

    Args:
        records: The service's rows, in whatever order the broker sent them.
        columns: The mapping from :func:`candle_columns`.

    Returns:
        A frame indexed by IST timestamp, oldest first, with unique timestamps,
        float ``open``, ``high``, ``low``, ``close`` and ``volume`` columns
        where the broker supplied them, and no NaN left anywhere. An empty
        frame when the records carry no usable timestamp or no close.
    """
    time_key = columns.get("timestamp")
    if not records or not time_key:
        return pd.DataFrame()

    index: list[Any] = []
    series: dict[str, list[float | None]] = {
        field: [] for field in ("open", "high", "low", "close", "volume") if field in columns
    }
    for row in records:
        moment = epoch_seconds(row.get(time_key))
        if moment is None:
            continue
        index.append(moment)
        for field in series:
            series[field].append(as_number(row.get(columns[field])))

    if not index or "close" not in series:
        return pd.DataFrame()

    frame = pd.DataFrame(series, index=pd.to_datetime(index, unit="s", utc=True).tz_convert(IST))
    frame = frame.astype("float64")
    # A column the broker never populated would empty the whole frame under
    # dropna. Drop the column instead, so the indicator that needs it refuses
    # by name and every other indicator still runs.
    frame = frame.dropna(axis="columns", how="all")
    frame = frame.dropna(axis="index", how="any")
    frame = frame[~frame.index.duplicated(keep="last")]
    return frame.sort_index()


def fit_to_budget(build: Callable[[int], dict[str, Any]], start: int) -> dict[str, Any]:
    """Build the largest payload that fits the character budget.

    Module level, and shared, because every tool that answers with a bounded
    list of rows needs it: the history summary, the multi-quote result and the
    indicator tables all have to drop rows deliberately rather than let
    ``to_json`` cut the string mid-value, which reads to the model as a broken
    result rather than a bounded one.

    Args:
        build: Builds the payload for a given number of rows. It is responsible
            for saying in the payload how many were omitted.
        start: Row count to try first.

    Returns:
        The payload for the largest row count that fits, down to none at all,
        so the caller always returns a well-formed result rather than a
        truncation envelope.
    """
    limit = max(0, start)
    while True:
        payload = build(limit)
        length = _rendered_length(payload)
        if limit == 0 or length <= _JSON_BUDGET:
            return payload
        # Scale the row count by how far over budget this attempt was, which
        # lands within a row or two of the real limit instead of halving away
        # rows that would have fitted. The min guarantees progress even when the
        # estimate does not move, so the loop always terminates.
        limit = min(limit - 1, max(0, int(limit * _JSON_BUDGET / length)))


def lookback_range(interval: str, bars: int, end_date: date | None = None) -> tuple[str, str]:
    """Derive a history date range covering roughly ``bars`` candles.

    This is what lets a tool take a lookback instead of asking the operator
    which dates to use. The calendar span comes from
    ``services.indicator_service.calendar_days_for_bars``, the same arithmetic
    Flow's history nodes size their own window with, so the two cannot drift.

    Args:
        interval: The candle interval, in OpenAlgo's own vocabulary.
        bars: How many candles are wanted, warm-up already included.
        end_date: Last day of the range. Defaults to today in IST, because the
            platform states every timestamp in IST and a server in another zone
            would otherwise ask for tomorrow or miss today.

    Returns:
        The start and end days as ``YYYY-MM-DD``.
    """
    end = end_date or datetime.now(IST).date()
    days = min(calendar_days_for_bars(max(int(bars), 1), interval), MAX_HISTORY_CALENDAR_DAYS)
    return (end - timedelta(days=days)).strftime(_DATE_FORMAT), end.strftime(_DATE_FORMAT)


# ---------------------------------------------------------------------------
# Shared argument handling
# ---------------------------------------------------------------------------
#
# These are module level rather than methods because more than one toolkit
# needs them: the visualization toolkit charts the same candles this one
# summarises, and it has to reach them through the same symbol correction, the
# same date parsing and the same broker interval check. A second copy would
# drift, and the copy in the chart path is the one nobody notices is wrong.


def is_listed(symbol: str, exchange: str) -> bool:
    """Report whether the symbol database holds this pair.

    Args:
        symbol: The symbol, in capitals.
        exchange: The exchange code.

    Returns:
        True when the master contract carries the pair. A lookup failure
        answers False, which leaves the exchange the caller asked for untouched
        and lets the service report the real problem.
    """
    try:
        return get_token(symbol, exchange) is not None
    except Exception:
        logger.exception(
            "Agent market tool could not look up %s on %s in the symbol database",
            symbol,
            exchange,
        )
        return False


def index_candidates(exchange: str) -> tuple[str, ...]:
    """Order the index exchanges to try for a requested exchange.

    Args:
        exchange: The exchange the model asked for.

    Returns:
        Every index exchange, with the one most likely to be meant first.
    """
    first = _INDEX_FIRST_CHOICE.get(exchange)
    if not first:
        return INDEX_EXCHANGES
    return (first, *(item for item in INDEX_EXCHANGES if item != first))


def resolve_exchange(symbol: str, exchange: str) -> tuple[str, str | None]:
    """Move a symbol onto an index exchange when that is where it is listed.

    Driven entirely by the symbol database, never by the spelling of the
    symbol: the pair is corrected only when the requested one does not resolve
    and an index one does. That means a genuinely unknown symbol is still
    reported as unknown, and a tradable instrument is never quietly moved onto a
    quote-only exchange.

    Args:
        symbol: The symbol, already in capitals.
        exchange: The exchange the model asked for, already validated.

    Returns:
        The exchange to use, and a notice when it differs from the request.
    """
    if is_listed(symbol, exchange):
        return exchange, None

    for candidate in index_candidates(exchange):
        if candidate == exchange or not is_listed(symbol, candidate):
            continue
        logger.debug(
            "Agent market tool: %s is not listed on %s; using %s", symbol, exchange, candidate
        )
        return candidate, (
            f"{symbol} is not listed on {exchange}, but it is listed on {candidate}, so "
            f"{candidate} was used. Index values are quoted on the index exchanges and "
            "cannot be traded there; the tradable instrument is the index future or option."
        )

    return exchange, None


def normalise_pair(symbol: Any, exchange: Any) -> tuple[str, str, list[str]]:
    """Normalise one symbol and exchange, correcting an index exchange.

    Args:
        symbol: The symbol the model supplied.
        exchange: The exchange the model supplied.

    Returns:
        The symbol in capitals, the exchange to use, and any notices to put in
        the result.

    Raises:
        RetryAgentRun: If either argument is empty or the exchange is not an
            OpenAlgo exchange code.
    """
    cleaned_symbol = str(symbol or "").strip().upper()
    if not cleaned_symbol:
        invalid_argument(
            "symbol",
            "it is empty",
            "Pass the OpenAlgo symbol in capitals, for example 'INFY' or 'NIFTY'.",
        )

    cleaned_exchange = str(exchange or "").strip().upper().replace(" ", "_").replace("-", "_")
    if not cleaned_exchange:
        invalid_argument(
            "exchange",
            "it is empty",
            f"Pass one of: {', '.join(VALID_EXCHANGES)}.",
        )
    if cleaned_exchange not in VALID_EXCHANGES:
        invalid_argument(
            "exchange",
            f"{cleaned_exchange!r} is not an OpenAlgo exchange code",
            f"Pass one of: {', '.join(VALID_EXCHANGES)}.",
        )

    resolved, notice = resolve_exchange(cleaned_symbol, cleaned_exchange)
    return cleaned_symbol, resolved, [notice] if notice else []


def normalise_source(source: Any) -> str:
    """Validate the history source.

    Args:
        source: The value the model supplied.

    Returns:
        ``api`` or ``db``.

    Raises:
        RetryAgentRun: For anything else.
    """
    cleaned = str(source or "api").strip().lower()
    if cleaned not in {"api", "db"}:
        invalid_argument(
            "source",
            f"{cleaned!r} is not a data source",
            "Use 'api' for live broker history, or 'db' for candles already downloaded "
            "into the local Historify store.",
        )
    return cleaned


def normalise_date(field: str, value: Any) -> str:
    """Parse one ``YYYY-MM-DD`` date argument.

    Args:
        field: The argument name, named in the error message.
        value: The value the model supplied.

    Returns:
        The date as ``YYYY-MM-DD``.

    Raises:
        RetryAgentRun: If it cannot be parsed.
    """
    if isinstance(value, (datetime, date)):
        return value.strftime(_DATE_FORMAT)

    text = str(value or "").strip()
    try:
        return datetime.strptime(text, _DATE_FORMAT).strftime(_DATE_FORMAT)
    except ValueError:
        invalid_argument(
            field,
            f"{text!r} is not a date",
            "Use YYYY-MM-DD, for example 2026-01-15.",
        )


def normalise_range(start_date: Any, end_date: Any) -> tuple[str, str]:
    """Validate a history date range.

    Args:
        start_date: First day, as ``YYYY-MM-DD``.
        end_date: Last day, as ``YYYY-MM-DD``.

    Returns:
        The two dates, normalised.

    Raises:
        RetryAgentRun: If either date is unparseable or the range is backwards.
    """
    start = normalise_date("start_date", start_date)
    end = normalise_date("end_date", end_date)
    if start > end:
        invalid_argument(
            "start_date",
            f"it is {start}, which is after end_date {end}",
            "Pass the earlier day as start_date.",
        )
    return start, end


def normalise_interval(
    interval: Any, source: str, accepted: list[str] | None
) -> tuple[str, str | None]:
    """Validate the candle interval against what this broker accepts.

    The accepted set comes from ``services.intervals_service`` through
    :class:`BrokerIntervals`, never from a list in this file, because it is per
    broker. Two deliberate softenings: a value that differs only in case from an
    accepted one is corrected with a notice (a model asking for ``5M`` means five
    minutes), and the check is skipped entirely for ``source='db'``, whose
    candles come from the local Historify store and whose resolutions are the
    ones the operator downloaded rather than the ones the broker serves.

    Args:
        interval: The value the model supplied.
        source: ``api`` or ``db``.
        accepted: The intervals this broker accepts, or None when the lookup
            failed and the check is to be skipped.

    Returns:
        The interval to use, and a notice when it was corrected.

    Raises:
        RetryAgentRun: If the broker's own list does not contain it.
    """
    cleaned = str(interval or "").strip()
    if not cleaned:
        invalid_argument(
            "interval",
            "it is empty",
            "Pass a candle size such as '5m', '1h' or 'D'. Call get_intervals for the "
            "ones this broker accepts.",
        )

    if source != "api":
        return cleaned, None

    if not accepted or cleaned in accepted:
        # No list means the intervals lookup failed. This is a read-only tool,
        # so it is skipped rather than failing closed; the history service
        # validates the interval again anyway.
        return cleaned, None

    matches = [value for value in accepted if value.lower() == cleaned.lower()]
    if len(matches) == 1:
        return matches[0], (
            f"The interval was read as {matches[0]!r} rather than {cleaned!r}. Interval "
            "names are case sensitive: 'm' is minutes and 'M' is months."
        )

    invalid_argument(
        "interval",
        f"{cleaned!r} is not one this broker accepts",
        f"Use one of: {', '.join(accepted)}.",
    )


def pair_fields(item: Any, index: int, field: str = "symbols") -> tuple[Any, Any]:
    """Pull the symbol and exchange out of one entry of a symbol list.

    Args:
        item: The entry, an object or an ``EXCHANGE:SYMBOL`` string.
        index: Its position in the list, named in the error so the model knows
            which entry to fix.
        field: The argument being read, named in the error.

    Returns:
        The raw symbol and exchange, before normalisation.

    Raises:
        RetryAgentRun: If the entry is not a usable pair.
    """
    if isinstance(item, Mapping):
        lowered = {str(key).strip().lower(): value for key, value in item.items()}
        symbol = lowered.get("symbol")
        exchange = lowered.get("exchange")
        if symbol is None or exchange is None:
            invalid_argument(
                field,
                f"entry {index + 1} is missing 'symbol' or 'exchange'",
                'Every entry needs both, for example {"symbol": "INFY", "exchange": "NSE"}.',
            )
        return symbol, exchange

    if isinstance(item, str) and ":" in item:
        exchange, _, symbol = item.partition(":")
        return symbol, exchange

    invalid_argument(
        field,
        f"entry {index + 1} is {type(item).__name__}, not an object carrying a symbol "
        "and an exchange",
        'Pass objects, for example [{"symbol": "INFY", "exchange": "NSE"}].',
    )


def symbol_pairs(
    symbols: Any,
    *,
    field: str = "symbols",
    limit: int = MAX_MULTIQUOTE_SYMBOLS,
    truncate: bool = False,
) -> tuple[list[dict[str, str]], list[str]]:
    """Normalise a list of instruments a model passed as a tool argument.

    Accepts the documented list of objects, a single object, and a JSON string
    of either, because a model that has been told to send an array still
    sometimes sends the array as text. Every pair goes through
    :func:`normalise_pair`, so an index symbol lands on its index exchange here
    rather than in each caller.

    Module level rather than private to the quote toolkit, because a live
    subscription card takes exactly the same argument. A second copy would
    drift, and the copy nobody is looking at is the one that goes wrong.

    Args:
        symbols: Whatever the model passed.
        field: The argument's name, used in every failure message.
        limit: Most entries this caller accepts.
        truncate: True to drop the entries past ``limit`` with a notice, which
            is what a card holding a live subscription per entry wants. False
            to refuse the whole call, which is what a one-shot batch request
            wants, because there the model can simply ask again in batches.

    Returns:
        The de-duplicated pairs, and any notices for the result.

    Raises:
        RetryAgentRun: If the argument is not a usable list of pairs, or it is
            over ``limit`` and ``truncate`` is false.
    """
    raw = symbols
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            invalid_argument(
                field,
                "it is a string that is not valid JSON",
                'Pass a list of objects, for example [{"symbol": "INFY", "exchange": "NSE"}].',
            )
    if isinstance(raw, Mapping):
        raw = [raw]
    if not isinstance(raw, (list, tuple)) or not raw:
        invalid_argument(
            field,
            "it is empty or is not a list",
            'Pass a list of objects, for example [{"symbol": "INFY", "exchange": "NSE"}, '
            '{"symbol": "SBIN", "exchange": "NSE"}].',
        )

    notices: list[str] = []
    if len(raw) > limit:
        if not truncate:
            invalid_argument(
                field,
                f"it carries {len(raw)} entries, more than the {limit} allowed in one call",
                f"Split it into batches of at most {limit} and call the tool once per batch.",
            )
        notices.append(
            f"{len(raw) - limit} of {len(raw)} entries were dropped, because this call "
            f"carries at most {limit}."
        )
        raw = list(raw)[:limit]

    pairs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    duplicates = 0

    for index, item in enumerate(raw):
        symbol, exchange = pair_fields(item, index, field)
        symbol, exchange, item_notices = normalise_pair(symbol, exchange)
        notices.extend(item_notices)
        key = (symbol, exchange)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        pairs.append({"symbol": symbol, "exchange": exchange})

    if duplicates:
        notices.append(
            f"{duplicates} duplicate entries were requested once each rather than repeatedly."
        )
    return pairs, notices


class BrokerIntervals:
    """The connected broker's interval list, fetched at most once per run.

    Held by a toolkit rather than cached at module level, so it lives exactly as
    long as the run that built it and a broker change is picked up on the next
    turn rather than never.

    Attributes:
        error: The reason the lookup failed, once it has failed. Reported to the
            model instead of asking the broker again.
    """

    __slots__ = ("_accepted", "_fetch", "_loaded", "_payload", "error")

    def __init__(self, fetch: Callable[[], Any]) -> None:
        """Build the cache.

        Args:
            fetch: Calls ``intervals_service.get_intervals`` through the
                toolkit's own ``service_call``, so a failure arrives as the same
                actionable error every other service call raises.
        """
        self._fetch = fetch
        self._payload: dict[str, Any] | None = None
        self._accepted: list[str] | None = None
        self._loaded = False
        self.error: str | None = None

    def payload(self) -> dict[str, Any] | None:
        """The grouped interval list, fetched once.

        Returns:
            The payload for the ``get_intervals`` tool, or None when the service
            returned nothing usable.

        Raises:
            RetryAgentRun: On the first failure only. A second call in the same
                run reports :attr:`error` instead of asking the broker again.
        """
        if self._loaded:
            return self._payload

        self._loaded = True
        try:
            response = self._fetch()
        except Exception as exc:
            self.error = str(exc)
            raise

        grouped = response.get("data") if isinstance(response, Mapping) else None
        if not isinstance(grouped, Mapping):
            return None

        accepted: list[str] = []
        for values in grouped.values():
            if isinstance(values, (list, tuple)):
                accepted.extend(str(value) for value in values)

        self._accepted = accepted
        self._payload = {"intervals": dict(grouped), "accepted": accepted}
        return self._payload

    def accepted(self) -> list[str] | None:
        """The flat list of intervals this broker accepts, or None if unknown.

        Returns:
            The accepted values, or None when the lookup failed. The failure is
            swallowed on purpose: this is the validation path for a read-only
            tool, and refusing a history call because the intervals endpoint
            hiccuped is the worse failure. A real credential or broker problem
            surfaces on the history call itself a moment later.
        """
        if self._loaded:
            return self._accepted

        try:
            self.payload()
        except Exception:
            logger.exception(
                "Agent market tool could not read the broker's intervals; skipping the "
                "interval check for this run"
            )
            self._accepted = None
        return self._accepted


# ---------------------------------------------------------------------------
# The toolkit
# ---------------------------------------------------------------------------


class MarketToolkit(OpenAlgoToolkit):
    """Quotes, market depth, historical candles and the broker's intervals.

    Every tool is read-only, so none of them requires confirmation and none of
    them writes an audit row. They are offered on both surfaces and to a session
    that has not enabled trading, because reading a price changes nothing.
    """

    def __init__(self, context: Any) -> None:
        """Register the five market-data tools.

        The interval cache is assigned before ``super().__init__`` because agno
        introspects the bound methods the moment it receives them, and a method
        that reads an attribute the instance does not have yet would fail during
        registration rather than during a call.

        Args:
            context: The run's :class:`services.agent.tools.ToolContext`.
        """
        self._intervals = BrokerIntervals(
            lambda: self.service_call(intervals_service.get_intervals)
        )

        super().__init__(
            context,
            name="market",
            tools=[
                self.get_quote,
                self.get_quotes,
                self.get_depth,
                self.get_history,
                self.get_intervals,
            ],
        )

    # -- tools ---------------------------------------------------------------

    def get_quote(self, symbol: str, exchange: str) -> str:
        """Fetch the latest quote for one instrument.

        Use this for a single symbol. For several at once use ``get_quotes``,
        which is one broker call instead of many.

        Args:
            symbol: OpenAlgo symbol, in capitals, exactly as the instrument is
                listed. For example ``RELIANCE``, ``BANKNIFTY24APR24FUT`` or
                ``NIFTY28MAR2420800CE``.
            exchange: Exchange code the symbol is listed on. One of NSE, BSE
                (equity), NFO, BFO (futures and options), CDS, BCD (currency),
                MCX, NCDEX, NCO (commodity), CRYPTO, or the quote-only index
                codes NSE_INDEX, BSE_INDEX, MCX_INDEX and GLOBAL_INDEX. An index
                such as NIFTY or SENSEX is quoted on an index code, never on NSE
                or BSE.

        Returns:
            JSON carrying the last traded price, open, high, low, previous
            close, bid, ask and volume for the symbol, plus a note when the
            exchange had to be corrected to an index exchange.
        """
        symbol, exchange, notices = normalise_pair(symbol, exchange)
        response = self.service_call(quotes_service.get_quotes, symbol=symbol, exchange=exchange)

        payload: dict[str, Any] = {
            "symbol": symbol,
            "exchange": exchange,
            "quote": response.get("data") if isinstance(response, Mapping) else response,
        }
        self._note(payload, notices)
        return self._wrapped("get_quote", payload, symbol=symbol, exchange=exchange)

    def get_quotes(self, symbols: list[dict[str, str]]) -> str:
        """Fetch the latest quote for several instruments in one call.

        Prefer this over repeated ``get_quote`` calls: it is a single broker
        request, which is faster and far less likely to be rate limited.

        Args:
            symbols: The instruments to quote, as a list of objects each
                carrying a ``symbol`` and an ``exchange``, for example
                ``[{"symbol": "INFY", "exchange": "NSE"}, {"symbol": "NIFTY",
                "exchange": "NSE_INDEX"}]``. Both fields are required on every
                entry; the exchange is not inherited from the entry before it.
                At most 50 entries per call, so split a longer watchlist into
                batches. A plain ``"NSE:INFY"`` string is accepted in place of
                an object.

        Returns:
            JSON with one result per requested instrument, each carrying either
            its quote or the reason that instrument failed, so a bad symbol
            costs its own row rather than the whole call.
        """
        pairs, notices = self._pairs(symbols)
        response = self.service_call(quotes_service.get_multiquotes, symbols=pairs)

        results = response.get("results") if isinstance(response, Mapping) else None
        if not isinstance(results, list):
            results = [] if results is None else [results]
        total = len(results)

        def build(limit: int) -> dict[str, Any]:
            payload: dict[str, Any] = {
                "requested": len(pairs),
                "results_returned": min(limit, total),
                "results": results[:limit],
            }
            if total > limit:
                payload["results_omitted"] = total - limit
                payload["note"] = (
                    f"{total - limit} of {total} results were dropped to fit the reply. "
                    "Ask for fewer symbols per call to see them all."
                )
            self._note(payload, notices)
            return payload

        payload = fit_to_budget(build, total)
        return self._wrapped("get_quotes", payload, count=len(pairs))

    def get_depth(self, symbol: str, exchange: str) -> str:
        """Fetch the order book depth for one instrument.

        Depth is the resting bid and ask ladder, normally five levels a side,
        with the total buy and sell quantity behind them. Use it to judge
        liquidity and the spread before sizing an order. An index has no order
        book; quote it instead.

        Args:
            symbol: OpenAlgo symbol, in capitals, exactly as the instrument is
                listed. For example ``SBIN`` or ``NIFTY28MAR2420800CE``.
            exchange: Exchange code the symbol is listed on: NSE, BSE, NFO, BFO,
                CDS, BCD, MCX, NCDEX, NCO or CRYPTO. Depth on a quote-only index
                exchange is normally unavailable.

        Returns:
            JSON with the bid and ask ladders, total buy and sell quantity, the
            last traded price and the day's open, high, low and previous close.
        """
        symbol, exchange, notices = normalise_pair(symbol, exchange)
        response = self.service_call(depth_service.get_depth, symbol=symbol, exchange=exchange)

        payload: dict[str, Any] = {
            "symbol": symbol,
            "exchange": exchange,
            "depth": response.get("data") if isinstance(response, Mapping) else response,
        }
        self._note(payload, notices)
        return self._wrapped("get_depth", payload, symbol=symbol, exchange=exchange)

    def get_history(
        self,
        symbol: str,
        exchange: str,
        interval: str,
        start_date: str,
        end_date: str,
        source: str = "api",
    ) -> str:
        """Fetch historical candles for one instrument.

        The result is a summary of the whole range plus the most recent candles,
        not the whole frame: a minute interval over a month is tens of thousands
        of bars. The summary is computed over every candle in the range, so the
        high, the low and the volume are the real ones even when older candles
        were dropped, and the result says how many were dropped.

        Ask for the range you actually need. A question about a trend over three
        months wants a daily interval, not a one-minute one.

        Args:
            symbol: OpenAlgo symbol, in capitals, exactly as the instrument is
                listed. For example ``INFY``, ``NIFTY`` or
                ``BANKNIFTY24APR24FUT``.
            exchange: Exchange code the symbol is listed on: NSE, BSE, NFO, BFO,
                CDS, BCD, MCX, NCDEX, NCO, CRYPTO, or an index code such as
                NSE_INDEX or BSE_INDEX for an index.
            interval: Candle size. Call ``get_intervals`` for the ones this
                broker accepts; they are drawn from ``1s`` to ``45s`` for
                seconds, ``1m`` to ``30m`` for minutes, ``1h`` to ``4h`` for
                hours, and ``D``, ``W``, ``M`` for daily, weekly and monthly.
                Case matters: ``1m`` is one minute and ``M`` is one month.
            start_date: First day of the range, as ``YYYY-MM-DD``, for example
                ``2026-01-15``. Inclusive, and interpreted in IST.
            end_date: Last day of the range, as ``YYYY-MM-DD``. Inclusive, and
                interpreted in IST. It must not be before ``start_date``.
            source: Where the candles come from. ``api`` (the default) asks the
                broker, which is what you want for anything current. ``db``
                reads the local Historify store, which only holds what the
                operator has already downloaded and answers with a download
                instruction when it holds nothing for the request.

        Returns:
            JSON carrying ``summary`` (first open, last close, highest high,
            lowest low, total volume and the change across the range), the most
            recent candles in ``candles`` oldest first with IST timestamps, and
            ``rows_total`` and ``rows_omitted`` so the count is never guessed.
        """
        symbol, exchange, notices = normalise_pair(symbol, exchange)
        source = normalise_source(source)
        interval, interval_notice = normalise_interval(interval, source, self._intervals.accepted())
        if interval_notice:
            notices.append(interval_notice)
        start, end = normalise_range(start_date, end_date)

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
        if not isinstance(rows, list):
            rows = []
        records = [row for row in rows if isinstance(row, Mapping)]
        total = len(records)
        columns = candle_columns(records[0]) if records else {}
        summary = summarise_candles(records, columns)

        def build(limit: int) -> dict[str, Any]:
            tail = records[total - limit :] if limit else []
            payload: dict[str, Any] = {
                "symbol": symbol,
                "exchange": exchange,
                "interval": interval,
                "start_date": start,
                "end_date": end,
                "source": source,
                "timezone": "Asia/Kolkata",
                "rows_total": total,
                "rows_returned": len(tail),
                "rows_omitted": total - len(tail),
                "summary": summary,
                "candles": [_candle(row, columns) for row in tail],
            }
            if payload["rows_omitted"]:
                payload["note"] = (
                    f"{payload['rows_omitted']} older candles of {total} were omitted; "
                    f"'candles' holds the most recent {len(tail)}, oldest first. The summary "
                    "covers all of them. Narrow the dates or use a larger interval to see more."
                )
            elif not total:
                payload["note"] = (
                    "The range returned no candles. Check the dates against the trading "
                    "calendar and confirm the interval is one this broker supports."
                )
            self._note(payload, notices)
            return payload

        payload = fit_to_budget(build, min(total, MAX_HISTORY_ROWS))
        return self._wrapped(
            "get_history", payload, symbol=symbol, exchange=exchange, interval=interval
        )

    def get_intervals(self) -> str:
        """List the candle intervals the connected broker supports.

        Brokers differ: one offers seconds, another starts at one minute, and
        the hourly resolutions vary. Call this before ``get_history`` when you
        are unsure, and pass one of the returned values verbatim.

        Returns:
            JSON with the intervals grouped as seconds, minutes, hours, days,
            weeks and months, plus a flat ``accepted`` list of every value
            ``get_history`` will take.
        """
        payload = self._intervals.payload()
        if payload is None:
            # A fresh failure raises out of BrokerIntervals.payload. Reaching
            # here means either the service answered with a shape carrying no
            # intervals, or a history call earlier in this run already tried and
            # failed, in which case the recorded reason is the useful part of
            # the answer.
            payload = {
                "intervals": {},
                "accepted": [],
                "note": (
                    "The broker did not return a usable interval list. Try a common interval "
                    "such as 'D' or '5m' with get_history and report the error if it is "
                    "rejected."
                ),
            }
            if self._intervals.error:
                payload["error"] = self._intervals.error
        return self._wrapped("get_intervals", payload)

    # -- argument handling ---------------------------------------------------

    def _pairs(self, symbols: Any) -> tuple[list[dict[str, str]], list[str]]:
        """Normalise the ``symbols`` argument of :meth:`get_quotes`.

        Args:
            symbols: Whatever the model passed.

        Returns:
            The de-duplicated pairs to request, and any notices for the result.

        Raises:
            RetryAgentRun: If the argument is not a usable list of pairs.
        """
        return symbol_pairs(symbols, limit=MAX_MULTIQUOTE_SYMBOLS)

    # -- result shaping ------------------------------------------------------

    @staticmethod
    def _note(payload: dict[str, Any], notices: list[str]) -> None:
        """Attach any notices to a result payload.

        Args:
            payload: The payload being built.
            notices: Messages about corrections this tool made, which the model
                must be able to repeat to the operator.
        """
        if notices:
            payload["notices"] = list(notices)

    def _wrapped(self, tool: str, payload: Any, **labels: Any) -> str:
        """Serialise a result and label it as data before it re-enters context.

        Args:
            tool: The tool's registered name.
            payload: The result payload.
            **labels: Attributes for the opening tag, such as the symbol and
                exchange the result is about. Each is escaped.

        Returns:
            The ``<tool_result>`` block to return to the model.
        """
        return wrap_tool_result(tool, self.to_json(payload), **labels)
