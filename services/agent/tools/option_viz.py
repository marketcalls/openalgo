"""Derived option analytics: a combined premium series, and a payoff diagram.

Two read-only tools. Both draw something the platform has no single service for,
and both obey the same rule as every other rendering tool here: **the model
supplies the selection, never a number.** Which instrument, which side, how
many, is the model's to say. Every price, strike, lot size, spot, premium and
expiry on the chart is fetched here from ``services/*``, and a leg that cannot
be resolved against the symbol master is refused rather than guessed.

Why these two are not in :mod:`services.agent.tools.viz`
--------------------------------------------------------

The four tools there each take one service's answer and turn it into a figure.
These two do not have a service to take an answer from. A combined premium is
several history frames aligned against each other, and a payoff is a leg list
resolved across four services and then drawn by arithmetic that lives in the
browser. Both are assembly, not presentation, and that is a different job.

Tool one: the combined premium, and the two series it can mean
--------------------------------------------------------------

Ask a trader to "chart the straddle" and there are two different answers. They
diverge the moment spot moves, and confusing them is expensive:

* **Rolling ATM.** For every candle the ATM strike is recomputed from the
  underlying close and *that* straddle is priced, so the strike follows spot.
  This is what a straddle chart on ``/straddlechart`` shows, and
  ``services/straddle_chart_service.py`` already computes it. It is reused
  wholesale; there is no second ATM roll in this file.
* **Fixed legs.** The contracts the operator named, summed, with the strikes
  held constant. As spot moves away, this is a directional position; the
  rolling series is not.

Which one is drawn is decided by whether the operator named contracts, so the
tool needs no mode argument: ``legs`` present means fixed, ``legs`` absent means
rolling ATM around an underlying. The card says which it is, in the heading and
in a line under it, because a reader who mistakes one for the other reads a
delta that is not there.

**A combined series is built from closes and drawn as a line.** It is not
candles, and summing OHLC across legs is the mistake the obvious implementation
makes: a straddle's combined high is not the call's high plus the put's high.
The legs are anti-correlated, so their highs happen at different moments inside
the same bar, and adding them invents a peak that never traded. A candle chart
built that way is a lie with a nice shape.

**The legs are inner-joined on the timestamp and the drop is reported.** An
illiquid leg that printed no candle in a five minute window would otherwise
shorten the series silently, and a shortened series reads as a trend.

Tool two: the payoff, which this file does not compute
------------------------------------------------------

``frontend/src/lib/strategyMath.ts`` already computes payoff curves, and
``/strategybuilder`` draws them with ``PayoffChart``. A Python copy would drift,
and the copy in the chat is the one nobody notices is wrong. This is the same
reasoning ``CLAUDE.md`` gives for ``services/risk/``, and it applies with more
force here because the two would be read side by side.

So this tool **resolves legs and emits them**, in the exact shape
``StrategyLeg`` declares, and the client computes and draws. Every field comes
from a service:

===================  ==================================================
Field                Source
===================  ==================================================
``symbol``           the operator's selection, or ``positionbook_service``
``exchange``         ``symbol_service.get_symbol_info`` (the master row)
``segment``          the OpenAlgo symbol's own suffix, confirmed by the master
``side``             the operator's selection, or the sign of the held quantity
``lots``             the operator's selection, or held quantity / lot size
``lotSize``          ``symbol_service.get_symbol_info``
``expiry``           the ``DDMMMYY`` segment of the symbol
``expiryTs``         ``option_greeks_service.parse_option_symbol``
``strike``           ``symbol_service.get_symbol_info``
``optionType``       ``symbol_service.get_symbol_info``
``price``            ``quotes_service.get_multiquotes``, or the position's
                     own average price
``marketPrice``      ``quotes_service.get_multiquotes``
``iv``               ``option_greeks_service.calculate_greeks``
``tickSize``         ``symbol_service.get_symbol_info``
``contractValid``    true only when the master row was found
``referenceUnderlying``  ``quotes_service.get_multiquotes``
``forwardPrice``     ``synthetic_future_service.calculate_synthetic_future``
===================  ==================================================

**Cash equity is not on the curve, and the tool says so out loud.** A
``StrategyLeg`` is an option or a future, so shares held against a short call
cannot be modelled as a leg. Dropping them quietly would draw a naked short
call where a covered call is held, which understates the risk, so an excluded
cash position in the same underlying is named in the card, in the notices and
in the sentence the model gets back.

The token rule
--------------

Both tools return one or two lines. The series, the legs and the spot travel to
the client on the frame through ``services/agent/viz_sink.py``, so charting a
whole session of a straddle costs the conversation a sentence.

The signed-leg vocabulary is module level and public
-----------------------------------------------------

A combination of instruments is described here in exactly one way: a list of
legs, each carrying a side and a number of lots, whose contribution is
``signed_multiplier(side, lots)``. The live combination card in
``services/agent/tools/live.py`` describes a straddle, a spread and a ratio the
same way, so :func:`leg_entries`, :func:`leg_symbol`, :func:`leg_side`,
:func:`leg_lots`, :func:`signed_multiplier` and :func:`leg_label`, along with
the three resolvers :func:`resolve_underlying_exchange`, :func:`resolve_expiry`
and :func:`resolve_contract`, are plain module-level functions rather than
methods. The three resolvers take the caller's ``service_call`` as their first
argument, which is the whole reason they need no toolkit. A second vocabulary
for the same idea is how a sold leg ends up added in one card and subtracted in
another.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any

import pytz

from services import history_service, quotes_service, symbol_service
from services.agent.tools.account import CURRENCY, current_mode, looks_flat
from services.agent.tools.base import (
    OpenAlgoToolkit,
    as_number,
    format_number,
    format_price,
    invalid_argument,
    json_safe,
)
from services.agent.tools.market import (
    IST,
    BrokerIntervals,
    candle_columns,
    chart_bars,
    is_listed,
    normalise_interval,
)
from services.agent.tools.options import normalise_expiry, normalise_int, normalise_symbol
from services.agent.tools.symbols import DERIVATIVE_EXCHANGES, symbol_expiry
from services.agent.tools.viz import CALL_COLOUR, PUT_COLOUR, plotly_spec, tool_answer
from services.agent.viz_sink import emit, no_sink_message, sink_of
from services.expiry_service import get_expiry_dates
from services.intervals_service import get_intervals
from services.option_greeks_service import (
    calculate_greeks,
    get_underlying_exchange,
    parse_option_symbol,
)
from services.option_symbol_service import get_option_exchange
from services.positionbook_service import get_positionbook
from services.straddle_chart_service import get_straddle_chart_data
from services.strategy_chart_service import _cap_last_n_trading_dates, _resolve_trading_window
from services.synthetic_future_service import calculate_synthetic_future
from utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from services.agent.tools import ToolContext

logger = get_logger(__name__)

__all__ = [
    "MAX_LEGS",
    "PAYOFF_VIZ",
    "OptionVizToolkit",
    "leg_entries",
    "leg_label",
    "leg_lots",
    "leg_side",
    "leg_symbol",
    "listed_expiries",
    "resolve_contract",
    "resolve_expiry",
    "resolve_underlying_exchange",
    "signed_multiplier",
]

#: The renderer selector the payoff tool emits. One kind, one branch in the
#: client's ``VizBlock``: that is the whole cost of adding a renderer. The
#: premium series needs no new kind at all, because a line chart is what the
#: existing ``plotly`` renderer already draws.
PAYOFF_VIZ = "payoff"

#: Candle size for a premium series when the model does not name one. Five
#: minutes is what a straddle chart opens on: fine enough to show the shape of
#: the session, coarse enough that a full day is under eighty points.
DEFAULT_PREMIUM_INTERVAL = "5m"

#: Trading sessions a premium series spans when the model does not ask for more.
DEFAULT_PREMIUM_DAYS = 1

#: Most sessions one premium series may span. Each session multiplies the number
#: of history frames the rolling series fetches, because the ATM strike moves.
MAX_PREMIUM_DAYS = 5

#: Most legs one combined premium or one payoff may carry. A structure wider
#: than this is not read off a chart in a conversation.
MAX_LEGS = 8

#: Most points one premium series carries. Well past a readable chart, and it
#: costs the conversation nothing because the series never enters the model's
#: context; the cap is here so a five-session one-minute request cannot build a
#: frame measured in megabytes.
MAX_PREMIUM_POINTS = 2500

#: Exchanges a leg of either tool may be listed on. Both tools deal in
#: derivatives, so a cash or index code is refused with the derivatives venue
#: named rather than being looked up and found.
LEG_EXCHANGES: tuple[str, ...] = DERIVATIVE_EXCHANGES

#: Exchanges searched, in order, when the operator named a contract but not its
#: exchange. Resolution is against the symbol master, never against the spelling
#: of the symbol, and a contract that resolves nowhere is refused.
_LEG_SEARCH_ORDER: tuple[str, ...] = ("NFO", "BFO", "MCX", "CDS", "BCD", "NCDEX", "NCO", "CRYPTO")

#: Exchanges searched, in order, when the operator named an underlying but not
#: its exchange. Index feeds come first because an index straddle is the common
#: question and ``NIFTY`` resolves on ``NSE_INDEX`` rather than on ``NSE``.
_UNDERLYING_SEARCH_ORDER: tuple[str, ...] = ("NSE_INDEX", "BSE_INDEX", "NSE", "BSE", "MCX", "CDS")

#: The combined series line. Deliberately neither the call nor the put colour:
#: it is the thing being charted and the legs are context beneath it.
_COMBINED_COLOUR = "#0ea5e9"

#: A leg colour when the leg is neither a call nor a put, for example a future.
_OTHER_LEG_COLOUR = "#a855f7"

#: An OpenAlgo option symbol, whose last two characters name the right.
_OPTION_SUFFIX = re.compile(r"(CE|PE)\Z")

#: An OpenAlgo futures symbol.
_FUTURE_SUFFIX = re.compile(r"FUT\Z")

#: The ``DDMMMYY`` segment every OpenAlgo derivative symbol carries.
_EMBEDDED_EXPIRY = re.compile(r"\d{2}[A-Z]{3}\d{2}")

#: ``23850CE`` and ``23850.5PE``: a strike and a right with no underlying and no
#: expiry in front of them, which is how a model spells a leg once it has
#: already named the underlying and the expiry on the call.
_SHORTHAND_LEG = re.compile(r"\A(\d+(?:\.\d+)?)(CE|PE)\Z")

#: ``NFO:NIFTY08SEP2623850CE``, the exchange-qualified spelling.
_QUALIFIED_LEG = re.compile(r"\A([A-Z_]{2,12}):(.+)\Z")

_BUY = "BUY"
_SELL = "SELL"
_SEGMENT_OPTION = "OPTION"
_SEGMENT_FUTURE = "FUTURE"

_NO_SINK_CHART = no_sink_message("chart")
_NO_SINK_PAYOFF = no_sink_message("payoff diagram")

#: The window helpers in ``strategy_chart_service`` take a pytz zone, which is
#: what ``straddle_chart_service`` hands them, so the fixed-leg series is framed
#: by exactly the same calendar as the rolling one.
_IST_PYTZ = pytz.timezone("Asia/Kolkata")

#: Legs named in a chart heading before it stops being a heading.
_MAX_HEADING_LEGS = 3


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def _ist_label(epoch: Any) -> str | None:
    """Render a UTC epoch second as the ISO instant a Plotly date axis reads.

    Args:
        epoch: UTC epoch seconds, as every series in this file carries them.

    Returns:
        The instant in IST, to the second, or None when the value is not a
        timestamp, in which case the point is dropped rather than placed at the
        epoch.
    """
    moment = as_number(epoch)
    if moment is None:
        return None
    return datetime.fromtimestamp(moment, IST).isoformat(timespec="seconds")


def leg_entries(value: Any, field: str) -> list[Any]:
    """Normalise a list argument a model may have sent as text.

    Args:
        value: Whatever the model passed. A list, a single object, a JSON string
            of a list, or a comma or newline separated string.
        field: Argument name, used in the failure message.

    Returns:
        The entries, in the order given. Empty when nothing was passed, which
        both tools read as a meaningful choice rather than as an error.

    Raises:
        RetryAgentRun: If the argument is not a list at all, or carries more
            entries than one chart can hold.
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
                    field,
                    "it is a string that is not valid JSON",
                    'Pass a list, for example ["NIFTY08SEP2623850CE", "NIFTY08SEP2623850PE"].',
                )
        else:
            raw = [part.strip() for part in re.split(r"[,\n]", text) if part.strip()]
    if isinstance(raw, Mapping):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        invalid_argument(
            field,
            f"it is {type(raw).__name__}, not a list",
            'Pass a list, for example ["NIFTY08SEP2623850CE", "NIFTY08SEP2623850PE"].',
        )
    if len(raw) > MAX_LEGS:
        invalid_argument(
            field,
            f"it carries {len(raw)} legs, more than the {MAX_LEGS} one chart shows",
            "Chart the legs that answer the question; a wider structure is unreadable here.",
        )
    return list(raw)


