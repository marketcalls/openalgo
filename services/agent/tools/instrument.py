"""The instrument card: one question, one answer, drawn from the broker session.

"How is RELIANCE doing" is the most common question anyone asks a trading
assistant, and answering it in prose wastes what this platform is. A general
assistant answering it has to end with a disclaimer of the form *use your broker
terminal for exact intraday levels and volume*. OpenAlgo **is** the broker
terminal, so this card carries exactly what that disclaimer is about, and one
thing no general assistant can ever carry: the operator's own position in the
instrument they just asked about.

One tool, :meth:`InstrumentToolkit.show_instrument`, emitting one new viz kind,
``instrument``.

There are no fundamentals here, and that is deliberate
------------------------------------------------------

**OpenAlgo has no fundamentals source.** There is no service, no table and no
feed anywhere in this repository that returns a price/earnings ratio, a market
capitalisation, an earnings per share figure, a dividend yield, a company
profile or an analyst estimate. A card that showed any of them would be showing
a number the model remembered, and a remembered number is indistinguishable, to
the reader, from one the broker returned. This card is going to look
authoritative, so every figure on it has to have come from a service call.

The rule for anyone extending this file: if you find yourself wanting a
fundamentals field, the field does not exist and the card is finished without
it. Do not add an empty tile, a dash, or a "not available" placeholder either.
An absent tile is honest; a tile saying nothing invites someone to fill it.

What is on the card, and where each part comes from
---------------------------------------------------

============================  ====================================
Section                       Service
============================  ====================================
Header, lot and tick          ``symbol_service.get_symbol_info``
Quote, and the day's move     ``quotes_service.get_quotes``
Intraday price and volume     ``history_service.get_history``
52 week high and low          ``history_service.get_history``
Order book, both sides        ``depth_service.get_depth``
The operator's own position   ``positionbook_service.get_positionbook``
============================  ====================================

Resilience matters more here than in the chart tools
-----------------------------------------------------

One call fans out to five services, and a card that renders nothing because the
52 week lookup timed out is worse than a card without a 52 week range. So:

* **The quote is the only hard requirement.** Without it there is no card, and
  the tool says so rather than drawing an empty one.
* **Every other section is optional.** Each is gathered inside its own guard;
  one that answers is put on the spec under its own key, and one that does not
  is named in ``unavailable`` with the reason. The renderer omits what is not
  there, which is the same rule the fundamentals paragraph above states: a
  section that could not be read is absent, never a placeholder.
* **A held position and a failed position lookup are different answers**, and
  the spec keeps them apart. ``position.held`` being false means the operator
  holds nothing; ``position`` being absent and ``unavailable.position`` being
  set means nobody knows. Getting that backwards would tell an operator they
  are flat while the broker holds their position.

The token rule
--------------

Like every rendering tool, the model gets one or two lines carrying the price
and the move, while the intraday series, the ladder and the position travel on
the frame. A card of four hundred bars costs the conversation a sentence.

Four helpers here are module level and public
----------------------------------------------

:func:`normalise_quote`, :func:`quote_move`, :func:`depth_levels` and
:func:`percent_change` each carry a rule rather than a convenience, and the
live subscription cards in ``services/agent/tools/live.py`` need every one of
them: a feed's zero is absence and not a measurement, a zero last traded price
is not a hundred percent fall, a padded ladder level is not a resting order,
and a percentage of zero is undefined rather than infinite. A second copy would
drift, and the copy in the path nobody is looking at is the one that goes wrong.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from agno.exceptions import RetryAgentRun

from services import depth_service, history_service, quotes_service, symbol_service
from services.agent.prompts import wrap_tool_result
from services.agent.tools.account import CURRENCY, current_mode, looks_flat
from services.agent.tools.base import (
    OpenAlgoToolkit,
    as_number,
    format_number,
    format_price,
    json_safe,
)
from services.agent.tools.market import (
    IST,
    BrokerIntervals,
    candle_columns,
    chart_bars,
    normalise_interval,
    normalise_pair,
    summarise_candles,
)
from services.agent.tools.options import normalise_int
from services.agent.tools.symbols import DERIVATIVE_EXCHANGES, INDEX_EXCHANGES
from services.agent.viz_sink import emit, no_sink_message, sink_of
from services.intervals_service import get_intervals
from services.positionbook_service import get_positionbook
from utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from services.agent.tools import ToolContext

logger = get_logger(__name__)

__all__ = [
    "INSTRUMENT_VIZ",
    "InstrumentToolkit",
    "depth_levels",
    "normalise_quote",
    "percent_change",
    "quote_move",
]

#: The renderer selector this toolkit emits. One kind, one branch in the
#: client's ``VizBlock``: that is the whole cost of adding a renderer.
INSTRUMENT_VIZ = "instrument"

#: Candle size for the intraday strip when the model does not name one. Five
#: minutes is what a broker terminal opens on: fine enough to show the shape of
#: the session, coarse enough that a full day is under eighty bars.
DEFAULT_INTRADAY_INTERVAL = "5m"

#: Trading sessions of intraday history the card carries when the model does not
#: ask for more.
DEFAULT_SESSIONS = 1

#: Most sessions one card may span. Past a week the intraday strip stops being
#: an intraday strip, and the daily chart tool is the right answer instead.
MAX_SESSIONS = 5

#: Most bars the intraday strip carries. Well past what fits across a card, and
#: it costs the conversation nothing because the bars never enter the model's
#: context; the cap is here so a five-session one-minute request cannot build a
#: frame measured in megabytes.
MAX_INSTRUMENT_BARS = 500

#: Calendar days of daily history read for the 52 week high and low. A little
#: over a year, so a full 52 weeks is covered even when the range starts on a
#: market holiday.
WEEK_52_LOOKBACK_DAYS = 372

#: Levels a side the order book carries. Indian exchanges publish five.
MAX_DEPTH_LEVELS = 5

#: Characters of a failure kept as the reason a section is missing. The reason
#: is shown under the card, not sent to the model, and a broker stack trace
#: rendered in full would bury the card it is explaining.
MAX_REASON_CHARS = 300

_TIMEZONE = "Asia/Kolkata"

_NO_SINK = no_sink_message("instrument card")


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def _session_date(epoch: Any) -> str:
    """Name the trading session one bar belongs to.

    Args:
        epoch: The bar's ``time``, UTC epoch seconds as
            :func:`services.agent.tools.market.chart_bars` produced it.

    Returns:
        The IST calendar date as ``YYYY-MM-DD``, or an empty string when the
        value is not a usable timestamp. The empty string groups the unusable
        bars together rather than scattering them across real sessions.
    """
    seconds = as_number(epoch)
    if seconds is None:
        return ""
    try:
        return datetime.fromtimestamp(seconds, IST).date().isoformat()
    except (OSError, OverflowError, ValueError):
        return ""


def _sessions_of(bars: Sequence[Mapping[str, Any]]) -> list[str]:
    """List the trading sessions a bar series spans, in order.

    Args:
        bars: The series, oldest first.

    Returns:
        The distinct IST session dates, oldest first. A bar carrying no usable
        timestamp contributes nothing rather than an empty date.
    """
    ordered: list[str] = []
    for bar in bars:
        day = _session_date(bar.get("time"))
        if day and (not ordered or ordered[-1] != day):
            ordered.append(day)
    return ordered


def _day_part(value: Any) -> str | None:
    """Take the calendar date out of an IST timestamp a summary rendered.

    Args:
        value: A value from
            :func:`services.agent.tools.market.summarise_candles`, normally an
            ISO-8601 string but passed through unchanged when the frame's
            timestamp was not a usable epoch.

    Returns:
        ``YYYY-MM-DD``, or None when the value is not an ISO timestamp.
    """
    if not isinstance(value, str) or len(value) < 10:
        return None
    head = value[:10]
    try:
        date.fromisoformat(head)
    except ValueError:
        return None
    return head


def _reason(exc: BaseException) -> str:
    """Render why one section of the card is missing.

    This reason is shown under the card, to a person, so it is trimmed to the
    first sentence. ``service_call`` raises a message written for the model,
    which ends in coaching about whether to call the tool again; that guidance
    is right where it lands and is noise under a card. The class name is added
    only for a failure that did not already come with its own wording.

    Args:
        exc: Whatever the section's gather raised.

    Returns:
        A short single-line reason, capped at :data:`MAX_REASON_CHARS`.
    """
    text = str(exc).replace("\n", " ").strip()
    if not isinstance(exc, RetryAgentRun):
        text = f"{type(exc).__name__}: {text}" if text else type(exc).__name__
    head, separator, _ = text.partition(". ")
    return (head + separator.strip())[:MAX_REASON_CHARS]


def depth_levels(raw: Any) -> list[dict[str, Any]]:
    """Normalise one side of the order book.

    A broker pads its ladder to a fixed depth with zero-price, zero-quantity
    entries. Those are padding rather than resting orders, so they are dropped:
    a card drawing five bars of nothing beside one real bid reads as a book that
    exists, which is the opposite of the truth.

    Args:
        raw: The ``bids`` or ``asks`` list the depth service returned.

    Returns:
        Up to :data:`MAX_DEPTH_LEVELS` levels, best first, each carrying a
        ``price`` and a ``quantity``.
    """
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []

    levels: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        price = as_number(entry.get("price"))
        quantity = as_number(entry.get("quantity"))
        if not price and not quantity:
            continue
        levels.append({"price": price, "quantity": quantity})
        if len(levels) >= MAX_DEPTH_LEVELS:
            break
    return levels


def percent_change(part: float | None, whole: float | None) -> float | None:
    """Express one number as a percentage of another.

    Args:
        part: The numerator.
        whole: The denominator.

    Returns:
        The percentage rounded to two places, or None when either input is
        missing or the denominator is zero. A percentage of zero is undefined
        rather than infinite, and reporting it as a number is how a card ends up
        claiming a hundred percent move that never happened.
    """
    if part is None or not whole:
        return None
    return round(part / whole * 100.0, 2)


def normalise_quote(raw: Any) -> dict[str, Any]:
    """Normalise the quote to the fields this platform actually returns.

    ``quotes_service`` returns exactly nine fields and that is the whole
    quote OpenAlgo has. Naming them here rather than passing the broker's
    payload through keeps a plugin's extra key from reaching the card as a
    tile nobody designed, and keeps the card's contract stable across
    brokers.

    A field that came back as exactly zero is dropped, because for every
    one of these except the last traded price zero is how a feed spells
    absence rather than a measurement: an index reports no traded volume and
    no open interest, and a closed book reports no bid. Rendering those as
    ``0.00`` is the same failure as a blank tile, only more confident. The
    last traded price is kept at zero, because there the caller has to be
    able to tell "nothing has printed" from "no quote came back at all", and
    it says so on the card rather than deriving a hundred percent fall.

    Args:
        raw: The service's ``data`` payload.

    Returns:
        The fields the broker supplied, as numbers.
    """
    source = raw if isinstance(raw, Mapping) else {}
    fields = ("ltp", "open", "high", "low", "prev_close", "volume", "bid", "ask", "oi")
    quote: dict[str, Any] = {}
    for field in fields:
        value = as_number(source.get(field))
        if value is None or (value == 0 and field != "ltp"):
            continue
        quote[field] = value
    return quote


def quote_move(quote: Mapping[str, Any], notices: list[str], *, symbol: str = "") -> dict[str, Any]:
    """Derive the day's move from the quote.

    Args:
        quote: The normalised quote.
        notices: Collected notices, appended to when the move cannot be
            stated.
        symbol: The instrument the quote belongs to. Named in the notice when
            given, because a card carrying several rows has to say which one
            has not printed; a card carrying one does not.

    Returns:
        ``change`` and ``change_percent`` when both are meaningful, an empty
        mapping otherwise.
    """
    ltp = as_number(quote.get("ltp"))
    previous = as_number(quote.get("prev_close"))
    if ltp is None or not previous:
        return {}
    if ltp == 0:
        # A last traded price of zero means nothing has printed yet, not a
        # hundred percent loss. The holdings mapping in the Zerodha plugin
        # learned the same lesson: report nothing rather than a fabricated
        # wipeout.
        subject = f"{symbol}'s last traded price" if symbol else "The last traded price"
        notices.append(
            f"{subject} is zero, so no trade has printed yet and the day's change is not stated."
        )
        return {}
    change = round(ltp - previous, 4)
    return {"change": change, "change_percent": percent_change(change, previous)}


# ---------------------------------------------------------------------------
# The toolkit
# ---------------------------------------------------------------------------


class InstrumentToolkit(OpenAlgoToolkit):
    """The instrument card, drawn from the operator's own broker session.

    Read-only, so no tool here requires confirmation and none writes an audit
    row. The single tool returns a short confirmation and leaves the card on the
    run's sink for ``services/agent/viz_sink.py`` to turn into a frame.
    """

    def __init__(self, context: ToolContext) -> None:
        """Register the instrument card tool.

        The sink and the interval cache are bound before ``super().__init__``
        because agno introspects the bound methods the moment it receives them,
        and a method reading an attribute the instance does not have yet would
        fail during registration rather than during a call.

        Args:
            context: The run's tool context. Its ``extras`` carry the sink the
                surface created for this run.
        """
        self._sink = sink_of(context)
        self._intervals = BrokerIntervals(lambda: self.service_call(get_intervals))

        super().__init__(context, name="instrument", tools=[self.show_instrument])

    # -- the tool ------------------------------------------------------------

    def show_instrument(
        self,
        symbol: str,
        exchange: str,
        interval: str = DEFAULT_INTRADAY_INTERVAL,
        days: int = DEFAULT_SESSIONS,
    ) -> str:
        """Show a full instrument card for one symbol in the conversation.

        Reach for this whenever the operator asks for a price, a quote, a last
        traded price, or how something is doing, trading or moving. It is the
        right answer to "what is RELIANCE at", "how is NIFTY doing today" and
        "give me a quote on SBIN". Prefer it over ``get_quote``, which is for
        when you need the number to reason with rather than to show.

        The card carries the last traded price and the move against the previous
        close, the day's open, high, low and volume, an intraday price and
        volume chart, the 52 week high and low, the top of the order book on
        both sides, and, when the operator holds this instrument, their own
        quantity, average price and unrealised profit or loss. Every figure is
        fetched here from the broker session, so none of it is yours to supply.

        It carries no fundamentals, because this platform has no source for
        them. There is no price/earnings ratio, market capitalisation, earnings
        per share or dividend yield anywhere in OpenAlgo. Do not add one from
        memory in your reply: a remembered figure sitting beside broker data
        reads as though the broker returned it.

        Args:
            symbol: OpenAlgo symbol, in capitals, exactly as the instrument is
                listed. Equity is the base symbol (``RELIANCE``, ``SBIN``). A
                future is ``[base][expiry]FUT`` (``BANKNIFTY24APR24FUT``). An
                option is ``[base][expiry][strike][CE or PE]``
                (``NIFTY28MAR2420800CE``). An index is its plain name
                (``NIFTY``, ``SENSEX``).
            exchange: Exchange code the symbol is listed on: NSE, BSE (equity),
                NFO, BFO (futures and options), CDS, BCD (currency), MCX, NCDEX,
                NCO (commodity), CRYPTO, or the quote-only index codes
                NSE_INDEX, BSE_INDEX, MCX_INDEX and GLOBAL_INDEX. An index such
                as NIFTY or SENSEX is quoted on an index code, never on NSE or
                BSE.
            interval: Candle size for the intraday chart on the card, defaulting
                to ``5m``. Call ``get_intervals`` for the ones this broker
                accepts. Case matters: ``1m`` is one minute and ``M`` is one
                month. Use ``1m`` only when the question is about the last few
                minutes.
            days: How many recent trading sessions the intraday chart spans,
                defaulting to 1, which is the latest session. At most 5. Ask for
                more only when the question is about the last few days; a longer
                range belongs on ``plot_price_chart`` with a daily interval.

        Returns:
            One or two lines carrying the price and the move. The chart, the
            ladder and the position travel to the operator's screen, not through
            this answer, so describe what the card shows rather than repeating
            its numbers.
        """
        symbol, exchange, notices = normalise_pair(symbol, exchange)
        sessions = normalise_int(days, "days", 1, MAX_SESSIONS)
        interval, interval_notice = normalise_interval(interval, "api", self._intervals.accepted())
        if interval_notice:
            notices.append(interval_notice)

        # The quote is the one hard requirement. A failure here raises out of
        # service_call with a message the model can act on, which is the plain
        # way of saying there is no card.
        response = self.service_call(quotes_service.get_quotes, symbol=symbol, exchange=exchange)
        raw_quote = response.get("data") if isinstance(response, Mapping) else response
        quote = normalise_quote(raw_quote)

        ltp = quote.get("ltp")
        if ltp is None:
            return self._answer(
                f"The quote for {symbol} on {exchange} came back with no last traded price, so "
                "no card was drawn. Say the price could not be read rather than reporting a "
                "number, and check the symbol is one this broker quotes.",
                symbol=symbol,
                exchange=exchange,
            )

        spec: dict[str, Any] = {
            "symbol": symbol,
            "exchange": exchange,
            "currency": CURRENCY,
            "mode": current_mode(self.analyzer_mode),
            "as_of": datetime.now(IST).isoformat(timespec="seconds"),
            "timezone": _TIMEZONE,
            "is_derivative": exchange in DERIVATIVE_EXCHANGES,
            "is_index": exchange in INDEX_EXCHANGES,
            "quote": quote,
        }
        spec.update(quote_move(quote, notices))

        unavailable: dict[str, str] = {}
        sources = ["quotes_service"]

        # Each section is gathered on its own, so one that fails costs itself
        # and nothing else, and the service that fed it is only claimed as a
        # source once it has actually answered.
        gathered = {
            "instrument": self._section(
                spec, unavailable, "instrument", lambda: self._master(symbol, exchange)
            ),
            "intraday": self._section(
                spec,
                unavailable,
                "intraday",
                lambda: self._intraday(symbol, exchange, interval, sessions),
            ),
            "week_52": self._section(
                spec, unavailable, "week_52", lambda: self._week_52(symbol, exchange, ltp)
            ),
            "depth": self._section(
                spec, unavailable, "depth", lambda: self._depth(symbol, exchange)
            ),
            "position": self._section(
                spec, unavailable, "position", lambda: self._position(symbol, exchange)
            ),
        }
        for section, service in (
            ("instrument", "symbol_service"),
            ("intraday", "history_service"),
            ("week_52", "history_service"),
            ("depth", "depth_service"),
            ("position", "positionbook_service"),
        ):
            if gathered[section] and service not in sources:
                sources.append(service)

        if unavailable:
            spec["unavailable"] = unavailable
        if notices:
            spec["notices"] = list(notices)

        drawn = emit(
            self._sink,
            tool="show_instrument",
            kind=INSTRUMENT_VIZ,
            spec=json_safe(spec),
            title=f"{symbol} {exchange}",
            source=", ".join(sources),
        )
        if not drawn:
            return self._answer(_NO_SINK, symbol=symbol, exchange=exchange)

        return self._answer(self._confirmation(spec, unavailable), symbol=symbol, exchange=exchange)

    # -- optional sections ---------------------------------------------------

    def _section(
        self,
        spec: dict[str, Any],
        unavailable: dict[str, str],
        name: str,
        gather: Any,
    ) -> bool:
        """Gather one optional section, recording why it is missing when it is.

        The single guard every optional part of the card goes through, so
        adding a section is one method plus one call rather than another copy of
        this try block. A section that raises costs itself and nothing else:
        the card still renders, and the reason is shown under it.

        Args:
            spec: The card being built. The section is added under ``name``.
            unavailable: Reasons, keyed by section name.
            name: The section's key in the spec.
            gather: Callable returning ``(section, reason)``. A section of None
                means there was nothing to show, and the reason says why.

        Returns:
            True when the section was gathered and added.
        """
        try:
            section, reason = gather()
        except Exception as exc:
            logger.exception("Instrument card: the %s section failed for the card", name)
            unavailable[name] = _reason(exc)
            return False

        if section is None:
            unavailable[name] = reason or "the platform returned nothing for this section"
            return False

        spec[name] = section
        return True

    def _master(self, symbol: str, exchange: str) -> tuple[dict[str, Any] | None, str | None]:
        """Read the contract's own details from the instrument master.

        Args:
            symbol: The OpenAlgo symbol.
            exchange: The exchange it is listed on.

        Returns:
            The header fields and the trading increments, or None and a reason.
        """
        payload = self.service_call(
            symbol_service.get_symbol_info, symbol=symbol, exchange=exchange
        )
        info = payload.get("data") if isinstance(payload, Mapping) else None
        if not isinstance(info, Mapping) or not info:
            return None, "the instrument master holds no row for this symbol"

        section: dict[str, Any] = {}
        for key, field in (
            ("name", "name"),
            ("instrumenttype", "instrument_type"),
            ("expiry", "expiry"),
        ):
            value = info.get(key)
            if isinstance(value, str) and value.strip():
                section[field] = value.strip()

        # A zero strike, lot size or tick is the master's way of saying the
        # field does not apply to this instrument, so it is dropped rather than
        # rendered as a tile reading nought. ``freeze_qty`` is deliberately not
        # carried: it is an order-placement ceiling rather than anything about
        # the price, and on a cash symbol it is not even meaningful.
        for key, field in (
            ("strike", "strike"),
            ("lotsize", "lot_size"),
            ("tick_size", "tick_size"),
        ):
            value = as_number(info.get(key))
            if not value:
                continue
            section[field] = int(value) if field == "lot_size" and value.is_integer() else value
        return (section or None), "the instrument master row carried no usable detail"

    def _intraday(
        self, symbol: str, exchange: str, interval: str, sessions: int
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Fetch the intraday price and volume series for the card's chart.

        A fixed window of calendar days is asked for and the most recent trading
        sessions are taken out of what came back, rather than asking for today
        and getting nothing on a weekend, a holiday, or before the first bar of
        the session has printed.

        Args:
            symbol: The OpenAlgo symbol.
            exchange: The exchange it is listed on.
            interval: The candle size, already checked against the broker.
            sessions: How many recent trading sessions to keep.

        Returns:
            The series and the sessions it spans, or None and a reason.
        """
        today = datetime.now(IST).date()
        start = today - timedelta(days=max(7, sessions * 4))
        response = self.service_call(
            history_service.get_history,
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_date=start.isoformat(),
            end_date=today.isoformat(),
            source="api",
        )

        rows = response.get("data") if isinstance(response, Mapping) else response
        records = (
            [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []
        )
        bars = chart_bars(records, candle_columns(records[0]) if records else {})
        if not bars:
            return None, (
                f"the broker returned no {interval} candles between {start.isoformat()} and "
                f"{today.isoformat()}"
            )

        ordered = _sessions_of(bars)
        kept = set(ordered[-sessions:])
        selected = [bar for bar in bars if _session_date(bar["time"]) in kept] if kept else bars

        omitted = max(0, len(selected) - MAX_INSTRUMENT_BARS)
        if omitted:
            selected = selected[-MAX_INSTRUMENT_BARS:]

        section: dict[str, Any] = {
            "interval": interval,
            # Listed from the bars that survived the cap, not from the ones that
            # were asked for. A one-minute five-session request is trimmed to
            # the most recent bars, and naming five sessions over a strip that
            # covers two would have the renderer label the chart with days it
            # is not drawing.
            "sessions": _sessions_of(selected),
            "bar_count": len(selected),
            "bars": selected,
            "first_time": selected[0]["time"],
            "last_time": selected[-1]["time"],
            # An index publishes no traded volume, and a strip of zero-height
            # volume bars reads as a real absence of trading rather than as a
            # measure that does not apply. The renderer drops the pane instead.
            "has_volume": any(bar.get("volume") for bar in selected),
        }
        if omitted:
            section["bars_omitted"] = omitted
        return section, None

    def _week_52(
        self, symbol: str, exchange: str, ltp: float
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Fetch the 52 week high and low, and where the price sits between them.

        Args:
            symbol: The OpenAlgo symbol.
            exchange: The exchange it is listed on.
            ltp: The last traded price, for the position within the range.

        Returns:
            The range, or None and a reason.
        """
        today = datetime.now(IST).date()
        start = today - timedelta(days=WEEK_52_LOOKBACK_DAYS)
        interval, _ = normalise_interval("D", "api", self._intervals.accepted())

        response = self.service_call(
            history_service.get_history,
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_date=start.isoformat(),
            end_date=today.isoformat(),
            source="api",
        )

        rows = response.get("data") if isinstance(response, Mapping) else response
        records = (
            [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []
        )
        summary = summarise_candles(records, candle_columns(records[0]) if records else {})

        high = as_number(summary.get("highest_high"))
        low = as_number(summary.get("lowest_low"))
        if high is None or low is None:
            return None, (
                f"the broker returned no daily candles between {start.isoformat()} and "
                f"{today.isoformat()}"
            )

        first_date = _day_part(summary.get("first_timestamp"))
        last_date = _day_part(summary.get("last_timestamp"))

        section: dict[str, Any] = {
            "high": high,
            "low": low,
            "start_date": start.isoformat(),
            "end_date": today.isoformat(),
            "bar_count": len(records),
            # A weekly option listed a month ago has a high and a low, and they
            # are not a 52 week high and low. The window that was asked for is
            # always 52 weeks; this says whether the instrument was listed for
            # enough of it to deserve the label, so a card can say "since
            # 2026-07-24" rather than claiming a year of history it never had.
            "full_year": bool(
                first_date and date.fromisoformat(first_date) <= today - timedelta(days=330)
            ),
        }
        for field, value in (
            ("first_date", first_date),
            ("last_date", last_date),
            ("high_date", _day_part(summary.get("highest_high_timestamp"))),
            ("low_date", _day_part(summary.get("lowest_low_timestamp"))),
            ("position_percent", percent_change(ltp - low, high - low)),
            ("from_high_percent", percent_change(ltp - high, high)),
            ("from_low_percent", percent_change(ltp - low, low)),
        ):
            if value is not None:
                section[field] = value
        return section, None

    def _depth(self, symbol: str, exchange: str) -> tuple[dict[str, Any] | None, str | None]:
        """Fetch the resting order book, both sides.

        Args:
            symbol: The OpenAlgo symbol.
            exchange: The exchange it is listed on.

        Returns:
            The ladders and the spread, or None and a reason.
        """
        response = self.service_call(depth_service.get_depth, symbol=symbol, exchange=exchange)
        data = response.get("data") if isinstance(response, Mapping) else response
        if not isinstance(data, Mapping):
            return None, "the broker returned no order book for this instrument"

        bids = depth_levels(data.get("bids"))
        asks = depth_levels(data.get("asks"))
        if not bids and not asks:
            return None, "there are no resting orders on either side"

        section: dict[str, Any] = {"bids": bids, "asks": asks}
        for field, value in (
            ("total_buy_quantity", as_number(data.get("totalbuyqty"))),
            ("total_sell_quantity", as_number(data.get("totalsellqty"))),
        ):
            if value is not None:
                section[field] = value

        best_bid = bids[0]["price"] if bids else None
        best_ask = asks[0]["price"] if asks else None
        if best_bid and best_ask and best_ask > best_bid:
            spread = round(best_ask - best_bid, 4)
            section["spread"] = spread
            spread_percent = percent_change(spread, (best_ask + best_bid) / 2.0)
            if spread_percent is not None:
                section["spread_percent"] = spread_percent
        return section, None

    def _position(self, symbol: str, exchange: str) -> tuple[dict[str, Any] | None, str | None]:
        """Find what the operator holds in this exact instrument.

        This is the one part of the card no general assistant can ever carry, so
        it has to be right or absent. Three rules make that true:

        * The whole position book is read and matched here rather than asking
          the open-position service, because that service takes a product and
          the same symbol held as ``MIS`` and as ``NRML`` is two positions. A
          card that asked for one product would report a holding of zero on a
          symbol the operator is holding.
        * A row whose quantity reads as zero is a position opened and closed
          again today, not a position, so it is dropped.
        * An aggregate is only stated when every leg supplied the figure it is
          built from. A partial sum presented as the total is a wrong number
          with a confident presentation.

        Args:
            symbol: The OpenAlgo symbol.
            exchange: The exchange it is listed on.

        Returns:
            The position, ``{"held": False}`` when the operator holds nothing,
            or None and a reason when the book could not be read. Holding
            nothing and not knowing are different answers and the caller keeps
            them apart.
        """
        payload = self.service_call(get_positionbook)
        data = payload.get("data") if isinstance(payload, Mapping) else payload
        if not isinstance(data, list):
            return None, "the broker returned the position book in an unrecognised shape"

        legs: list[dict[str, Any]] = []
        for row in data:
            if not isinstance(row, Mapping):
                continue
            if str(row.get("symbol") or "").strip().upper() != symbol:
                continue
            if str(row.get("exchange") or "").strip().upper() != exchange:
                continue
            if looks_flat(row.get("quantity")):
                continue
            leg: dict[str, Any] = {}
            product = row.get("product")
            if isinstance(product, str) and product.strip():
                leg["product"] = product.strip().upper()
            for key, field in (
                ("quantity", "quantity"),
                ("average_price", "average_price"),
                ("ltp", "ltp"),
                ("pnl", "pnl"),
            ):
                value = as_number(row.get(key))
                if value is not None:
                    leg[field] = value
            legs.append(leg)

        if not legs:
            return {"held": False}, None

        section: dict[str, Any] = {"held": True, "legs": legs}

        quantities = [leg.get("quantity") for leg in legs]
        if all(value is not None for value in quantities):
            quantity = sum(quantities)
            section["quantity"] = quantity
            if quantity:
                section["side"] = "long" if quantity > 0 else "short"

        pnls = [leg.get("pnl") for leg in legs]
        if all(value is not None for value in pnls):
            section["pnl"] = round(sum(pnls), 2)

        # An average price across two products is only meaningful if both legs
        # are on the same side, and the card has no room to explain when it is
        # not. One leg is the ordinary case and the only one it is stated for.
        if len(legs) == 1:
            average = legs[0].get("average_price")
            if average is not None:
                section["average_price"] = average
            pnl = section.get("pnl")
            quantity = section.get("quantity")
            if pnl is not None and average and quantity:
                percent = percent_change(pnl, abs(quantity) * average)
                if percent is not None:
                    section["pnl_percent"] = percent
        return section, None

    # -- the answer ----------------------------------------------------------

    @staticmethod
    def _confirmation(spec: Mapping[str, Any], unavailable: Mapping[str, str]) -> str:
        """Compose the one or two lines the model receives.

        Args:
            spec: The card that was drawn.
            unavailable: Sections that could not be gathered.

        Returns:
            The confirmation. It carries the price and the move and nothing the
            operator can already see, because the card is on their screen and a
            second rendering of it in prose is the failure this tier exists to
            prevent.
        """
        quote = spec.get("quote", {})
        symbol = spec["symbol"]
        exchange = spec["exchange"]

        change = as_number(spec.get("change"))
        percent = as_number(spec.get("change_percent"))
        if change is None or percent is None:
            move = "with no stated change against the previous close"
        else:
            direction = "up" if change > 0 else "down" if change < 0 else "unchanged at"
            move = (
                f"{direction} {format_price(abs(change))} ({abs(percent):.2f} percent) "
                f"from the previous close of {format_price(quote.get('prev_close'))}"
            )

        parts = [
            f"{symbol} on {exchange} is {format_price(quote.get('ltp'))}, {move}. "
            f"Day {format_price(quote.get('low'))} to {format_price(quote.get('high'))}."
        ]

        position = spec.get("position")
        if isinstance(position, Mapping) and position.get("held"):
            side = position.get("side") or "holding"
            quantity = as_number(position.get("quantity"))
            size = format_number(abs(quantity)) if quantity is not None else "an unstated quantity"
            average = position.get("average_price")
            at = f" at {format_price(average)}" if average is not None else ""
            pnl = position.get("pnl")
            profit = f", unrealised P and L {format_price(pnl)}" if pnl is not None else ""
            parts.append(f"The operator is {side} {size}{at}{profit}.")

        if spec.get("mode") == "analyze":
            parts.append("Analyzer mode is on, so the position is a sandbox one; say so.")

        if unavailable:
            parts.append(f"Not on the card: {', '.join(sorted(unavailable))}.")

        parts.append(
            "The card is on the operator's screen with the intraday chart, the 52 week range "
            "and the order book, so describe what it shows rather than listing its numbers. "
            "It carries no fundamentals because this platform has none; do not add any."
        )
        return " ".join(parts)

    def _answer(self, message: str, **labels: Any) -> str:
        """Wrap the confirmation the model receives.

        Labelled as data like every other tool result, so nothing a symbol name
        or a broker message carries can read as an instruction.

        Args:
            message: The confirmation, one or two lines.
            **labels: Attributes for the opening tag.

        Returns:
            The ``<tool_result>`` block.
        """
        clean = {name: value for name, value in labels.items() if value is not None}
        return wrap_tool_result("show_instrument", message, **clean)
