"""Live cards: a subscription list, and one derived number recomputed per tick.

Two read-only tools. Neither of them streams anything itself, and that is the
whole design. OpenAlgo already has one WebSocket client in the browser
(``frontend/src/lib/MarketDataManager.ts``: a single shared socket, ref-counted
subscriptions, a REST fallback after hours), and the point of these tools is to
hand that client a **resolved, seeded, bounded** subscription rather than to
grow a second one on the server.

So a tool here does four things and stops:

1. **Resolves** every instrument against the instrument master. An unresolvable
   symbol reaching the client is a subscription that never ticks, which on
   screen is indistinguishable from a dead feed. It is refused by name, the
   ones that did resolve are listed, and the card still opens for those.
2. **Seeds** a snapshot from ``quotes_service``, and from ``depth_service`` in
   Depth mode, so the card renders complete on first paint. Outside market
   hours there may be no tick at all, and an unseeded card would sit blank
   looking broken.
3. **Bounds** the list. Every instrument on a card is a live subscription held
   for as long as the message is on screen, and a conversation accumulates
   messages, so the caps here are not politeness: they are what stops a long
   conversation holding a hundred subscriptions.
4. **Carries market status**, so the renderer can say the market is closed
   rather than showing a still price as though it were live.

Tool one: :meth:`LiveToolkit.stream_quotes`, viz kind ``live_quotes``
---------------------------------------------------------------------

A list of instruments in one of the three modes the client already speaks:
``LTP``, ``Quote`` or ``Depth``. That vocabulary is ``SubscriptionMode`` in
``MarketDataManager.ts`` exactly, because inventing a fourth word for the same
three things is how a card ends up subscribing in a mode the manager ignores.

Tool two: :meth:`LiveToolkit.stream_combo`, viz kind ``live_combo``
--------------------------------------------------------------------

"Get the live ATM straddle of NIFTY current week" is not a list of quotes. It
is **one number recomputed on every tick of two instruments**, and the same
shape covers a strangle, a vertical spread, a ratio and a synthetic basis. So
the tool is generic: it resolves legs, states the formula, and the client
evaluates it per tick.

The formula is deliberately the dullest thing that covers all of them::

    value = constant + sum(multiplier * price(leg))

``multiplier`` is ``signed_multiplier(side, lots)`` from
:mod:`services.agent.tools.option_viz`, which is the **one** vocabulary this
codebase uses to describe a combination of instruments. The payoff diagram
already speaks it. A second way to say "sold" is how a leg ends up added in one
card and subtracted in another.

Every part is service work, never arithmetic in the model's head or in this
file's:

=========================  =================================================
Part                       Source
=========================  =================================================
The expiry                 ``expiry_service`` through ``listed_expiries``
The spot                   ``quotes_service.get_quotes``
The ATM strike             ``option_symbol_service.get_available_strikes``
                           plus its own ``find_atm_strike_from_actual``
The strike interval        the spacing of the listed strike ladder
The option symbols         ``option_symbol_service.get_option_symbol``
Lot size, tick, strike     ``symbol_service.get_symbol_info``
The seeded premiums        ``quotes_service.get_multiquotes``
Market status              ``market_calendar_service``
=========================  =================================================

The ATM roll, which is the honest-design decision here
-------------------------------------------------------

An ATM straddle stops being the ATM straddle the moment spot crosses half a
strike interval. There are two ways to handle that and only one of them is
defensible:

* **Resubscribe to the new strike.** The number then changes meaning underneath
  the operator mid-observation, and every roll thrashes two subscriptions. What
  they were watching is gone and nothing says so.
* **Pin the legs, and notice out loud.** The legs resolved here stay the legs.
  The card carries ``atm.strike``, ``atm.strike_interval`` and
  ``atm.roll_threshold`` (half an interval), so the renderer can compare live
  spot against them and **say** that spot has moved to a different strike,
  while the card goes on showing the combination it actually holds.

The second is what this does. A stale label on a live number is the worst of
both: the number keeps updating, so it reads as current, while the words above
it describe a position nobody has.

The token rule
--------------

Both tools answer the model with a short confirmation carrying the seeded
values, and the card, its ladders, its legs and its market calendar travel to
the client on the frame through ``services/agent/viz_sink.py``. The seeded
values are in the confirmation on purpose, because the model has to be able to
say something concrete; the confirmation also tells it those numbers are the
ones the card opened with and not the current ones, because by the time the
answer is read they will have moved.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from services import depth_service, quotes_service
from services.agent.tools.account import CURRENCY, current_mode
from services.agent.tools.base import (
    OpenAlgoToolkit,
    as_number,
    format_price,
    invalid_argument,
    json_safe,
)
from services.agent.tools.instrument import depth_levels, normalise_quote, quote_move
from services.agent.tools.market import IST, is_listed, symbol_pairs
from services.agent.tools.option_viz import (
    MAX_LEGS,
    leg_entries,
    leg_label,
    leg_lots,
    leg_side,
    leg_symbol,
    listed_expiries,
    resolve_contract,
    resolve_underlying_exchange,
    signed_multiplier,
)
from services.agent.tools.options import normalise_expiry, normalise_int, normalise_symbol
from services.agent.tools.symbols import DERIVATIVE_EXCHANGES, INDEX_EXCHANGES
from services.agent.tools.viz import tool_answer
from services.agent.viz_sink import emit, no_sink_message, sink_of
from services.market_calendar_service import check_holiday, get_timings
from services.option_symbol_service import (
    NO_SPOT_EXCHANGES,
    find_atm_strike_from_actual,
    get_available_strikes,
    get_option_exchange,
    get_option_symbol,
    resolve_underlying_quote,
)
from utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from services.agent.tools import ToolContext

logger = get_logger(__name__)

__all__ = ["LIVE_COMBO_VIZ", "LIVE_QUOTES_VIZ", "STRUCTURES", "LiveToolkit"]

#: The two renderer selectors this toolkit emits. One kind, one branch in the
#: client's ``VizBlock``: that is the whole cost of adding a renderer.
LIVE_QUOTES_VIZ = "live_quotes"
LIVE_COMBO_VIZ = "live_combo"

#: The subscription modes the browser's ``MarketDataManager`` accepts, spelled
#: the way it spells them. Taking its vocabulary rather than inventing one is
#: what stops a card asking for a mode the manager silently ignores.
MODES: tuple[str, ...] = ("LTP", "Quote", "Depth")

#: What the model gets when it does not name a mode. Quote carries the day's
#: open, high, low, volume and the touch as well as the last price, which is
#: what a watchlist row shows, and it costs the same subscription as LTP.
DEFAULT_MODE = "Quote"

#: Most instruments one quotes card carries. Each is a live subscription held
#: for as long as the message is on screen, and a conversation accumulates
#: messages, so this is a resource bound rather than a readability one.
MAX_LIVE_SYMBOLS = 12

#: Most instruments a **Depth** card carries. A depth subscription is an order
#: book per instrument at every tick rather than one price, and seeding it costs
#: one broker request each because there is no batched depth service.
MAX_LIVE_DEPTH_SYMBOLS = 4

#: Levels a side a seeded ladder carries. Indian exchanges publish five.
MAX_DEPTH_LEVELS = 5

#: The combination card subscribes its legs in this mode. Not an argument: the
#: formula needs the last traded price and nothing else, and Quote carries the
#: day's move alongside it for free, so there is nothing to choose between.
COMBO_MODE = "Quote"

_TIMEZONE = "Asia/Kolkata"

_BUY = "BUY"
_SELL = "SELL"

_NO_SINK_QUOTES = no_sink_message("live quotes card")
_NO_SINK_COMBO = no_sink_message("live combination card")


# ---------------------------------------------------------------------------
# The structure table
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LegTemplate:
    """One leg of a named structure, before it is resolved to a contract.

    Attributes:
        side: ``BUY`` or ``SELL``. Decides the sign of this leg's contribution.
        lots: How many of this leg, which is what makes a ratio a ratio.
        kind: ``option`` for a contract resolved at an offset from the ATM
            strike, or ``spot`` for the underlying itself, which is what lets a
            basis be expressed as legs rather than as a special case.
        offset: The offset from the ATM strike, in
            ``option_symbol_service``'s own vocabulary: ``ATM``, ``OTM{width}``
            or ``ITM{width}``. ``{width}`` is filled in from the tool's
            ``width`` argument. Empty for a spot leg.
        option_type: ``CE`` or ``PE``. Empty for a spot leg.
    """

    side: str
    lots: int
    kind: str
    offset: str = ""
    option_type: str = ""


@dataclass(frozen=True, slots=True)
class Structure:
    """One named combination, as the legs it expands into.

    Adding a structure is one entry in :data:`STRUCTURES` and nothing else.

    Attributes:
        legs: The legs, in the order they are shown.
        summary: One line describing what the number means, carried onto the
            card so a reader never has to infer it from the legs.
        constant: ``strike`` when the structure's value is quoted relative to
            its strike rather than as a bare premium sum, which is what makes a
            synthetic future come out as a price. Empty otherwise.
        needs_width: True when the structure reads the ``width`` argument, so
            the tool can say the argument was ignored when it does not.
    """

    legs: tuple[LegTemplate, ...]
    summary: str
    constant: str = ""
    needs_width: bool = False


#: Every structure the tool can build, keyed by the word the model passes. The
#: value of every one of them is the same signed sum; they differ only in which
#: legs go into it, which is exactly why this is a table and not a branch per
#: structure.
STRUCTURES: Mapping[str, Structure] = {
    "straddle": Structure(
        legs=(
            LegTemplate(_BUY, 1, "option", "ATM", "CE"),
            LegTemplate(_BUY, 1, "option", "ATM", "PE"),
        ),
        summary="the call and the put at the ATM strike, added together",
    ),
    "strangle": Structure(
        legs=(
            LegTemplate(_BUY, 1, "option", "OTM{width}", "CE"),
            LegTemplate(_BUY, 1, "option", "OTM{width}", "PE"),
        ),
        summary="the out of the money call and put, added together",
        needs_width=True,
    ),
    "call_spread": Structure(
        legs=(
            LegTemplate(_BUY, 1, "option", "ATM", "CE"),
            LegTemplate(_SELL, 1, "option", "OTM{width}", "CE"),
        ),
        summary="the ATM call less the further out call, so the net debit of the spread",
        needs_width=True,
    ),
    "put_spread": Structure(
        legs=(
            LegTemplate(_BUY, 1, "option", "ATM", "PE"),
            LegTemplate(_SELL, 1, "option", "OTM{width}", "PE"),
        ),
        summary="the ATM put less the further out put, so the net debit of the spread",
        needs_width=True,
    ),
    "call_ratio": Structure(
        legs=(
            LegTemplate(_BUY, 1, "option", "ATM", "CE"),
            LegTemplate(_SELL, 2, "option", "OTM{width}", "CE"),
        ),
        summary="one ATM call against two further out calls, so the net of the ratio",
        needs_width=True,
    ),
    "put_ratio": Structure(
        legs=(
            LegTemplate(_BUY, 1, "option", "ATM", "PE"),
            LegTemplate(_SELL, 2, "option", "OTM{width}", "PE"),
        ),
        summary="one ATM put against two further out puts, so the net of the ratio",
        needs_width=True,
    ),
    "synthetic": Structure(
        legs=(
            LegTemplate(_BUY, 1, "option", "ATM", "CE"),
            LegTemplate(_SELL, 1, "option", "ATM", "PE"),
        ),
        summary="the synthetic future: strike plus the call less the put",
        constant="strike",
    ),
    "basis": Structure(
        legs=(
            LegTemplate(_BUY, 1, "option", "ATM", "CE"),
            LegTemplate(_SELL, 1, "option", "ATM", "PE"),
            LegTemplate(_SELL, 1, "spot"),
        ),
        summary="the basis: the synthetic future less spot, so the forward premium",
        constant="strike",
    ),
}

#: What ``structure`` becomes when the operator named the contracts themselves.
CUSTOM_STRUCTURE = "custom"

#: How the model may spell "the nearest listed expiry", and the rest of the
#: expiry vocabulary. Every one of these resolves against the **listed**
#: expiries, so the tool always names a real date back.
_EXPIRY_CHOICES: tuple[str, ...] = (
    "current_week",
    "next_week",
    "current_month",
    "next_month",
)

_DEFAULT_EXPIRY_CHOICE = "current_week"


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def normalise_mode(value: Any) -> str:
    """Settle which subscription mode a card opens in.

    Args:
        value: The model's value, or an empty value for the default.

    Returns:
        One of :data:`MODES`, spelled the way the browser's manager spells it.

    Raises:
        RetryAgentRun: For a word that is not one of the three.
    """
    text = "" if value is None else str(value).strip().lower()
    if not text:
        return DEFAULT_MODE
    for mode in MODES:
        if text == mode.lower():
            return mode
    invalid_argument(
        "mode",
        f"{text!r} is not a subscription mode",
        f"Pass one of {', '.join(MODES)}. LTP is the last price only, Quote adds the day's "
        "open, high, low, volume and the touch, and Depth adds the order book.",
    )


def calendar_exchange(exchange: str) -> str:
    """The exchange whose trading session an instrument actually follows.

    An index is quoted on its own pseudo exchange but has no session of its
    own: NIFTY opens and closes exactly when NSE does. The market calendar
    stores real exchanges only, so a lookup on ``NSE_INDEX`` finds nothing and
    the card would read as closed every minute of every day. The browser's
    ``useMarketStatus`` learned this the same way.

    Args:
        exchange: The OpenAlgo exchange code.

    Returns:
        The exchange to look the session up under.
    """
    return exchange[: -len("_INDEX")] if exchange.endswith("_INDEX") else exchange


def strike_spacing(strikes: Sequence[Any]) -> float | None:
    """The spacing of a listed strike ladder.

    Read off the ladder rather than assumed, because strike intervals differ by
    underlying and a card that assumed one would be telling the operator the
    ATM had rolled when it had not. The most common gap wins, and a tie goes to
    the smaller one, because a ladder is usually a fine grid near the money
    that thins out in the wings: the fine grid is the real interval.

    Args:
        strikes: The listed strikes, ascending, as the master returned them.

    Returns:
        The interval, or None when the ladder has fewer than two usable
        strikes, in which case the card omits it rather than guessing one.
    """
    gaps: dict[float, int] = {}
    previous: float | None = None
    for entry in strikes:
        value = as_number(entry)
        if value is None:
            continue
        if previous is not None:
            gap = round(value - previous, 4)
            if gap > 0:
                gaps[gap] = gaps.get(gap, 0) + 1
        previous = value
    if not gaps:
        return None
    return min(gaps, key=lambda gap: (-gaps[gap], gap))


def _within_this_week(expiry: str) -> bool:
    """Whether a ``DDMMMYY`` expiry falls inside the current calendar week.

    Args:
        expiry: The expiry, as every OpenAlgo symbol spells it.

    Returns:
        True when the date is on or before the coming Sunday. An unparseable
        date answers False, so the card says "the nearest listed one" rather
        than claiming a week it could not check.
    """
    try:
        moment = datetime.strptime(expiry, "%d%b%y").date()
    except ValueError:
        return False
    today = datetime.now(IST).date()
    return today <= moment <= today + timedelta(days=6 - today.weekday())


def _epoch_ms(value: Any) -> int | None:
    """Read a market-calendar timestamp, which is in epoch milliseconds.

    Args:
        value: The ``start_time`` or ``end_time`` of a timings row.

    Returns:
        The value as a whole number of milliseconds, or None.
    """
    number = as_number(value)
    return None if number is None else int(number)


def _quote_rows(response: Any) -> dict[tuple[str, str], Mapping[str, Any]]:
    """Index a batched quote response by the pair each row is about.

    Args:
        response: The payload ``quotes_service.get_multiquotes`` returned.

    Returns:
        The rows that carried data, keyed by ``(symbol, exchange)``. A row that
        carried an error is left out, so the caller reports the instrument as
        unseeded rather than as priced at zero.
    """
    results = response.get("results") if isinstance(response, Mapping) else None
    rows: dict[tuple[str, str], Mapping[str, Any]] = {}
    if not isinstance(results, list):
        return rows
    for row in results:
        if not isinstance(row, Mapping):
            continue
        data = row.get("data")
        if not isinstance(data, Mapping):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        exchange = str(row.get("exchange") or "").strip().upper()
        if symbol and exchange:
            rows[(symbol, exchange)] = data
    return rows


def _subscription_list(pairs: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """The exact set of instruments a card subscribes, de-duplicated.

    Computed here rather than in the renderer, because a combination card's
    subscriptions are the union of its legs and its underlying and one of them
    is frequently both. Working that out in the client is a step that can be
    got wrong once per renderer.

    Args:
        pairs: Anything carrying a ``symbol`` and an ``exchange``.

    Returns:
        One entry per distinct pair, in first-seen order.
    """
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for pair in pairs:
        symbol = str(pair.get("symbol") or "").strip().upper()
        exchange = str(pair.get("exchange") or "").strip().upper()
        key = (symbol, exchange)
        if not symbol or not exchange or key in seen:
            continue
        seen.add(key)
        out.append({"symbol": symbol, "exchange": exchange})
    return out


def _formula_text(legs: Sequence[Mapping[str, Any]], constant: float | None) -> str:
    """Write the formula out the way a reader would say it.

    Args:
        legs: The resolved legs, each carrying ``multiplier`` and ``symbol``.
        constant: The constant added to the sum, or None.

    Returns:
        Something like ``24500 + NIFTY...CE - NIFTY...PE``. Display only: the
        renderer evaluates from ``multiplier``, never by parsing this. The
        constant is written plainly, without thousands separators, because it
        is a term in a formula rather than a price on a tile.
    """
    parts: list[str] = []
    if constant:
        parts.append(f"{constant:g}")
    for leg in legs:
        multiplier = as_number(leg.get("multiplier")) or 0
        sign = "-" if multiplier < 0 else "+"
        size = abs(multiplier)
        scale = "" if size == 1 else f"{size:g} x "
        symbol = str(leg.get("symbol") or "")
        parts.append(f"{sign} {scale}{symbol}" if parts else f"{scale}{symbol}")
    return " ".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# The toolkit
# ---------------------------------------------------------------------------


class LiveToolkit(OpenAlgoToolkit):
    """Two live cards, resolved and seeded here and streamed by the client.

    Read-only, so no tool here requires confirmation and none writes an audit
    row. Each returns a short confirmation and leaves the card on the run's
    sink for ``services/agent/viz_sink.py`` to turn into a frame.
    """

    def __init__(self, context: ToolContext) -> None:
        """Register the two live card tools.

        The sink is bound before ``super().__init__`` because agno introspects
        the bound methods the moment it receives them, and a method reading an
        attribute the instance does not have yet would fail during registration
        rather than during a call.

        Args:
            context: The run's tool context. Its ``extras`` carry the sink the
                surface created for this run.
        """
        self._sink = sink_of(context)

        super().__init__(context, name="live", tools=[self.stream_quotes, self.stream_combo])

    # -- tool one: the live quotes card --------------------------------------

    def stream_quotes(self, symbols: list[str | dict[str, str]], mode: str = DEFAULT_MODE) -> str:
        """Open a live streaming card for a list of instruments.

        This is the tool for watch, track, monitor, stream, live and "keep an
        eye on". The card subscribes to the broker feed in the browser and
        updates on its own for as long as the message is on screen, so the
        operator watches it rather than asking you again.

        For **one** instrument asked about **once**, use ``show_instrument``
        instead: it draws the full card, with the day's range, an intraday
        chart, the 52 week high and low, the order book and the operator's own
        position. Use this one when there are several instruments, or when the
        operator asked to watch rather than to know.

        Every symbol is resolved against the instrument master first. One that
        does not resolve is named back to you and left off the card, because a
        subscription that never ticks looks exactly like a dead feed; the rest
        still stream. The card is seeded with a snapshot, so it renders
        complete even outside market hours, and it carries the trading session
        so it can say the market is closed rather than showing a still price.

        Args:
            symbols: The instruments to watch, as a list of objects each
                carrying a ``symbol`` and an ``exchange``, for example
                ``[{"symbol": "RELIANCE", "exchange": "NSE"}, {"symbol":
                "NIFTY", "exchange": "NSE_INDEX"}]``. A plain ``"NSE:INFY"``
                string is accepted in place of an object. Both fields are
                required on every entry; the exchange is not inherited from the
                entry before it. When the operator did not name an exchange,
                use NSE for an Indian share and the index code for an index,
                say which you used, and open the card: do not stop to ask,
                because a symbol listed on both NSE and BSE is the normal case
                rather than an ambiguity worth a turn. At most 12 instruments,
                or 4 in Depth mode, and anything past that is dropped rather
                than refused.
            mode: How much each tick carries. ``LTP`` is the last traded price
                only. ``Quote``, the default, adds the day's open, high, low,
                volume and the best bid and ask, which is what a watchlist row
                shows. ``Depth`` adds the five level order book, and is worth
                the extra weight only when the question is about liquidity or
                the spread.

        Returns:
            One line naming what is on the card and the price each instrument
            opened at, plus any symbol that was refused. Those prices are the
            snapshot the card was seeded with, not current values: the card
            updates on the operator's screen, so describe what they can watch
            rather than quoting a price as though it were now.
        """
        mode = normalise_mode(mode)
        limit = MAX_LIVE_DEPTH_SYMBOLS if mode == "Depth" else MAX_LIVE_SYMBOLS
        pairs, notices = symbol_pairs(symbols, limit=limit, truncate=True)

        resolved: list[dict[str, str]] = []
        refused: list[dict[str, str]] = []
        for pair in pairs:
            if is_listed(pair["symbol"], pair["exchange"]):
                resolved.append(pair)
            else:
                refused.append(
                    {
                        "symbol": pair["symbol"],
                        "exchange": pair["exchange"],
                        "reason": "no row in the instrument master, so it would never tick",
                    }
                )

        if not resolved:
            named = ", ".join(f"{row['symbol']} on {row['exchange']}" for row in refused)
            return tool_answer(
                "stream_quotes",
                f"None of the instruments asked for are in the instrument master ({named}), so "
                "no card was opened. Check the spelling and the exchange with search_symbols, "
                "and do not tell the operator anything is streaming.",
                notices,
            )

        instruments = self._seed_instruments(resolved, mode, notices)
        spec: dict[str, Any] = {
            "mode": mode,
            "currency": CURRENCY,
            "account_mode": current_mode(self.analyzer_mode),
            "as_of": datetime.now(IST).isoformat(timespec="seconds"),
            "timezone": _TIMEZONE,
            "instruments": instruments,
            "subscribe": _subscription_list(instruments),
            "market": self._market(row["exchange"] for row in resolved),
        }
        if refused:
            spec["refused"] = refused
        if notices:
            spec["notices"] = list(notices)

        drawn = emit(
            self._sink,
            tool="stream_quotes",
            kind=LIVE_QUOTES_VIZ,
            spec=json_safe(spec),
            title=self._quotes_title(instruments, mode),
            source="quotes_service, depth_service, market_calendar_service",
        )
        if not drawn:
            return tool_answer("stream_quotes", _NO_SINK_QUOTES, notices)

        return tool_answer(
            "stream_quotes",
            self._quotes_confirmation(instruments, refused, mode, spec["market"]),
            notices,
            count=len(instruments),
            mode=mode,
        )

    # -- tool two: the derived live card --------------------------------------

    def stream_combo(
        self,
        underlying: str = "",
        exchange: str = "",
        structure: str = "straddle",
        expiry: str = _DEFAULT_EXPIRY_CHOICE,
        width: int = 1,
        legs: list[str | dict[str, str | int]] | None = None,
    ) -> str:
        """Open a live card showing one derived value recomputed on every tick.

        "The live ATM straddle of NIFTY this week" is not a list of quotes: it
        is one number, and it moves whenever either leg moves. This tool
        resolves the legs, states the formula, and the card evaluates it per
        tick in the browser. The same shape covers a strangle, a vertical
        spread, a ratio and a synthetic basis, so reach for it whenever the
        operator wants to watch a **combination** rather than instruments side
        by side.

        The value is always ``constant + sum(multiplier x price)``, where a
        bought leg counts positive and a sold leg negative. Nothing about the
        number is yours to compute or to state: the expiry, the spot, the ATM
        strike, the strike interval, the option symbols and the seeded premiums
        are all fetched here.

        **The legs are pinned at resolution.** If spot later moves to a
        different strike the card says so rather than quietly relabelling
        itself as a different straddle, because resubscribing would change what
        the number means while the operator was watching it.

        Sensible defaults, so this usually answers in one call: the ATM
        straddle, the current week's expiry, and whichever exchange the
        underlying is listed on. The result says exactly which expiry date and
        which strike were used, so correct it on a second call only if the
        operator meant something else.

        Args:
            underlying: The underlying: ``NIFTY``, ``BANKNIFTY``, ``SENSEX``,
                ``RELIANCE``, ``CRUDEOIL``. Required unless ``legs`` names the
                contracts outright.
            exchange: Exchange of the **underlying**, not of the options:
                ``NSE_INDEX`` for NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY;
                ``BSE_INDEX`` for SENSEX and BANKEX; ``NSE`` or ``BSE`` for a
                stock; ``MCX`` for a commodity. Leave it empty to have it
                looked up in the instrument master, which is right almost
                always.
            structure: Which combination to build: ``straddle`` (the default,
                the ATM call plus the ATM put), ``strangle``, ``call_spread``,
                ``put_spread``, ``call_ratio``, ``put_ratio``, ``synthetic``
                (the synthetic future, strike plus call less put) or ``basis``
                (that synthetic less spot). Ignored when ``legs`` is given.
            expiry: ``current_week`` (the default, the nearest listed expiry),
                ``next_week``, ``current_month``, ``next_month``, or an exact
                date in DDMMMYY form such as ``09SEP26``. Every one of these
                is resolved against the expiries actually listed, and the
                result names the date that was picked.
            width: How many strikes out of the money the wing legs sit, for the
                structures that have one: the strangle, the spreads and the
                ratios. Defaults to 1, meaning the first strike out. Ignored by
                the straddle, the synthetic and the basis.
            legs: The exact contracts to combine, instead of a named structure.
                At most 8, each either an OpenAlgo symbol such as
                ``"NIFTY09SEP2624500CE"``, an exchange-qualified
                ``"NFO:NIFTY09SEP2624500CE"``, the shorthand ``"24500CE"``
                when ``underlying`` and ``expiry`` are both set, or an object
                such as ``{"symbol": "NIFTY09SEP2624500CE", "side": "SELL",
                "lots": 2}``. ``side`` defaults to BUY, so a plain list of two
                symbols is their sum and a sold leg is subtracted.

        Returns:
            One line naming the structure, the expiry and strike that were
            picked, the legs, and the value the card was seeded with. That
            value is the one the card opened at, not the current one, so
            describe what the operator can watch rather than quoting it as
            though it were now.
        """
        notices: list[str] = []
        entries = leg_entries(legs, "legs")
        if entries:
            return self._custom_combo(entries, underlying, expiry, notices)
        return self._named_structure(underlying, exchange, structure, expiry, width, notices)

    # -- tool one: seeding ---------------------------------------------------

    def _seed_instruments(
        self, pairs: Sequence[Mapping[str, str]], mode: str, notices: list[str]
    ) -> list[dict[str, Any]]:
        """Build one card row per instrument, seeded from a snapshot.

        Args:
            pairs: The resolved instruments.
            mode: The subscription mode, which decides whether a ladder is
                seeded as well as a quote.
            notices: Collected notices, appended to.

        Returns:
            One row per instrument, in the order asked for. A row whose
            snapshot failed is still on the card, carrying its reason in
            ``unavailable`` rather than a fabricated price.
        """
        quoted = self._snapshot(pairs, notices)

        rows: list[dict[str, Any]] = []
        for pair in pairs:
            symbol = pair["symbol"]
            exchange = pair["exchange"]
            row: dict[str, Any] = {
                "symbol": symbol,
                "exchange": exchange,
                "calendar_exchange": calendar_exchange(exchange),
                "is_index": exchange in INDEX_EXCHANGES,
                "is_derivative": exchange in DERIVATIVE_EXCHANGES,
            }
            unavailable: dict[str, str] = {}

            raw = quoted.get((symbol, exchange))
            if raw is None:
                unavailable["seed"] = "the broker returned no quote for this instrument"
            else:
                quote = normalise_quote(raw)
                row["seed"] = quote
                row.update(quote_move(quote, notices, symbol=symbol))

            if mode == "Depth":
                ladder, reason = self._ladder(symbol, exchange)
                if ladder is not None:
                    row["depth"] = ladder
                elif reason:
                    unavailable["depth"] = reason

            if unavailable:
                row["unavailable"] = unavailable
            rows.append(row)
        return rows

    def _snapshot(
        self, pairs: Sequence[Mapping[str, str]], notices: list[str]
    ) -> dict[tuple[str, str], Mapping[str, Any]]:
        """Fetch one batched quote for every instrument on a card.

        The whole snapshot is one broker request, and a failure costs the seed
        rather than the card: an unseeded card still subscribes and fills in on
        the first tick, which is strictly better than refusing to open.

        Args:
            pairs: The resolved instruments.
            notices: Collected notices, appended to when the snapshot fails.

        Returns:
            The quotes, keyed by pair. Empty when the request failed.
        """
        try:
            response = self.service_call(
                quotes_service.get_multiquotes, symbols=[dict(pair) for pair in pairs]
            )
        except Exception as exc:
            logger.exception("Agent live card could not seed a snapshot")
            notices.append(
                f"The opening snapshot could not be read ({type(exc).__name__}), so the card "
                "starts empty and fills in on the first tick."
            )
            return {}
        return _quote_rows(response)

    def _ladder(self, symbol: str, exchange: str) -> tuple[dict[str, Any] | None, str | None]:
        """Seed one instrument's order book.

        Args:
            symbol: The OpenAlgo symbol.
            exchange: The exchange it is listed on.

        Returns:
            The ladder, or None and the reason there is none. An index has no
            order book at all, which is a fact about the instrument rather than
            a failure.
        """
        try:
            response = self.service_call(depth_service.get_depth, symbol=symbol, exchange=exchange)
        except Exception as exc:
            logger.exception("Agent live card could not seed depth for %s %s", symbol, exchange)
            return None, f"the order book could not be read ({type(exc).__name__})"

        data = response.get("data") if isinstance(response, Mapping) else response
        if not isinstance(data, Mapping):
            return None, "the broker returned no order book for this instrument"

        bids = depth_levels(data.get("bids"))
        asks = depth_levels(data.get("asks"))
        if not bids and not asks:
            return None, "there are no resting orders on either side"

        ladder: dict[str, Any] = {"bids": bids, "asks": asks}
        for field, value in (
            ("total_buy_quantity", as_number(data.get("totalbuyqty"))),
            ("total_sell_quantity", as_number(data.get("totalsellqty"))),
        ):
            if value is not None:
                ladder[field] = value
        return ladder, None

    # -- tool two: the named structures --------------------------------------

    def _named_structure(
        self,
        underlying: Any,
        exchange: Any,
        structure: Any,
        expiry: Any,
        width: Any,
        notices: list[str],
    ) -> str:
        """Build one of the structures in :data:`STRUCTURES`.

        Args:
            underlying: The model's underlying.
            exchange: The model's exchange, or an empty value to resolve one.
            structure: The structure name.
            expiry: The expiry choice or an exact date.
            width: How many strikes out the wing legs sit.
            notices: Collected notices, appended to.

        Returns:
            The wrapped confirmation.
        """
        name = str(structure or "straddle").strip().lower().replace(" ", "_").replace("-", "_")
        chosen = STRUCTURES.get(name)
        if chosen is None:
            invalid_argument(
                "structure",
                f"{name!r} is not a structure this tool builds",
                f"Pass one of {', '.join(sorted(STRUCTURES))}, or name the contracts "
                "themselves in 'legs'.",
            )

        base = normalise_symbol(underlying, "underlying")
        venue = resolve_underlying_exchange(base, exchange, notices)
        listed = listed_expiries(self.service_call, base, venue)
        if not listed:
            invalid_argument(
                "underlying",
                f"{base} lists no option expiries on {get_option_exchange(venue)}",
                "Confirm the underlying has listed options, or watch the instruments "
                "themselves with stream_quotes.",
            )
        settled = self._settle_expiry(listed, expiry, notices)

        steps = normalise_int(width, "width", 1, 20) if chosen.needs_width else 1
        if not chosen.needs_width and as_number(width) not in (None, 1):
            notices.append(f"A {name} has no out of the money leg, so 'width' was not used.")

        spot_symbol, spot_exchange = self._spot_instrument(base, venue)
        spot = self._spot_price(spot_symbol, spot_exchange)

        ladder = self.service_call(
            get_available_strikes, base, settled, "CE", get_option_exchange(venue)
        )
        strikes = ladder if isinstance(ladder, list) else []
        atm_strike = find_atm_strike_from_actual(spot, strikes) if strikes else None
        interval = strike_spacing(strikes)

        resolved: list[dict[str, Any]] = []
        for index, template in enumerate(chosen.legs, start=1):
            if template.kind == "spot":
                resolved.append(self._spot_leg(template, spot_symbol, spot_exchange))
                continue
            resolved.append(self._option_leg(template, base, venue, settled, steps, spot, index))

        return self._deliver_combo(
            structure=name,
            summary=chosen.summary,
            constant_rule=chosen.constant,
            base=base,
            venue=venue,
            expiry=settled,
            expiry_choice=str(expiry or _DEFAULT_EXPIRY_CHOICE).strip().lower(),
            legs=resolved,
            spot_symbol=spot_symbol,
            spot_exchange=spot_exchange,
            spot=spot,
            atm_strike=as_number(atm_strike),
            interval=interval,
            claims_atm=any(t.offset == "ATM" for t in chosen.legs),
            notices=notices,
        )

    def _custom_combo(
        self, entries: Sequence[Any], underlying: Any, expiry: Any, notices: list[str]
    ) -> str:
        """Build a combination from the contracts the operator named.

        Args:
            entries: The raw ``legs`` entries.
            underlying: The model's underlying, used only to expand a shorthand
                leg such as ``24500CE``.
            expiry: The model's expiry, used for the same.
            notices: Collected notices, appended to.

        Returns:
            The wrapped confirmation.
        """
        base = str(underlying or "").strip().upper()
        shorthand = str(expiry or "").strip().upper()
        if shorthand and shorthand in _EXPIRY_CHOICES:
            # A shorthand leg needs a real date to expand against, and a
            # keyword is not one. The named contracts carry their own expiry,
            # so this only ever costs the shorthand spelling.
            shorthand = ""

        resolved: list[dict[str, Any]] = []
        for index, entry in enumerate(entries, start=1):
            symbol, venue = leg_symbol(entry, index, base, shorthand)
            contract = resolve_contract(self.service_call, symbol, venue, f"leg {index}")
            side = leg_side(entry.get("side") if isinstance(entry, Mapping) else None, index)
            lots = leg_lots(entry.get("lots") if isinstance(entry, Mapping) else None, index)
            resolved.append(self._leg_row(contract, side, lots, "named"))

        underlyings = {str(leg.get("base") or "") for leg in resolved}
        first = resolved[0]
        if len(underlyings) > 1:
            notices.append(
                "The legs span "
                + ", ".join(sorted(name for name in underlyings if name))
                + ", so the card shows their combined value against "
                f"{first.get('base')}, which is the underlying it is centred on."
            )

        combo_base = str(first.get("base") or "")
        combo_venue = str(first.get("underlying_exchange") or "")
        spot_symbol, spot_exchange = self._spot_instrument(combo_base, combo_venue)
        spot = self._spot_price(spot_symbol, spot_exchange, required=False)

        settled = str(first.get("expiry") or "")
        interval = None
        atm_strike = None
        if spot is not None and settled and combo_base:
            ladder = self.service_call(
                get_available_strikes, combo_base, settled, "CE", get_option_exchange(combo_venue)
            )
            strikes = ladder if isinstance(ladder, list) else []
            atm_strike = as_number(find_atm_strike_from_actual(spot, strikes)) if strikes else None
            interval = strike_spacing(strikes)

        return self._deliver_combo(
            structure=CUSTOM_STRUCTURE,
            summary="the contracts the operator named, bought legs added and sold legs subtracted",
            constant_rule="",
            base=combo_base,
            venue=combo_venue,
            expiry=settled,
            expiry_choice="named",
            legs=resolved,
            spot_symbol=spot_symbol,
            spot_exchange=spot_exchange,
            spot=spot,
            atm_strike=atm_strike,
            interval=interval,
            claims_atm=False,
            notices=notices,
        )

    # -- tool two: resolution ------------------------------------------------

    def _settle_expiry(self, listed: Sequence[str], value: Any, notices: list[str]) -> str:
        """Turn an expiry choice into one of the expiries actually listed.

        "Current week" has to come out as a real date or the card is naming a
        contract that does not exist, so every branch here picks from
        ``listed`` and says which date it picked.

        Args:
            listed: The listed expiries in ``DDMMMYY`` form, nearest first.
            value: The model's choice or an exact date.
            notices: Collected notices, appended to.

        Returns:
            One of ``listed``.

        Raises:
            RetryAgentRun: If an exact date was named and is not listed.
        """
        text = str(value or _DEFAULT_EXPIRY_CHOICE).strip().lower().replace(" ", "_")
        text = text.replace("-", "_")

        if text in ("", "current_week", "nearest", "weekly", "this_week"):
            picked = listed[0]
            if _within_this_week(picked):
                notices.append(f"{picked} is this week's expiry and was used.")
            else:
                # "Current week" has to come out as a contract that exists. A
                # stock lists monthly expiries only, and this week's index
                # expiry is behind us by Wednesday evening, so saying "the
                # current week" back would name a date nothing trades on.
                notices.append(
                    f"No expiry is listed inside the current week, so {picked}, the nearest "
                    "listed one, was used."
                )
            return picked

        if text in ("next_week", "next"):
            picked = listed[1] if len(listed) > 1 else listed[0]
            if picked == listed[0]:
                notices.append(
                    f"{picked} is the only listed expiry, so the next one could not be used."
                )
            else:
                notices.append(f"{picked} is the next listed expiry after {listed[0]}.")
            return picked

        if text in ("current_month", "monthly", "this_month", "next_month"):
            picked = self._monthly(listed, later=text == "next_month")
            notices.append(
                f"{picked} is the last expiry listed in "
                f"{'the following' if text == 'next_month' else 'the current'} contract month."
            )
            return picked

        exact = normalise_expiry(text.upper(), "", allow_embedded=False)
        if exact not in listed:
            invalid_argument(
                "expiry",
                f"{exact} is not a listed expiry",
                "The listed ones are " + ", ".join(listed[:8]) + ". Pass one of those, or one "
                f"of {', '.join(_EXPIRY_CHOICES)}.",
            )
        return exact

    @staticmethod
    def _monthly(listed: Sequence[str], *, later: bool) -> str:
        """The last expiry listed in a contract month.

        Args:
            listed: The listed expiries, nearest first.
            later: True for the month after the nearest expiry's month.

        Returns:
            The last expiry of that month, falling back to the last listed
            expiry when the month has none.
        """
        months: list[str] = []
        for entry in listed:
            month = entry[2:]
            if month not in months:
                months.append(month)
        wanted = months[1] if later and len(months) > 1 else months[0]
        matching = [entry for entry in listed if entry[2:] == wanted]
        return matching[-1] if matching else listed[-1]

    def _spot_instrument(self, base: str, venue: str) -> tuple[str, str]:
        """The instrument the underlying is actually quoted on.

        A commodity or a currency has no spot instrument, so its reference
        price is the near month future, which is what the option chain, the IV
        surface and the straddle charts already use. That mapping belongs to
        ``option_symbol_service`` and is read from there rather than repeated.

        Args:
            base: The underlying.
            venue: The underlying's exchange.

        Returns:
            The symbol and exchange to quote and to subscribe for spot.

        Raises:
            RetryAgentRun: If a no-spot exchange lists no unexpired future.
        """
        if venue not in NO_SPOT_EXCHANGES:
            return base, venue

        resolved = resolve_underlying_quote(base, venue)
        if not resolved:
            invalid_argument(
                "underlying",
                f"{base} has no unexpired futures contract on {venue}, and {venue} lists no "
                "spot instrument",
                "Check the underlying, or re-download the master contract.",
            )
        return resolved[0], resolved[1]

    def _spot_price(self, symbol: str, exchange: str, *, required: bool = True) -> float | None:
        """Read the underlying's last traded price.

        Args:
            symbol: The spot instrument.
            exchange: Its exchange.
            required: True when the card cannot be drawn without it, which is
                the case for every structure resolved from an ATM offset.

        Returns:
            The price, or None when it could not be read and it was optional.

        Raises:
            RetryAgentRun: When it is required and nothing came back. Every
                strike on the card is chosen relative to spot, so guessing one
                would put the card on contracts nobody asked for.
        """
        response = self.service_call(quotes_service.get_quotes, symbol=symbol, exchange=exchange)
        data = response.get("data") if isinstance(response, Mapping) else response
        price = as_number(data.get("ltp")) if isinstance(data, Mapping) else None
        if price is not None and price > 0:
            return price
        if not required:
            return None
        invalid_argument(
            "underlying",
            f"{symbol} on {exchange} returned no last traded price, so the ATM strike cannot "
            "be chosen",
            "Say the underlying could not be priced rather than naming a strike, and check "
            "the instrument is one this broker quotes.",
        )

    def _option_leg(
        self,
        template: LegTemplate,
        base: str,
        venue: str,
        expiry: str,
        width: int,
        spot: float,
        position: int,
    ) -> dict[str, Any]:
        """Resolve one option leg of a named structure.

        The strike is never worked out here. ``get_option_symbol`` picks it from
        the strikes the master actually lists, at the offset the template asks
        for, which is what makes this correct for an underlying whose strike
        interval nobody remembers.

        Args:
            template: The leg's template.
            base: The underlying.
            venue: The underlying's exchange.
            expiry: The settled expiry, in DDMMMYY form.
            width: How many strikes out an out of the money leg sits.
            spot: The underlying's last traded price, passed through so the
                resolver does not quote it again once per leg.
            position: The leg's place in the structure, for a failure message.

        Returns:
            The resolved leg row.
        """
        offset = template.offset.format(width=width)
        payload = self.service_call(
            get_option_symbol,
            underlying=base,
            exchange=venue,
            expiry_date=expiry,
            strike_int=None,
            offset=offset,
            option_type=template.option_type,
            underlying_ltp=spot,
        )
        symbol = str(payload.get("symbol") or "").strip().upper()
        listed_on = str(payload.get("exchange") or "").strip().upper()
        if not symbol:
            invalid_argument(
                "structure",
                f"leg {position} ({offset} {template.option_type}) resolved to no contract",
                "Try a nearer expiry, a smaller width, or watch the instruments themselves "
                "with stream_quotes.",
            )

        contract = resolve_contract(
            self.service_call, symbol, listed_on, f"the {offset} {template.option_type} leg"
        )
        row = self._leg_row(contract, template.side, template.lots, "structure")
        row["role"] = f"{offset.lower()}_{'call' if template.option_type == 'CE' else 'put'}"
        return row

    def _spot_leg(self, template: LegTemplate, symbol: str, exchange: str) -> dict[str, Any]:
        """Build the underlying itself as a leg.

        A basis is the synthetic future less spot, so spot has to be able to be
        a leg. Modelling it as one rather than as a special case in the formula
        is what keeps the client's evaluation a single signed sum.

        Args:
            template: The leg's template.
            symbol: The spot instrument.
            exchange: Its exchange.

        Returns:
            The leg row. It carries no strike, expiry or lot size, because the
            underlying has none.
        """
        return {
            "symbol": symbol,
            "exchange": exchange,
            "segment": "SPOT",
            "side": template.side,
            "lots": template.lots,
            "multiplier": signed_multiplier(template.side, template.lots),
            "origin": "structure",
            "role": "spot",
        }

    @staticmethod
    def _leg_row(contract: Mapping[str, Any], side: str, lots: int, origin: str) -> dict[str, Any]:
        """Turn a resolved contract into a card leg.

        Args:
            contract: The master's own row for the contract.
            side: ``BUY`` or ``SELL``.
            lots: How many of this leg.
            origin: ``structure`` or ``named``, so the card can say whether the
                operator chose the contract or the structure did.

        Returns:
            The leg row, carrying ``multiplier``, which is the only field the
            renderer needs to evaluate the formula.
        """
        row: dict[str, Any] = {
            "symbol": contract["symbol"],
            "exchange": contract["exchange"],
            "segment": contract.get("segment") or "",
            "side": side,
            "lots": lots,
            "multiplier": signed_multiplier(side, lots),
            "origin": origin,
            "role": "named",
        }
        for source, target in (
            ("option_type", "option_type"),
            ("strike", "strike"),
            ("expiry", "expiry"),
            ("lotSize", "lot_size"),
            ("tickSize", "tick_size"),
            ("base", "base"),
            ("underlying_exchange", "underlying_exchange"),
        ):
            value = contract.get(source)
            if value not in (None, ""):
                row[target] = value
        return row

    # -- tool two: delivery --------------------------------------------------

    def _deliver_combo(
        self,
        *,
        structure: str,
        summary: str,
        constant_rule: str,
        base: str,
        venue: str,
        expiry: str,
        expiry_choice: str,
        legs: list[dict[str, Any]],
        spot_symbol: str,
        spot_exchange: str,
        spot: float | None,
        atm_strike: float | None,
        interval: float | None,
        claims_atm: bool,
        notices: list[str],
    ) -> str:
        """Seed the legs, assemble the card and put it on the run's sink.

        Args:
            structure: The structure's name, or ``custom``.
            summary: One line saying what the number means.
            constant_rule: ``strike`` when the value is quoted relative to the
                option legs' strike, empty otherwise.
            base: The underlying.
            venue: The underlying's exchange.
            expiry: The settled expiry.
            expiry_choice: What the operator asked for, so the card can show
                both the request and the date it became.
            legs: The resolved legs.
            spot_symbol: The instrument spot is read from.
            spot_exchange: Its exchange.
            spot: The seeded spot price.
            atm_strike: The ATM strike at resolution.
            interval: The listed strike interval.
            claims_atm: True when at least one leg was resolved at the ATM, so
                the card's own label depends on the strike still being the ATM.
            notices: Collected notices, appended to.

        Returns:
            The wrapped confirmation.
        """
        if len(legs) > MAX_LEGS:
            notices.append(
                f"{len(legs) - MAX_LEGS} of {len(legs)} legs were dropped, because one card "
                f"carries at most {MAX_LEGS}."
            )
            legs = legs[:MAX_LEGS]

        pairs = [{"symbol": leg["symbol"], "exchange": leg["exchange"]} for leg in legs]
        pairs.append({"symbol": spot_symbol, "exchange": spot_exchange})
        quoted = self._snapshot(_subscription_list(pairs), notices)

        seeded = 0
        for leg in legs:
            raw = quoted.get((leg["symbol"], leg["exchange"]))
            if raw is None:
                continue
            quote = normalise_quote(raw)
            leg["seed"] = quote
            if as_number(quote.get("ltp")) is not None:
                seeded += 1

        constant = None
        if constant_rule == "strike":
            option_strikes = {
                as_number(leg.get("strike"))
                for leg in legs
                if leg.get("segment") == "OPTION" and leg.get("strike") is not None
            }
            if len(option_strikes) == 1:
                constant = option_strikes.pop()
            else:
                notices.append(
                    "The option legs sit at different strikes, so the value is shown as the "
                    "net premium rather than as a price."
                )

        value = None
        if seeded == len(legs) and legs:
            total = float(constant or 0.0)
            for leg in legs:
                price = as_number((leg.get("seed") or {}).get("ltp"))
                total += float(leg["multiplier"]) * float(price or 0.0)
            value = round(total, 4)

        spot_row: dict[str, Any] = {"symbol": spot_symbol, "exchange": spot_exchange}
        spot_quote = quoted.get((spot_symbol, spot_exchange))
        if spot_quote is not None:
            spot_row["seed"] = normalise_quote(spot_quote)
        if spot is not None:
            spot_row["ltp"] = spot

        lot_sizes = {int(leg["lot_size"]) for leg in legs if leg.get("lot_size")}

        spec: dict[str, Any] = {
            "structure": structure,
            "summary": summary,
            "label": self._combo_label(structure, base, expiry, atm_strike, claims_atm),
            "underlying": base,
            "underlying_exchange": venue,
            "expiry": expiry,
            "expiry_choice": expiry_choice,
            "mode": COMBO_MODE,
            "currency": CURRENCY,
            "account_mode": current_mode(self.analyzer_mode),
            "as_of": datetime.now(IST).isoformat(timespec="seconds"),
            "timezone": _TIMEZONE,
            "spot": spot_row,
            "legs": legs,
            "formula": {
                "kind": "signed_sum",
                "constant": constant,
                "per": "unit",
                "expression": _formula_text(legs, constant),
            },
            "seed": {"value": value, "complete": value is not None, "legs_priced": seeded},
            "subscribe": _subscription_list(pairs),
            "market": self._market(
                [leg["exchange"] for leg in legs] + [spot_exchange],
            ),
        }
        if len(lot_sizes) == 1:
            spec["lot_size"] = lot_sizes.pop()
        if atm_strike is not None:
            spec["atm"] = {
                "strike": atm_strike,
                "strike_interval": interval,
                "spot_at_resolution": spot,
                "roll_threshold": round(interval / 2.0, 4) if interval else None,
                "pinned": True,
                "claims_atm": claims_atm,
            }
        if notices:
            spec["notices"] = list(notices)

        drawn = emit(
            self._sink,
            tool="stream_combo",
            kind=LIVE_COMBO_VIZ,
            spec=json_safe(spec),
            title=spec["label"],
            source=(
                "quotes_service, option_symbol_service, expiry_service, symbol_service, "
                "market_calendar_service"
            ),
        )
        if not drawn:
            return tool_answer("stream_combo", _NO_SINK_COMBO, notices)

        return tool_answer(
            "stream_combo",
            self._combo_confirmation(spec, legs, value, spot),
            notices,
            underlying=base or None,
            expiry=expiry or None,
        )

    # -- market status -------------------------------------------------------

    def _market(self, exchanges: Any) -> dict[str, Any]:
        """Read today's trading session for every exchange on a card.

        Carried so the renderer can say the market is closed rather than
        showing a still price as though it were live. Both the window and the
        verdict travel: a card outlives the moment it was drawn, so the client
        recomputes from ``opens_at`` and ``closes_at`` and uses ``is_open``
        only as the value at resolution.

        Args:
            exchanges: The exchange codes on the card, in any order and with
                repeats.

        Returns:
            The session block. A lookup that fails costs the block its
            certainty, never the card: every exchange then reports
            ``known: false`` and the renderer says nothing about the session.
        """
        now = datetime.now(IST)
        today = now.date().isoformat()
        wanted: list[str] = []
        for entry in exchanges:
            venue = calendar_exchange(str(entry or "").strip().upper())
            if venue and venue not in wanted:
                wanted.append(venue)

        block: dict[str, Any] = {
            "date": today,
            "as_of": now.isoformat(timespec="seconds"),
            "timezone": _TIMEZONE,
        }

        timings: dict[str, Mapping[str, Any]] = {}
        holiday: bool | None = None
        try:
            payload = self.service_call(get_timings, date_str=today)
            rows = payload.get("data") if isinstance(payload, Mapping) else None
            for row in rows if isinstance(rows, list) else []:
                if isinstance(row, Mapping):
                    timings[str(row.get("exchange") or "").strip().upper()] = row
            answer = self.service_call(check_holiday, date_str=today)
            data = answer.get("data") if isinstance(answer, Mapping) else None
            if isinstance(data, Mapping):
                holiday = bool(data.get("is_holiday"))
        except Exception:
            logger.exception("Agent live card could not read the market calendar")
            block["known"] = False
            block["exchanges"] = [{"exchange": venue, "known": False} for venue in wanted]
            return block

        now_ms = int(now.timestamp() * 1000)
        rows_out: list[dict[str, Any]] = []
        for venue in wanted:
            row = timings.get(venue)
            if row is None:
                rows_out.append({"exchange": venue, "known": False, "is_open": False})
                continue
            opens = _epoch_ms(row.get("start_time"))
            closes = _epoch_ms(row.get("end_time"))
            rows_out.append(
                {
                    "exchange": venue,
                    "known": True,
                    "is_open": bool(opens and closes and opens <= now_ms <= closes),
                    "opens_at": opens,
                    "closes_at": closes,
                }
            )

        block["known"] = True
        block["exchanges"] = rows_out
        block["is_open"] = any(row.get("is_open") for row in rows_out)
        if holiday is not None:
            block["is_holiday"] = holiday
        return block

    # -- the model's answer --------------------------------------------------

    @staticmethod
    def _quotes_title(instruments: Sequence[Mapping[str, Any]], mode: str) -> str:
        """Name a quotes card.

        Args:
            instruments: The rows on the card.
            mode: The subscription mode.

        Returns:
            The heading shown above the card.
        """
        names = [str(row.get("symbol") or "") for row in instruments]
        listed = ", ".join(names[:3])
        if len(names) > 3:
            listed = f"{listed} and {len(names) - 3} more"
        return f"Live {mode}: {listed}"

    @staticmethod
    def _quotes_confirmation(
        instruments: Sequence[Mapping[str, Any]],
        refused: Sequence[Mapping[str, str]],
        mode: str,
        market: Mapping[str, Any],
    ) -> str:
        """Write the line the model gets back from a quotes card.

        Args:
            instruments: The rows on the card.
            refused: The instruments that were not subscribed.
            mode: The subscription mode.
            market: The session block.

        Returns:
            The confirmation.
        """
        opened: list[str] = []
        for row in instruments:
            price = as_number((row.get("seed") or {}).get("ltp"))
            where = f"{row.get('symbol')} {row.get('exchange')}"
            opened.append(f"{where} at {format_price(price)}" if price is not None else where)

        parts = [
            f"Opened a live {mode} card on "
            f"{len(instruments)} {'instrument' if len(instruments) == 1 else 'instruments'}: "
            + "; ".join(opened)
            + "."
        ]
        if refused:
            named = ", ".join(f"{row['symbol']} on {row['exchange']}" for row in refused)
            parts.append(
                f"{named} could not be resolved in the instrument master and "
                f"{'is' if len(refused) == 1 else 'are'} not on the card. Say so."
            )
        if market.get("known") and not market.get("is_open"):
            parts.append("Every exchange on the card is outside its trading session right now.")
        parts.append(
            "Those are the values the card opened with, not current ones: it is subscribed and "
            "updates on the operator's screen, so tell them what they can watch rather than "
            "quoting a price as though it were now."
        )
        return " ".join(parts)

    @staticmethod
    def _combo_label(
        structure: str, base: str, expiry: str, strike: float | None, claims_atm: bool
    ) -> str:
        """Name a combination card.

        Args:
            structure: The structure's name, or ``custom``.
            base: The underlying.
            expiry: The settled expiry.
            strike: The ATM strike at resolution.
            claims_atm: True when the structure was built around the ATM.

        Returns:
            The heading, for example ``NIFTY 09SEP26 24500 straddle``. A card
            built from named contracts is a ``combination`` rather than a
            ``custom``, which is the machine value and reads as a setting.
        """
        words = "combination" if structure == CUSTOM_STRUCTURE else structure.replace("_", " ")
        at = f" {strike:g}" if claims_atm and strike is not None else ""
        return " ".join(part for part in (base, expiry, at.strip(), words) if part)

    @staticmethod
    def _combo_confirmation(
        spec: Mapping[str, Any],
        legs: Sequence[Mapping[str, Any]],
        value: float | None,
        spot: float | None,
    ) -> str:
        """Write the line the model gets back from a combination card.

        Args:
            spec: The card being delivered.
            legs: The resolved legs.
            value: The seeded combined value, or None.
            spot: The seeded spot.

        Returns:
            The confirmation.
        """
        described = "; ".join(leg_label(leg) for leg in legs)
        parts = [
            f"Opened a live card on the {spec.get('label')}: {described}."
            if described
            else f"Opened a live card on the {spec.get('label')}."
        ]
        if value is not None:
            parts.append(
                f"It is {spec.get('summary')}, seeded at {format_price(value)}"
                + (f" with spot {format_price(spot)}." if spot is not None else ".")
            )
        else:
            parts.append(
                f"It is {spec.get('summary')}. Not every leg had a traded price, so the card "
                "opens incomplete and fills in on the first tick."
            )

        atm = spec.get("atm")
        if isinstance(atm, Mapping) and atm.get("claims_atm") and atm.get("roll_threshold"):
            parts.append(
                f"The legs are pinned at the {atm['strike']:g} strike. If spot moves more than "
                f"{atm['roll_threshold']:g} away the card says the strike is no longer the ATM "
                "rather than relabelling itself, so it keeps meaning what it meant when it "
                "opened."
            )
        market = spec.get("market")
        if isinstance(market, Mapping) and market.get("known") and not market.get("is_open"):
            parts.append("The exchanges on the card are outside their trading session right now.")
        parts.append(
            "The value recomputes on every tick on the operator's screen, so describe what they "
            "can watch rather than quoting the seeded number as though it were current."
        )
        return " ".join(parts)