def leg_side(value: Any, position: int) -> str:
    """Normalise a leg's side.

    Args:
        value: The model's value, or None for the default.
        position: The leg's place in the list, named in the failure message.

    Returns:
        ``BUY`` or ``SELL``. A leg that says nothing is bought, because a
        premium series of contracts the operator named is a long structure
        unless they said otherwise.

    Raises:
        RetryAgentRun: For anything that is not a side.
    """
    text = "" if value is None else str(value).strip().upper()
    if not text:
        return _BUY
    if text in (_BUY, "B", "LONG", "+"):
        return _BUY
    if text in (_SELL, "S", "SHORT", "-"):
        return _SELL
    invalid_argument(
        "legs",
        f"leg {position} names side {text!r}, which is not a side",
        "Use 'BUY' for a long leg or 'SELL' for a short one.",
    )


def leg_lots(value: Any, position: int) -> int:
    """Normalise a leg's lot count.

    Args:
        value: The model's value, or None for the default.
        position: The leg's place in the list, named in the failure message.

    Returns:
        A whole number of lots, defaulting to one.

    Raises:
        RetryAgentRun: For a value that is not a whole number between 1 and 100.
    """
    if value is None or value == "":
        return 1
    return normalise_int(value, f"legs (leg {position} lots)", 1, 100)


def leg_symbol(entry: Any, position: int, underlying: str, expiry: str) -> tuple[str, str]:
    """Read the symbol and the exchange one leg entry names.

    Three spellings are accepted, because a model reaches for all three: the
    bare OpenAlgo symbol, the exchange-qualified ``NFO:SYMBOL``, and the
    strike-and-right shorthand ``23850CE``, which is only meaningful when the
    call already named an underlying and an expiry.

    Args:
        entry: One entry of the ``legs`` argument, a string or a mapping.
        position: Its place in the list, named in failure messages.
        underlying: The call's underlying, used to expand the shorthand.
        expiry: The call's expiry in ``DDMMMYY``, used to expand the shorthand.

    Returns:
        The symbol, upper-cased, and the exchange, which is an empty string when
        the entry did not name one.

    Raises:
        RetryAgentRun: If the entry names no usable contract.
    """
    exchange = ""
    if isinstance(entry, Mapping):
        lowered = {str(key).strip().lower(): value for key, value in entry.items()}
        symbol = str(lowered.get("symbol") or lowered.get("tradingsymbol") or "").strip().upper()
        exchange = str(lowered.get("exchange") or "").strip().upper()
    elif isinstance(entry, str):
        symbol = entry.strip().upper()
    else:
        invalid_argument(
            "legs",
            f"leg {position} is {type(entry).__name__}, not a contract",
            'Pass strings such as "NIFTY08SEP2623850CE", or objects such as '
            '{"symbol": "NIFTY08SEP2623850CE", "exchange": "NFO", "side": "SELL", "lots": 1}.',
        )

    qualified = _QUALIFIED_LEG.match(symbol)
    if qualified:
        exchange = exchange or qualified.group(1)
        symbol = qualified.group(2).strip()

    shorthand = _SHORTHAND_LEG.match(symbol)
    if shorthand:
        if not underlying or not expiry:
            invalid_argument(
                "legs",
                f"leg {position} is {symbol!r}, which is a strike and a right with no contract "
                "in front of it",
                "Either pass the whole OpenAlgo symbol, such as 'NIFTY08SEP2623850CE', or set "
                "underlying and expiry_date on this call so the shorthand can be expanded.",
            )
        strike = shorthand.group(1)
        if "." in strike:
            strike = strike.rstrip("0").rstrip(".")
        symbol = f"{underlying}{expiry}{strike}{shorthand.group(2)}"

    if not symbol:
        invalid_argument(
            "legs",
            f"leg {position} names no symbol",
            "Pass the OpenAlgo symbol of each contract, for example 'NIFTY08SEP2623850CE'.",
        )
    return symbol, exchange


def _resolve_leg_exchange(symbol: str, exchange: str, where: str) -> str:
    """Settle which exchange a leg is listed on, against the symbol master.

    A leg the operator did not qualify is looked up rather than assumed: the
    master is asked for the pair on each derivatives exchange in turn and the
    first that resolves wins. A contract that resolves nowhere is refused, which
    is the whole point: a payoff or a premium series drawn from a symbol that
    does not exist is worse than no chart.

    Args:
        symbol: The OpenAlgo symbol.
        exchange: The exchange the entry named, or an empty string.
        where: How to name this leg in a failure message, for example ``leg 2``.

    Returns:
        The exchange code the master holds this contract on.

    Raises:
        RetryAgentRun: If the pair is not listed, or the named exchange lists no
            derivatives.
    """
    if exchange:
        if exchange not in LEG_EXCHANGES:
            invalid_argument(
                "legs",
                f"{where} names exchange {exchange!r}, which lists no futures or options",
                f"Use one of: {', '.join(LEG_EXCHANGES)}. An index code such as NSE_INDEX is a "
                "quote-only feed and carries no contract.",
            )
        if not is_listed(symbol, exchange):
            invalid_argument(
                "legs",
                f"{where}, {symbol} on {exchange}, is not in the instrument master",
                "Resolve the contract first with get_option_symbol or search_symbols, and pass "
                "the symbol it returns. Do not adjust a strike or an expiry to make one fit.",
            )
        return exchange

    for candidate in _LEG_SEARCH_ORDER:
        if is_listed(symbol, candidate):
            return candidate

    invalid_argument(
        "legs",
        f"{where}, {symbol}, is not listed on any derivatives exchange",
        "Resolve the contract first with get_option_symbol or search_symbols, and pass the "
        "symbol it returns rather than assembling one.",
    )


def _segment_of(symbol: str, where: str | None) -> str:
    """Classify a contract from the OpenAlgo symbol format.

    The format is the platform's own and is documented in ``CLAUDE.md``: an
    option ends in ``CE`` or ``PE``, a future ends in ``FUT``. Anything else is
    cash or an index, which no payoff leg and no premium series can carry.

    Args:
        symbol: The OpenAlgo symbol.
        where: How to name this leg in a failure message when the operator named
            it, or None when it came out of the position book, which is what
            decides whether an unusable contract is refused or reported.

    Returns:
        ``OPTION`` or ``FUTURE``, or an empty string when the caller is expected
        to report rather than refuse.

    Raises:
        RetryAgentRun: When the operator named a contract that is neither.
    """
    if _OPTION_SUFFIX.search(symbol) and _EMBEDDED_EXPIRY.search(symbol):
        return _SEGMENT_OPTION
    if _FUTURE_SUFFIX.search(symbol) and _EMBEDDED_EXPIRY.search(symbol):
        return _SEGMENT_FUTURE
    if where is None:
        return ""
    invalid_argument(
        "legs",
        f"{where}, {symbol}, is neither an option nor a future",
        "This chart is built from derivative contracts. An option is "
        "[base][DDMMMYY][strike][CE or PE] and a future is [base][DDMMMYY]FUT.",
    )


def _leg_colour(segment: str, option_type: str) -> str:
    """Pick the line colour for one leg.

    Args:
        segment: ``OPTION`` or ``FUTURE``.
        option_type: ``CE``, ``PE`` or an empty string.

    Returns:
        The call colour, the put colour, or the colour for everything else. The
        two option colours are the ones the open interest chart uses, so a call
        is the same colour wherever the conversation draws one.
    """
    if segment == _SEGMENT_OPTION and option_type == "CE":
        return CALL_COLOUR
    if segment == _SEGMENT_OPTION and option_type == "PE":
        return PUT_COLOUR
    return _OTHER_LEG_COLOUR


def signed_multiplier(side: str, lots: int) -> int:
    """The multiplier one leg contributes to a combined premium.

    Args:
        side: ``BUY`` or ``SELL``.
        lots: Whole lots.

    Returns:
        Positive for a bought leg, negative for a sold one, scaled by the lots.
        A combined premium is quoted per share, so the lot size is deliberately
        not in here: a one-lot straddle and a ten-lot straddle trade at the same
        premium and differ only in what they cost.
    """
    return (1 if side == _BUY else -1) * lots


def leg_label(leg: Mapping[str, Any]) -> str:
    """Name one leg for a legend entry or a confirmation line.

    Args:
        leg: A resolved leg.

    Returns:
        Something like ``SELL 2x NIFTY08SEP2623850CE``, with the multiplier
        omitted when it is one.
    """
    lots = int(leg.get("lots") or 1)
    count = "" if lots == 1 else f" {lots}x"
    return f"{leg.get('side', _BUY)}{count} {leg.get('symbol', '')}"


def resolve_underlying_exchange(base: str, value: Any, notices: list[str]) -> str:
    """Settle which exchange an underlying is quoted on.

    Args:
        base: The already-normalised underlying.
        value: The exchange the model named, or an empty value.
        notices: Collected notices, appended to when one is resolved here.

    Returns:
        The exchange code the instrument master holds the underlying on.

    Raises:
        RetryAgentRun: If the underlying is listed nowhere the tool searched.
    """
    text = "" if value is None else str(value).strip().upper()
    if text:
        return text

    for candidate in _UNDERLYING_SEARCH_ORDER:
        if is_listed(base, candidate):
            notices.append(f"{base} was resolved to {candidate} from the instrument master.")
            return candidate

    invalid_argument(
        "underlying",
        f"{base} is not listed on any exchange this tool searched",
        f"Pass the exchange explicitly, one of {', '.join(_UNDERLYING_SEARCH_ORDER)}, or "
        "look the symbol up with search_symbols first.",
    )


def listed_expiries(call: Callable[..., Any], base: str, venue: str) -> list[str]:
    """Every option expiry the instrument master still lists for an underlying.

    The one reader of ``expiry_service`` in the agent's option path, so
    "which expiries exist" has a single answer. The service drops expired dates
    and sorts what is left chronologically, which is what lets a caller take
    the first entry as the nearest and pick a monthly one out of the rest.

    Args:
        call: The toolkit's ``service_call``, so this stays a plain function
            that any toolkit can hand its own service access to.
        base: The already-normalised underlying.
        venue: The underlying's exchange. Mapped to its options venue here.

    Returns:
        Expiries in ``DDMMMYY`` form, nearest first. Empty when the underlying
        lists no options, which every caller reads as a refusal rather than as
        an error.
    """
    payload = call(
        get_expiry_dates,
        symbol=base,
        exchange=get_option_exchange(venue),
        instrumenttype="options",
    )
    dates = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(dates, list):
        return []
    return [item for item in (symbol_expiry(entry) for entry in dates) if item]


def resolve_expiry(
    call: Callable[..., Any], base: str, venue: str, value: Any, notices: list[str]
) -> str:
    """Settle which expiry to price, defaulting to the nearest listed one.

    Resolving it here rather than making the model call ``get_expiry_dates``
    first is a whole round trip saved on the most common question this tool
    answers.

    Args:
        call: The toolkit's ``service_call``, so this stays a plain function
            that any toolkit can hand its own service access to.
        base: The already-normalised underlying.
        venue: The underlying's exchange.
        value: The expiry the model named, or an empty value.
        notices: Collected notices, appended to when one is resolved here.

    Returns:
        The expiry in ``DDMMMYY`` form.

    Raises:
        RetryAgentRun: If the underlying lists no options at all.
    """
    text = "" if value is None else str(value).strip().upper()
    if text:
        return normalise_expiry(text, base, allow_embedded=False)

    nearest = next(iter(listed_expiries(call, base, venue)), None)
    if not nearest:
        invalid_argument(
            "expiry_date",
            f"{base} lists no option expiries on {get_option_exchange(venue)}",
            "Confirm the underlying has listed options, or name the expiry explicitly in "
            "DDMMMYY form.",
        )
    notices.append(f"{nearest} is the nearest listed expiry and was used.")
    return nearest


def resolve_contract(
    call: Callable[..., Any], symbol: str, exchange: str, where: str | None
) -> dict[str, Any]:
    """Read one contract's own details from the instrument master.

    Args:
        call: The toolkit's ``service_call``, so this stays a plain function
            that any toolkit can hand its own service access to.
        symbol: The OpenAlgo symbol.
        exchange: The exchange it lists on, or an empty string to resolve.
        where: How to name this leg in a failure message when the operator
            named it, or None when it came out of the position book.

    Returns:
        The leg fields the master owns: exchange, segment, strike, option
        type, lot size, tick size, expiry and the underlying it belongs to.

    Raises:
        RetryAgentRun: If the master holds no row for the pair.
    """
    label = where or f"the open position {symbol}"
    venue = _resolve_leg_exchange(symbol, exchange, label)
    segment = _segment_of(symbol, label)
    payload = call(symbol_service.get_symbol_info, symbol=symbol, exchange=venue)
    info = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(info, Mapping) or not info:
        invalid_argument(
            "legs",
            f"{symbol} on {venue} has no row in the instrument master",
            "Resolve the contract with get_option_symbol or search_symbols and pass the "
            "symbol it returns.",
        )

    expiry = ""
    embedded = _EMBEDDED_EXPIRY.search(symbol)
    if embedded:
        expiry = embedded.group(0)
    else:
        expiry = symbol_expiry(info.get("expiry")) or ""

    option_type = ""
    strike = None
    expiry_ts = None
    if segment == _SEGMENT_OPTION:
        option_type = symbol[-2:]
        strike = as_number(info.get("strike"))
        try:
            _base, moment, parsed_strike, parsed_type = parse_option_symbol(symbol, venue)
        except Exception:
            logger.exception("Payoff leg %s could not be parsed for its expiry instant", symbol)
        else:
            option_type = parsed_type
            if strike is None:
                strike = parsed_strike
            expiry_ts = int(moment.replace(tzinfo=IST).timestamp())

    base = str(info.get("name") or "").strip().upper()
    if not base:
        base = re.split(_EMBEDDED_EXPIRY, symbol)[0]

    return {
        "symbol": symbol,
        "exchange": venue,
        "segment": segment,
        "strike": strike,
        "option_type": option_type,
        "lotSize": int(as_number(info.get("lotsize")) or 0) or 1,
        "tickSize": as_number(info.get("tick_size")),
        "expiry": expiry,
        "expiryTs": expiry_ts,
        "base": base,
        "underlying_exchange": get_underlying_exchange(base, venue),
    }


# ---------------------------------------------------------------------------
# The toolkit
# ---------------------------------------------------------------------------


class OptionVizToolkit(OpenAlgoToolkit):
    """A combined premium series and a payoff diagram, drawn from platform data.

    Both tools are read-only, so neither requires confirmation and neither
    writes an audit row. Each returns a short confirmation and leaves the
    payload on the run's sink for ``services/agent/viz_sink.py`` to turn into a
    frame.
    """

    def __init__(self, context: ToolContext) -> None:
        """Register the two derived analytics tools.

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

        super().__init__(
            context,
            name="option_viz",
            tools=[self.plot_combined_premium, self.plot_payoff],
        )

    # -- tool one: the combined premium --------------------------------------

    def plot_combined_premium(
        self,
        underlying: str = "",
        exchange: str = "",
        expiry_date: str = "",
        legs: list[str | dict[str, str | int]] | None = None,
        interval: str = DEFAULT_PREMIUM_INTERVAL,
        days: int = DEFAULT_PREMIUM_DAYS,
    ) -> str:
        """Chart the combined premium of several option legs over time.

        Two different series live behind this one tool, and which you get is
        decided by whether you name contracts. Say which one you asked for when
        you describe the result, because they diverge as soon as spot moves:

        - **Leave ``legs`` empty** and you get the **rolling ATM** straddle of
          ``underlying``: for every candle the ATM strike is recomputed from the
          underlying close and that straddle is priced, so the strike follows
          spot. This is the volatility view, and it is what "the NIFTY straddle
          today" usually means.
        - **Name contracts in ``legs``** and you get those exact contracts,
          summed, with the **strikes held constant**. As spot moves away from
          the strike this becomes a directional position, which the rolling
          series never is.

        The series is built from closes and drawn as a line, deliberately. A
        combined high is not the sum of the legs' highs: the legs move against
        each other, so their highs happen at different moments inside one bar
        and adding them invents a peak that never traded. Do not ask for a
        combined candle and do not describe one.

        Sensible defaults, so this usually answers in one call: the latest
        session, five minute candles, and for the rolling series the nearest
        listed expiry and whichever exchange the underlying is listed on. The
        result says what was used, so correct it on a second call only if the
        operator meant something else.

        Args:
            underlying: Underlying symbol for the rolling ATM series:
                ``NIFTY``, ``BANKNIFTY``, ``SENSEX``, ``RELIANCE``,
                ``CRUDEOIL``. Required when ``legs`` is empty. When ``legs`` is
                given it is optional, and is only used to expand a shorthand leg
                such as ``23850CE``.
            exchange: Exchange of the **underlying**, not of the options:
                ``NSE_INDEX`` for NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY;
                ``BSE_INDEX`` for SENSEX, BANKEX; ``NSE`` or ``BSE`` for a
                stock; ``MCX`` for a commodity. Leave it empty to have it looked
                up in the instrument master, which is right almost always.
            expiry_date: Expiry in DDMMMYY format, for example ``08SEP26``.
                Leave it empty for the nearest listed expiry, which is looked up
                here. Only the rolling series needs it; a named contract carries
                its own.
            legs: The contracts to sum, at most eight, each either an OpenAlgo
                symbol such as ``"NIFTY08SEP2623850CE"``, an exchange-qualified
                ``"NFO:NIFTY08SEP2623850CE"``, the shorthand ``"23850CE"`` when
                ``underlying`` and ``expiry_date`` are set, or an object such as
                ``{"symbol": "NIFTY08SEP2623850CE", "exchange": "NFO", "side":
                "SELL", "lots": 1}``. ``side`` defaults to BUY, so a plain list
                of two symbols is their sum; a sold leg is subtracted, which is
                what makes a spread come out as a spread. A contract that is not
                in the instrument master is refused, never guessed.
            interval: Candle size, defaulting to ``5m``. Call ``get_intervals``
                for the ones this broker accepts. Case matters: ``1m`` is one
                minute and ``M`` is one month.
            days: How many recent trading sessions the series spans, defaulting
                to 1, which is the latest session. At most 5.

        Returns:
            One line naming which series was drawn, the last combined value and
            the range. The series travels to the operator's screen, not through
            this answer, so describe what it shows rather than listing points.
        """
        entries = leg_entries(legs, "legs")
        interval, notice = normalise_interval(interval, "api", self._intervals.accepted())
        notices = [notice] if notice else []
        sessions = normalise_int(days, "days", 1, MAX_PREMIUM_DAYS)

        if entries:
            return self._fixed_legs(entries, underlying, expiry_date, interval, sessions, notices)
        return self._rolling_atm(underlying, exchange, expiry_date, interval, sessions, notices)

    def _rolling_atm(
        self,
        underlying: Any,
        exchange: Any,
        expiry_date: Any,
        interval: str,
        sessions: int,
        notices: list[str],
    ) -> str:
        """Draw the rolling ATM straddle, computed by ``straddle_chart_service``.

        The ATM roll is not reimplemented here. The service already recomputes
        the ATM strike from the underlying close for every candle and prices
        that straddle, which is exactly what ``/straddlechart`` draws.

        Args:
            underlying: The model's underlying.
            exchange: The model's exchange, or an empty value to resolve one.
            expiry_date: The model's expiry, or an empty value for the nearest.
            interval: The already-checked candle size.
            sessions: How many recent trading sessions to span.
            notices: Collected notices, appended to.

        Returns:
            The wrapped confirmation.
        """
        base = normalise_symbol(underlying, "underlying")
        venue = resolve_underlying_exchange(base, exchange, notices)
        expiry = resolve_expiry(self.service_call, base, venue, expiry_date, notices)

        payload = self.service_call(
            get_straddle_chart_data,
            underlying=base,
            exchange=venue,
            expiry_date=expiry,
            interval=interval,
            days=sessions,
        )
        data = payload.get("data") if isinstance(payload, Mapping) else None
        rows = data.get("series") if isinstance(data, Mapping) else None
        series = [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []
        if not series:
            return tool_answer(
                "plot_combined_premium",
                f"No rolling ATM straddle came back for {base} {expiry} at {interval}, so "
                "nothing was drawn. Option history may be missing for the strikes that were "
                "ATM during the range.",
                notices,
                underlying=base,
                expiry=expiry,
            )

        strikes = sorted({row.get("atm_strike") for row in series if row.get("atm_strike")})
        combined = [as_number(row.get("straddle")) for row in series]
        legs = [
            {
                "label": "ATM call",
                "colour": CALL_COLOUR,
                "values": [as_number(row.get("ce_price")) for row in series],
            },
            {
                "label": "ATM put",
                "colour": PUT_COLOUR,
                "values": [as_number(row.get("pe_price")) for row in series],
            },
        ]
        subtitle = (
            f"Rolling ATM: the strike follows spot. {len(strikes)} ATM "
            f"{'strike' if len(strikes) == 1 else 'strikes'} used "
            f"({', '.join(format_number(value) for value in strikes)})."
        )

        drawn = self._deliver_premium(
            series=series,
            combined=combined,
            legs=legs,
            title=f"{base} {expiry} rolling ATM straddle, {interval}",
            subtitle=subtitle,
            axis="Straddle premium",
            source="straddle_chart_service",
            notices=notices,
        )
        if not drawn:
            return tool_answer("plot_combined_premium", _NO_SINK_CHART, notices, underlying=base)

        last = series[-1]
        message = (
            f"Drew the rolling ATM straddle for {base} {expiry} at {interval}, "
            f"{len(series)} points across {sessions} "
            f"{'session' if sessions == 1 else 'sessions'}. The strike follows spot, so this is "
            f"the volatility view rather than a fixed position: {len(strikes)} ATM "
            f"{'strike' if len(strikes) == 1 else 'strikes'} were used "
            f"({', '.join(format_number(value) for value in strikes)}). "
            f"Last point {format_price(last.get('straddle'))} at strike "
            f"{format_number(last.get('atm_strike'))} with spot {format_price(last.get('spot'))}: "
            f"call {format_price(last.get('ce_price'))} plus put "
            f"{format_price(last.get('pe_price'))}."
        )
        return tool_answer(
            "plot_combined_premium", message, notices, underlying=base, expiry=expiry
        )

    def _fixed_legs(
        self,
        entries: Sequence[Any],
        underlying: Any,
        expiry_date: Any,
        interval: str,
        sessions: int,
        notices: list[str],
    ) -> str:
        """Draw the sum of the contracts the operator named, strikes held fixed.

        Args:
            entries: The raw ``legs`` entries.
            underlying: The model's underlying, used to expand a shorthand leg.
            expiry_date: The model's expiry, used to expand a shorthand leg.
            interval: The already-checked candle size.
            sessions: How many recent trading sessions to span.
            notices: Collected notices, appended to.

        Returns:
            The wrapped confirmation.
        """
        base = str(underlying or "").strip().upper()
        shorthand_expiry = str(expiry_date or "").strip().upper()
        if shorthand_expiry:
            shorthand_expiry = normalise_expiry(shorthand_expiry, base, allow_embedded=False)

        legs: list[dict[str, Any]] = []
        for index, entry in enumerate(entries, start=1):
            where = f"leg {index}"
            symbol, exchange = leg_symbol(entry, index, base, shorthand_expiry)
            exchange = _resolve_leg_exchange(symbol, exchange, where)
            option_type = symbol[-2:] if _OPTION_SUFFIX.search(symbol) else ""
            legs.append(
                {
                    "symbol": symbol,
                    "exchange": exchange,
                    "segment": _segment_of(symbol, where),
                    "side": leg_side(
                        entry.get("side") if isinstance(entry, Mapping) else None, index
                    ),
                    "lots": leg_lots(
                        entry.get("lots") if isinstance(entry, Mapping) else None, index
                    ),
                    "option_type": option_type,
                }
            )

        start, end = _resolve_trading_window(sessions, _IST_PYTZ)

        # One history frame per leg. There is no cheaper way: these are
        # different instruments, so nothing is being fetched twice.
        closes: list[dict[int, float]] = []
        for leg in legs:
            response = self.service_call(
                history_service.get_history,
                symbol=leg["symbol"],
                exchange=leg["exchange"],
                interval=interval,
                start_date=start,
                end_date=end,
            )
            rows = response.get("data") if isinstance(response, Mapping) else response
            records = (
                [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []
            )
            bars = chart_bars(records, candle_columns(records[0]) if records else {})
            closes.append({bar["time"]: bar["close"] for bar in bars})

        empty = [leg["symbol"] for leg, seen in zip(legs, closes, strict=True) if not seen]
        if empty:
            return tool_answer(
                "plot_combined_premium",
                f"No candles came back for {', '.join(empty)} at {interval} between {start} and "
                f"{end}, so nothing was drawn. Check the contract is listed and still trading, "
                "and that the interval is one this broker supports.",
                notices,
            )

        # The inner join is the correctness point. A combined value needs every
        # leg to have printed in that window; taking the union and treating a
        # missing leg as zero would draw a collapse that never happened.
        common = set(closes[0])
        for seen in closes[1:]:
            common &= set(seen)
        for leg, seen in zip(legs, closes, strict=True):
            dropped = len(seen) - len(common)
            if dropped > 0:
                notices.append(
                    f"{leg['symbol']} printed {len(seen)} candles, {dropped} of which had no "
                    "matching candle on every other leg and were dropped from the combined "
                    "series."
                )
        if not common:
            return tool_answer(
                "plot_combined_premium",
                "The legs share no candle timestamp at "
                f"{interval} between {start} and {end}, so no combined series could be built. "
                "One of them is illiquid enough that it never printed at the same time as the "
                "others; try a coarser interval.",
                notices,
            )

        series = [{"time": moment} for moment in sorted(common)]
        series = _cap_last_n_trading_dates(series, sessions, _IST_PYTZ)
        times = [row["time"] for row in series]
        combined = [
            round(
                sum(
                    signed_multiplier(leg["side"], leg["lots"]) * seen[moment]
                    for leg, seen in zip(legs, closes, strict=True)
                ),
                4,
            )
            for moment in times
        ]
        traces = [
            {
                "label": leg_label(leg),
                "colour": _leg_colour(leg["segment"], leg["option_type"]),
                "values": [seen[moment] for moment in times],
            }
            for leg, seen in zip(legs, closes, strict=True)
        ]

        total_dropped = sum(max(0, len(seen) - len(common)) for seen in closes)
        subtitle = (
            f"Fixed legs: strikes held constant. {len(times)} aligned bars, "
            f"{total_dropped} dropped."
        )
        heading = (
            " ".join(leg_label(leg) for leg in legs)
            if len(legs) <= _MAX_HEADING_LEGS
            else f"{legs[0]['symbol']} and {len(legs) - 1} more legs"
        )

        drawn = self._deliver_premium(
            series=series,
            combined=combined,
            legs=traces,
            title=f"{heading}, combined premium at {interval}",
            subtitle=subtitle,
            axis="Combined premium",
            source="history_service",
            notices=notices,
        )
        if not drawn:
            return tool_answer("plot_combined_premium", _NO_SINK_CHART, notices)

        parts = " plus ".join(
            f"{leg_label(leg)} at {format_price(seen[times[-1]])}"
            for leg, seen in zip(legs, closes, strict=True)
        )
        message = (
            f"Drew the combined premium of {len(legs)} fixed legs at {interval} from {start} to "
            f"{end}: {len(times)} aligned bars, {total_dropped} dropped. The strikes are held "
            "constant, so this is a fixed position rather than the rolling ATM view. Last bar "
            f"{format_price(combined[-1])} ({parts})."
        )
        return tool_answer("plot_combined_premium", message, notices)

    # -- tool two: the payoff ------------------------------------------------

    def plot_payoff(
        self,
        legs: list[str | dict[str, str | int]] | None = None,
        underlying: str = "",
        expiry_date: str = "",
        include_open_positions: bool = False,
    ) -> str:
        """Draw the payoff diagram of an option structure at expiry.

        Reach for this whenever the operator asks what a structure makes or
        loses, where it breaks even, what its maximum profit or loss is, or
        simply "what is my payoff". Do not describe a payoff shape in prose and
        never draw one out of characters: this tool exists so the operator sees
        the real curve.

        Two sources of legs, and they can be combined:

        - **Contracts the operator named**, in ``legs``. Use this for a
          structure they are considering.
        - **Their own open positions.** Call with no arguments at all and the
          position book is read: that is the right call for "what is my payoff"
          and "show me my current risk". Set ``include_open_positions`` to add
          the book to legs you also named.

        Every number on the curve is fetched here: the lot size and tick size
        from the instrument master, the premium from the live quote or, for a
        held position, its own average price, the implied volatility from the
        platform's Black-76 inversion, and the spot from the underlying's quote.
        You supply which contracts, which side and how many, and nothing else.

        Cash equity is not on the curve, because a payoff leg is an option or a
        future. When the operator holds shares in the same underlying, the card
        says so and so must you: a covered call charted without its shares looks
        like a naked short call.

        Args:
            legs: The contracts in the structure, at most eight, each either an
                OpenAlgo symbol such as ``"NIFTY08SEP2623850CE"``, an
                exchange-qualified ``"NFO:NIFTY08SEP2623850CE"``, the shorthand
                ``"23850CE"`` when ``underlying`` and ``expiry_date`` are set,
                or an object such as ``{"symbol": "NIFTY08SEP2623850CE",
                "exchange": "NFO", "side": "SELL", "lots": 2}``. ``side``
                defaults to BUY and ``lots`` to 1. Leave the whole argument out
                to chart the operator's own open positions instead. A contract
                that is not in the instrument master is refused, never guessed.
            underlying: Optional, and only used to expand a shorthand leg such
                as ``23850CE``. The underlying of the curve itself is read from
                the legs.
            expiry_date: Optional, in DDMMMYY format, and only used to expand a
                shorthand leg.
            include_open_positions: True to add the operator's open F&O
                positions to the legs named above. Ignored when ``legs`` is
                empty, because the position book is then the source anyway.

        Returns:
            One line naming the structure, the spot it was priced against and
            the legs. The curve is computed and drawn on the operator's screen
            from the legs this tool resolved, so describe the shape rather than
            listing numbers you do not have.
        """
        entries = leg_entries(legs, "legs")
        base = str(underlying or "").strip().upper()
        shorthand_expiry = str(expiry_date or "").strip().upper()
        if shorthand_expiry:
            shorthand_expiry = normalise_expiry(shorthand_expiry, base, allow_embedded=False)

        notices: list[str] = []
        excluded: list[dict[str, str]] = []
        sources = ["symbol_service", "quotes_service"]

        named = self._named_legs(entries, base, shorthand_expiry)
        held: list[dict[str, Any]] = []
        if not named or include_open_positions:
            held = self._position_legs(excluded)
            sources.append("positionbook_service")

        raw = named + held
        if not raw:
            return tool_answer(
                "plot_payoff",
                "There is nothing to chart: no contracts were named and the position book holds "
                "no open futures or options, so the operator is flat in derivatives. Say so "
                "rather than drawing an empty diagram."
                + (
                    " They do hold "
                    + ", ".join(f"{row['symbol']} ({row['reason']})" for row in excluded)
                    + "."
                    if excluded
                    else ""
                ),
            )

        chosen, dropped = self._one_underlying(raw)
        for row in dropped:
            notices.append(
                f"{row['symbol']} is on {row['base']}, a different underlying, so it is not on "
                "this curve. One payoff diagram has one underlying on its axis."
            )
        for row in excluded:
            if row.get("base") == chosen[0]["base"]:
                notices.append(
                    f"The operator also holds {row['symbol']}, which is {row['reason']} and "
                    "cannot be a leg of this curve. The diagram therefore understates a covered "
                    "or hedged position: say so."
                )

        resolved, spot, used_forward, atm_iv = self._price_legs(chosen, notices)
        if not resolved:
            return tool_answer(
                "plot_payoff",
                "None of the legs could be priced against the broker session, so no payoff was "
                "drawn. Check the contracts are still quoting.",
                notices,
            )
        if spot is None or spot <= 0:
            # Every point on the curve is placed relative to the underlying, so
            # a missing spot is not a cosmetic gap: it is a diagram with no
            # axis. Refusing beats drawing one centred on nothing.
            return tool_answer(
                "plot_payoff",
                f"{chosen[0]['base']} on {chosen[0]['underlying_exchange']} returned no last "
                "traded price, so the curve has nothing to centre on and none was drawn. Say "
                "the underlying could not be priced rather than describing a shape.",
                notices,
            )
        if used_forward:
            sources.append("synthetic_future_service")

        spec: dict[str, Any] = {
            "underlying": chosen[0]["base"],
            "underlying_exchange": chosen[0]["underlying_exchange"],
            "spot": spot,
            "atm_iv": atm_iv,
            "currency": CURRENCY,
            "mode": current_mode(self.analyzer_mode),
            "as_of": datetime.now(IST).isoformat(timespec="seconds"),
            "timezone": "Asia/Kolkata",
            "legs": resolved,
        }
        if excluded:
            spec["excluded"] = excluded
        if notices:
            spec["notices"] = list(notices)

        origin = "the operator's open positions" if held and not named else "the named legs"
        drawn = emit(
            self._sink,
            tool="plot_payoff",
            kind=PAYOFF_VIZ,
            spec=json_safe(spec),
            title=f"{chosen[0]['base']} payoff at expiry",
            source=", ".join(sources),
        )
        if not drawn:
            return tool_answer("plot_payoff", _NO_SINK_PAYOFF, notices)

        message = (
            f"Drew the payoff at expiry for {len(resolved)} "
            f"{'leg' if len(resolved) == 1 else 'legs'} on {chosen[0]['base']}, from {origin}, "
            f"priced against spot {format_price(spot)}: "
            + "; ".join(
                f"{leg['side']} {leg['lots']}x{leg['lotSize']} {leg['symbol']} at "
                f"{format_price(leg['price'])}"
                for leg in resolved
            )
            + ". The operator can see the curve, its breakevens and its maximum profit and loss, "
            "so read the shape rather than restating the legs."
        )
        return tool_answer("plot_payoff", message, notices, underlying=chosen[0]["base"])

    # -- leg resolution ------------------------------------------------------

    def _named_legs(self, entries: Sequence[Any], base: str, expiry: str) -> list[dict[str, Any]]:
        """Resolve the contracts the operator named against the symbol master.

        Args:
            entries: The raw ``legs`` entries.
            base: The call's underlying, used to expand a shorthand leg.
            expiry: The call's expiry, used to expand a shorthand leg.

        Returns:
            One resolved contract per entry, carrying the master's own lot size,
            tick size, strike and expiry.

        Raises:
            RetryAgentRun: If any entry names a contract the master does not
                hold. The operator named it, so guessing or skipping it would be
                worse than refusing.
        """
        legs: list[dict[str, Any]] = []
        for index, entry in enumerate(entries, start=1):
            symbol, exchange = leg_symbol(entry, index, base, expiry)
            contract = resolve_contract(self.service_call, symbol, exchange, f"leg {index}")
            contract["side"] = leg_side(
                entry.get("side") if isinstance(entry, Mapping) else None, index
            )
            contract["lots"] = leg_lots(
                entry.get("lots") if isinstance(entry, Mapping) else None, index
            )
            contract["origin"] = "named"
            legs.append(contract)
        return legs

    def _position_legs(self, excluded: list[dict[str, str]]) -> list[dict[str, Any]]:
        """Read the operator's own open derivative positions as payoff legs.

        Args:
            excluded: Collected rows that cannot be a leg, appended to. A cash
                holding belongs here rather than being dropped, because a
                covered call charted without its shares reads as a naked short.

        Returns:
            One resolved leg per open futures or options position, carrying the
            position's own average price as the entry premium.

        Raises:
            RetryAgentRun: If a derivative position cannot be resolved against
                the symbol master. A payoff missing a real leg understates the
                risk, so it fails rather than drawing.
        """
        payload = self.service_call(get_positionbook)
        data = payload.get("data") if isinstance(payload, Mapping) else payload
        rows = [row for row in data if isinstance(row, Mapping)] if isinstance(data, list) else []

        legs: list[dict[str, Any]] = []
        for row in rows:
            quantity = as_number(row.get("quantity"))
            symbol = str(row.get("symbol") or "").strip().upper()
            exchange = str(row.get("exchange") or "").strip().upper()
            if not symbol or looks_flat(row.get("quantity")) or quantity is None:
                continue
            if _segment_of(symbol, None) == "":
                excluded.append(
                    {
                        "symbol": symbol,
                        "exchange": exchange,
                        "reason": "a cash position rather than a derivative",
                        "base": symbol,
                    }
                )
                continue
            if len(legs) >= MAX_LEGS:
                excluded.append(
                    {
                        "symbol": symbol,
                        "exchange": exchange,
                        "reason": f"past the {MAX_LEGS} legs one diagram carries",
                        "base": symbol,
                    }
                )
                continue

            contract = resolve_contract(self.service_call, symbol, exchange, None)
            lot_size = contract["lotSize"]
            contract["side"] = _BUY if quantity > 0 else _SELL
            contract["lots"] = max(1, int(round(abs(quantity) / lot_size))) if lot_size else 1
            contract["origin"] = "position"
            average = as_number(row.get("average_price"))
            if average is not None and average > 0:
                contract["entry_price"] = average
            legs.append(contract)
        return legs

    @staticmethod
    def _one_underlying(
        legs: Sequence[Mapping[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Keep the legs of one underlying, because one curve has one axis.

        Args:
            legs: Every resolved leg.

        Returns:
            The legs of the underlying with the most of them, and the rest. The
            rest are named to the operator rather than dropped in silence.
        """
        groups: dict[str, list[dict[str, Any]]] = {}
        for leg in legs:
            groups.setdefault(str(leg.get("base") or ""), []).append(dict(leg))
        winner = max(groups, key=lambda name: (len(groups[name]), name))
        rest = [leg for name, rows in groups.items() if name != winner for leg in rows]
        return groups[winner], rest

    def _price_legs(
        self, legs: Sequence[Mapping[str, Any]], notices: list[str]
    ) -> tuple[list[dict[str, Any]], float | None, bool, float | None]:
        """Attach the live price, the implied volatility and the spot to each leg.

        One batched quote covers every leg plus the underlying, and one forward
        is computed per expiry, so a four leg structure costs two broker
        requests rather than eight. The implied volatility is then a local
        Black-76 inversion of numbers already in hand.

        Args:
            legs: The resolved contracts of one underlying.
            notices: Collected notices, appended to when a leg cannot be priced.

        Returns:
            The legs in ``StrategyLeg`` shape, the underlying's spot, whether a
            forward was available, and the implied volatility to use for a leg
            that has none of its own.
        """
        base = str(legs[0].get("base") or "")
        venue = str(legs[0].get("underlying_exchange") or "")

        pairs = [{"symbol": leg["symbol"], "exchange": leg["exchange"]} for leg in legs]
        pairs.append({"symbol": base, "exchange": venue})
        response = self.service_call(quotes_service.get_multiquotes, symbols=pairs)
        results = response.get("results") if isinstance(response, Mapping) else None
        quotes: dict[tuple[str, str], float] = {}
        for row in results if isinstance(results, list) else []:
            if not isinstance(row, Mapping):
                continue
            data = row.get("data")
            price = as_number(data.get("ltp")) if isinstance(data, Mapping) else None
            if price is not None:
                key = (str(row.get("symbol") or ""), str(row.get("exchange") or ""))
                quotes[key] = price
        spot = quotes.get((base, venue))

        # One forward per expiry, shared by every leg on it. It is the reference
        # Black-76 is defined against, and the platform's own convention: an
        # index future trades at a premium to spot, so inverting against spot
        # biases every implied volatility on the curve.
        forwards: dict[str, float] = {}
        for expiry in {str(leg.get("expiry") or "") for leg in legs if leg.get("expiry")}:
            try:
                payload = self.service_call(
                    calculate_synthetic_future,
                    underlying=base,
                    exchange=venue,
                    expiry_date=expiry,
                )
            except Exception:
                logger.exception("Payoff: no forward for %s %s", base, expiry)
                continue
            value = as_number(payload.get("synthetic_future_price"))
            if value:
                forwards[expiry] = value

        priced: list[dict[str, Any]] = []
        ivs: list[float] = []
        for index, leg in enumerate(legs, start=1):
            market = quotes.get((leg["symbol"], leg["exchange"]))
            entry = as_number(leg.get("entry_price"))
            price = entry if entry is not None else market
            if price is None:
                notices.append(
                    f"{leg['symbol']} is not quoting, so it could not be priced and is not on "
                    "the curve. The diagram is therefore incomplete."
                )
                continue

            if leg["segment"] == _SEGMENT_OPTION and as_number(leg.get("strike")) is None:
                notices.append(
                    f"{leg['symbol']} has no strike in the instrument master, so it could not be "
                    "priced and is not on the curve. The diagram is therefore incomplete."
                )
                continue

            expiry = str(leg.get("expiry") or "")
            forward = forwards.get(expiry)
            iv = 0.0
            if leg["segment"] == _SEGMENT_OPTION and forward and market:
                try:
                    greeks = self.service_call(
                        calculate_greeks,
                        option_symbol=leg["symbol"],
                        exchange=leg["exchange"],
                        spot_price=forward,
                        option_price=market,
                    )
                except Exception:
                    logger.exception("Payoff: no implied volatility for %s", leg["symbol"])
                else:
                    iv = as_number(greeks.get("implied_volatility")) or 0.0
            if iv > 0:
                ivs.append(iv)

            entry_leg: dict[str, Any] = {
                "id": f"agent-{index}",
                "segment": leg["segment"],
                "side": leg["side"],
                "lots": int(leg["lots"]),
                "lotSize": int(leg["lotSize"]),
                "expiry": expiry,
                "price": round(price, 6),
                "iv": round(iv, 4),
                "active": True,
                "symbol": leg["symbol"],
                "exchange": leg["exchange"],
                "contractValid": True,
                "origin": leg.get("origin", "named"),
            }
            if leg["segment"] == _SEGMENT_OPTION:
                entry_leg["strike"] = leg.get("strike")
                entry_leg["optionType"] = leg.get("option_type")
            if leg.get("tickSize") is not None:
                entry_leg["tickSize"] = leg["tickSize"]
            if leg.get("expiryTs"):
                entry_leg["expiryTs"] = leg["expiryTs"]
            if market is not None:
                entry_leg["marketPrice"] = round(market, 6)
            if spot is not None:
                entry_leg["referenceUnderlying"] = spot
            if forward and leg["segment"] == _SEGMENT_OPTION:
                entry_leg["forwardPrice"] = forward
            priced.append(entry_leg)

        atm_iv = round(sum(ivs) / len(ivs), 4) if ivs else None
        return priced, spot, bool(forwards), atm_iv

    # -- delivery ------------------------------------------------------------

    def _deliver_premium(
        self,
        *,
        series: Sequence[Mapping[str, Any]],
        combined: Sequence[Any],
        legs: Sequence[Mapping[str, Any]],
        title: str,
        subtitle: str,
        axis: str,
        source: str,
        notices: list[str],
    ) -> bool:
        """Put one combined premium line chart on the run's sink.

        The combined series is the thick line and every leg is a thin one under
        it, so the reader can see which leg moved. The figure is a line and only
        a line: see the module docstring for why a candle would be a lie.

        Args:
            series: The aligned rows, each carrying ``time`` in epoch seconds.
            combined: The combined value per row.
            legs: One entry per leg, carrying ``label``, ``colour`` and
                ``values`` parallel to ``series``.
            title: Heading shown above the chart.
            subtitle: The line under the heading that says which of the two
                series this is.
            axis: The y axis title.
            source: The service the data came from.
            notices: Collected notices, appended to when points are dropped to
                fit the frame.

        Returns:
            True when it was queued for delivery.
        """
        total = len(series)
        keep = min(total, MAX_PREMIUM_POINTS)
        if total > keep:
            notices.append(
                f"{total - keep} of {total} points were older than the {MAX_PREMIUM_POINTS} the "
                "chart carries, so it starts later than the range asked for."
            )
        rows = list(series)[-keep:]
        x = [_ist_label(row.get("time")) for row in rows]

        traces: list[dict[str, Any]] = [
            {
                "type": "scatter",
                "mode": "lines",
                "name": "Combined",
                "x": x,
                "y": list(combined)[-keep:],
                "line": {"color": _COMBINED_COLOUR, "width": 2},
            }
        ]
        for leg in legs:
            traces.append(
                {
                    "type": "scatter",
                    "mode": "lines",
                    "name": str(leg.get("label") or ""),
                    "x": x,
                    "y": list(leg.get("values") or [])[-keep:],
                    "line": {"color": str(leg.get("colour") or _OTHER_LEG_COLOUR), "width": 1},
                    "opacity": 0.65,
                }
            )

        spec = plotly_spec(
            data=traces,
            layout={
                "margin": {"l": 56, "r": 24, "t": 48, "b": 48},
                "xaxis": {"title": {"text": "Time (IST)"}},
                "yaxis": {"title": {"text": axis}},
                "legend": {"orientation": "h"},
                "annotations": [
                    {
                        "x": 0,
                        "xref": "paper",
                        "xanchor": "left",
                        "y": 1.12,
                        "yref": "paper",
                        "yanchor": "bottom",
                        "showarrow": False,
                        "text": subtitle,
                        "font": {"size": 11},
                    }
                ],
            },
        )
        return emit(
            self._sink,
            tool="plot_combined_premium",
            kind="plotly",
            spec=spec,
            title=title,
            source=source,
        )
