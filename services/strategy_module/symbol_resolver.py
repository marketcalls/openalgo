"""Resolve a strategy leg to a concrete tradable OpenAlgo symbol.

A multi-leg strategy is written in relative terms: "the ATM call of the weekly
expiry, two lots". Nothing can be ordered from that. Before a run starts every
leg has to become an exact contract that the master contract confirms exists,
with the lot size and tick size that contract actually carries.

This module does that translation and nothing else. It reads the master
contract database and may fetch one quote, but it holds no state, starts no
thread, touches no Flask object and never places an order, so a strategy can
resolve its whole basket up front and fail before the first leg is sent. That
matters because a basket fails leg by leg: by the time leg three is refused,
legs one and two are already filled and the position is not the one anybody
chose.

Everything the resolver needs already exists elsewhere and is delegated to:

* ``services.expiry_service.get_expiry_dates`` for the live expiry calendar,
* ``services.option_symbol_service`` for the underlying quote reference, the
  ATM and offset arithmetic, the strikes cache and the symbol construction,
* ``services.quotes_service.get_quotes`` for the underlying LTP.

Two things are worth knowing before reading further.

**Expiry has two spellings.** ``get_expiry_dates`` and ``SymToken.expiry`` use
``DD-MMM-YY`` ("28-APR-26"); an OpenAlgo symbol embeds ``DDMMMYY`` with no
hyphens ("NIFTY28APR2624000CE"). Every result below carries both, ``expiry``
being the exact string the database stores so it can be used as a query filter,
and ``expiry_symbol`` being the form that goes into a symbol.

**Failure is a value, not an exception.** A leg that cannot be resolved comes
back as a result with ``ok=False``, a machine-readable ``code`` and a message
naming what was looked for. Nothing here ever falls back to a plausible-looking
substitute: a wrong lot size or a neighbouring strike is a real position, and
silently trading it is worse than refusing the run.
"""

import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from services import expiry_service, option_symbol_service, quotes_service
from services.flow_node_contracts import parse_underlying_symbol
from utils.logging import get_logger

logger = get_logger(__name__)

#: Expiry ranks a leg may ask for.
#:
#: MCX commodities each run their own cycle - GOLDM and CRUDEOIL do not share a
#: calendar, and neither is weekly in the NFO sense - so the ranks are
#: positional rather than named. ``current`` and ``next`` are the segment
#: neutral spelling of ``weekly`` and ``next_week``, and resolve identically.
EXPIRY_RANKS = ("weekly", "next_week", "monthly", "next_month", "current", "next")

#: Segments a leg may trade.
SEGMENTS = ("cash", "futures", "options")

#: How an option leg names its strike.
STRIKE_MODES = ("atm", "strike")

#: Offsets from the money, in strike steps. Bounded at five because a basket
#: that reaches further than that is nearly always a typo, and an unbounded
#: offset silently walks off the end of a thin chain.
ATM_OFFSET_PATTERN = re.compile(r"^(ATM|ITM[1-5]|OTM[1-5])$")

#: Exchanges that list derivatives under their own code. An exchange already in
#: this set is used as given rather than being run through the underlying to
#: derivatives mapping, which would log a misleading "unknown exchange" warning.
DERIVATIVE_EXCHANGES = frozenset({"NFO", "BFO", "MCX", "CDS", "NCO", "BCD", "NCDEX", "CRYPTO"})

#: An index has no cash instrument of its own, so a cash leg on an index
#: underlying trades the equity segment of the same exchange. NIFTY resolves to
#: nothing there and is refused by name, which is the correct answer: the index
#: itself is not tradable.
CASH_EXCHANGE_FOR = {"NSE_INDEX": "NSE", "BSE_INDEX": "BSE"}

#: Expiries written literally on a leg, in either spelling and with a two or
#: four digit year.
_LITERAL_EXPIRY_PATTERN = re.compile(r"^(\d{2})-?([A-Za-z]{3})-?(\d{2}|\d{4})$")

_EXPIRY_INPUT_FORMATS = ("%d-%b-%y", "%d-%b-%Y", "%d%b%y", "%d%b%Y")


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExpiryResult:
    """One resolved expiry, in both the database and the symbol spelling."""

    ok: bool
    rank: str
    expiry: str | None = None
    expiry_symbol: str | None = None
    available: tuple[str, ...] = ()
    #: True when the requested rank did not exist and the nearest one was used
    #: instead: a single expiry answers ``next_week``, a single monthly answers
    #: ``next_month``. Recorded rather than hidden so a caller can say so.
    fallback: bool = False
    error: str | None = None
    code: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UnderlyingQuote:
    """The instrument an ATM strike is measured against, and its last price."""

    ok: bool
    symbol: str | None = None
    exchange: str | None = None
    ltp: float | None = None
    error: str | None = None
    code: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResolvedLeg:
    """A leg turned into an exact contract, or a refusal explaining why not."""

    ok: bool
    symbol: str | None = None
    exchange: str | None = None
    segment: str | None = None
    lotsize: int | None = None
    tick_size: float | None = None
    strike: float | None = None
    expiry: str | None = None
    expiry_symbol: str | None = None
    quantity: int | None = None
    lots: int | None = None
    option_type: str | None = None
    action: str | None = None
    underlying: str | None = None
    underlying_ltp: float | None = None
    atm_strike: float | None = None
    strategy_type: str | None = None
    error: str | None = None
    code: str | None = None
    #: Everything consulted on the way, for logs and for a caller that wants to
    #: show its work. Never load bearing.
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------


def _leg_value(leg: Mapping[str, Any], *keys: str) -> Any:
    """First non-empty value among ``keys``.

    Legs arrive from the strategy editor in camelCase and from Python callers
    in snake_case, and both spellings mean the same field.
    """
    for key in keys:
        value = leg.get(key)
        if value is not None and value != "":
            return value
    return None


def _is_positive_number(value: Any) -> bool:
    """Whether a value is a real, finite, strictly positive number.

    ``bool`` is excluded because it is an ``int`` subclass, so ``True`` would
    otherwise pass as a strike of 1.
    """
    if isinstance(value, bool):
        return False
    try:
        return math.isfinite(value) and value > 0
    except (TypeError, OverflowError, ValueError):
        return False


def _strike_text(strike: float) -> str:
    """A strike as it is written into a symbol, for use in messages.

    Mirrors ``option_symbol_service.construct_option_symbol``: a whole strike
    loses its ``.0`` and a fractional one keeps its decimals, so 292.5 stays
    292.5 and never becomes 292. The symbol itself is always built by that
    function, never by this one.
    """
    return str(int(strike)) if float(strike).is_integer() else str(strike)


def _parse_expiry(text: Any) -> date | None:
    """Parse an expiry in any spelling the codebase uses, or None."""
    if not isinstance(text, str) or not text.strip():
        return None
    cleaned = text.strip().upper()
    for fmt in _EXPIRY_INPUT_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _expiry_forms(text: str) -> tuple[str, str] | None:
    """``(database form, symbol form)`` for an expiry string.

    The database form is returned exactly as supplied so it still matches
    ``SymToken.expiry``; the symbol form is derived from the parsed date, which
    is what normalizes a four digit year down to the two digits a symbol
    carries.
    """
    parsed = _parse_expiry(text)
    if parsed is None:
        return None
    return text.strip().upper(), parsed.strftime("%d%b%y").upper()


def lot_size_for(symbol: str, exchange: str) -> int | None:
    """The contract lot size for an underlying on an exchange, or None.

    Read from the master contract rather than assumed. A derivative trades in
    whole lots, so a quantity that is not a multiple of this is refused by the
    broker at order time; catching it earlier turns a rejected order into a
    validation message.

    Matched on ``name`` first, which is the indexed column and holds the
    underlying root on most brokers, then on the OpenAlgo ``symbol`` prefix for
    the brokers whose master contract puts a description in ``name`` instead.
    Both are confirmed against a positive lot size, so a row that carries none
    cannot answer.

    Returns None when the exchange is not a derivative one (cash trades in
    single units), when the master contract has not been downloaded, or when
    nothing matches. A None answer means "cannot say", never "any quantity is
    fine", and callers must treat it that way.
    """
    if not symbol or not exchange:
        return None
    venue = str(exchange).upper()
    if venue not in DERIVATIVE_EXCHANGES:
        return None

    root = str(symbol).upper()
    try:
        from database.symbol import SymToken, db_session

        record = (
            db_session.query(SymToken.lotsize)
            .filter(
                SymToken.name == root,
                SymToken.exchange == venue,
                SymToken.lotsize.isnot(None),
                SymToken.lotsize > 0,
            )
            .first()
        )
        if record and record[0]:
            return int(record[0])

        # Fall back to the normalised symbol, which reads the same on every
        # broker. A LIKE prefix is not an anchor: GOLD% matches GOLDM and
        # GOLDPETAL, so a base with no contract of its own used to be handed a
        # neighbour's lot size, and the user's lot count was then multiplied by
        # it. Every OpenAlgo derivative symbol is the base followed
        # immediately by the expiry day, so the character after the root must
        # be a digit for the row to belong to this base.
        # find_near_month_futures anchors the same lookup for the same reason.
        rows = (
            db_session.query(SymToken.symbol, SymToken.lotsize)
            .filter(
                SymToken.symbol.like(f"{root}%"),
                SymToken.exchange == venue,
                SymToken.lotsize.isnot(None),
                SymToken.lotsize > 0,
            )
            .limit(200)
            .all()
        )
        for candidate, lotsize in rows:
            tail = str(candidate)[len(root) :]
            # Either the row is this contract exactly, which is what a signal
            # leg names, or the root is followed by the expiry day. "GOLDM..."
            # is neither, so GOLD cannot borrow GOLDM's lot size.
            if (tail == "" or tail[:1].isdigit()) and lotsize:
                return int(lotsize)
    except Exception:
        logger.exception("Could not read a lot size for %s on %s", root, venue)
    return None


def contract_exists(symbol: str, exchange: str) -> bool:
    """Whether the master contract lists this exact symbol on this exchange.

    A signal leg names its instrument outright rather than being resolved from
    an underlying and an expiry rank, so nothing else checks that the name is
    tradable. A futures leg configured as the base symbol ("NIFTY" on NFO)
    still produced a plausible quantity, because the lot size is looked up on
    the root, and the literal base then went to the broker as an order.

    Answers False only when the master contract is present and has no such
    row: with no rows at all for that exchange there is nothing to check
    against, and refusing every order because the contract has not been
    downloaded yet would be worse than the defect.
    """
    if not symbol or not exchange:
        return False
    name = str(symbol).upper()
    venue = str(exchange).upper()
    try:
        from database.symbol import SymToken, db_session

        if db_session.query(SymToken.id).filter_by(symbol=name, exchange=venue).first():
            return True
        # No rows for this venue at all: the master contract has not been
        # downloaded, so this cannot be called a bad symbol.
        return db_session.query(SymToken.id).filter_by(exchange=venue).first() is None
    except Exception:
        logger.exception("Could not check the master contract for %s on %s", name, venue)
        return True


def resolve_quantity(
    value: Any, qty_mode: str, symbol: str, exchange: str
) -> tuple[int | None, int | None, str | None]:
    """Turn a configured quantity into the number the broker is sent.

    Returns ``(quantity, lot_size, error)``.

    Two modes, because a derivative and a cash instrument are counted
    differently and pretending otherwise puts the conversion in the user's head:

    ``lots``   the value is a lot count and the quantity is ``value * lot_size``.
               Five lots of NIFTY at a lot size of 65 is 325.
    ``units``  the value is the quantity itself.

    Storing lots rather than units is what makes a strategy survive a lot-size
    change. Exchanges revise them: NIFTY moved from 75 to 65. A leg stored as
    325 units silently becomes 5 lots under one size and 4.33 under the next,
    which is not a quantity any broker will accept. A leg stored as 5 lots is
    still 5 lots.

    An unknown lot size in ``lots`` mode is an error rather than a guess. The
    quantity would be fabricated, and fabricating the size of a real order is
    the one thing this must never do.
    """
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None, None, f"{value!r} is not a whole number"
    if count <= 0:
        return None, None, "Quantity must be greater than zero"

    lot_size = lot_size_for(symbol, exchange)

    if qty_mode != "lots":
        # Units on a derivative still have to land on a lot boundary. The form
        # checks this too, but a strategy saved before the master contract was
        # downloaded, or edited directly, arrives here unchecked, and the broker
        # would refuse the order rather than round it.
        if lot_size and count % lot_size:
            return (
                None,
                lot_size,
                f"{count} is not a whole number of lots; {symbol} trades in lots of {lot_size}",
            )
        return count, lot_size, None

    if not lot_size:
        return (
            None,
            None,
            f"No lot size is known for {symbol} on {exchange}. Download the master "
            "contract, or set the quantity in units.",
        )
    return count * lot_size, lot_size, None


def quantity_is_whole_lots(quantity: Any, symbol: str, exchange: str) -> tuple[bool, int | None]:
    """Whether a quantity is a whole number of lots. Returns ``(ok, lot_size)``.

    ``ok`` is True when the exchange is not a derivative one, or when the lot
    size cannot be determined. The second case is deliberate: refusing a
    configuration because the master contract has not been downloaded would
    block a user for a reason they cannot act on from the form. The engine
    checks again at entry, where the real contract is known.
    """
    lot_size = lot_size_for(symbol, exchange)
    if not lot_size:
        return True, None
    try:
        qty = int(quantity)
    except (TypeError, ValueError):
        return False, lot_size
    return qty > 0 and qty % lot_size == 0, lot_size


def derivatives_exchange(exchange: str) -> str:
    """The exchange a derivative of this underlying is listed on.

    Delegates the underlying to derivatives mapping to
    ``option_symbol_service.get_option_exchange`` (NSE and NSE_INDEX to NFO,
    BSE and BSE_INDEX to BFO, commodities and currencies to themselves), but
    passes an exchange that is already a derivatives code straight through so
    the mapping's "unknown exchange" warning is not logged for NFO.
    """
    exch = (exchange or "").strip().upper()
    if exch in DERIVATIVE_EXCHANGES:
        return exch
    return option_symbol_service.get_option_exchange(exch)


def _normalize_rank(rank: Any) -> str:
    """Lowercase a rank and accept ``next-week`` and ``next week`` spellings."""
    if not isinstance(rank, str):
        return ""
    return rank.strip().lower().replace("-", "_").replace(" ", "_")


def _normalize_instrument_type(instrument_type: Any) -> str | None:
    """Map a leg's instrument wording onto what ``get_expiry_dates`` accepts."""
    if not isinstance(instrument_type, str):
        return None
    value = instrument_type.strip().lower()
    if value in ("options", "option", "opt", "ce", "pe"):
        return "options"
    if value in ("futures", "future", "fut"):
        return "futures"
    return None


def _lookup_contract(symbol: str, exchange: str) -> dict[str, Any] | None:
    """The master contract row for a symbol, or None.

    ``option_symbol_service.find_option_in_database`` is named for its first
    caller but is a plain symbol and exchange lookup returning every field this
    module needs, so futures and cash legs use it too rather than growing a
    second query against the same table.
    """
    return option_symbol_service.find_option_in_database(symbol, exchange)


def _coerce_lots(value: Any) -> int | None:
    """A leg's lot count as a positive whole number, or None if unusable."""
    if value is None:
        return 1
    if isinstance(value, bool):
        return None
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(as_float) or as_float <= 0 or not as_float.is_integer():
        return None
    return int(as_float)


def _fail_leg(code: str, message: str, **fields: Any) -> ResolvedLeg:
    """A refusal carrying the reason and whatever context was known."""
    logger.warning(f"Leg not resolved ({code}): {message}")
    return ResolvedLeg(ok=False, error=message, code=code, **fields)


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------


def _monthly_pairs(pairs: list[tuple[str, date]]) -> list[tuple[str, date]]:
    """The last expiry of each calendar month, in chronological order.

    ``pairs`` must be sorted ascending, so the final entry written for a month
    is that month's last expiry. This reads the rule off the data rather than
    assuming a weekday: NFO monthlies moved from Thursday to Tuesday, MCX
    commodities never had a weekday rule to begin with, and a holiday shifts any
    of them.
    """
    last_of_month: dict[tuple[int, int], tuple[str, date]] = {}
    for text, expiry in pairs:
        last_of_month[(expiry.year, expiry.month)] = (text, expiry)
    return [last_of_month[key] for key in sorted(last_of_month)]


def resolve_expiry_rank(
    underlying: str,
    exchange: str,
    instrument_type: str,
    rank: str,
    api_key: str | None = None,
) -> ExpiryResult:
    """Turn a relative expiry rank into a dated expiry.

    Args:
        underlying: Underlying, bare ("NIFTY") or carrying an expiry
            ("NIFTY28OCT25FUT"), in which case the base is taken from it.
        exchange: The underlying's own exchange ("NSE_INDEX", "NSE", "MCX") or
            the derivatives exchange ("NFO"). Either is accepted; the
            derivatives code is derived when needed.
        instrument_type: "options" or "futures". They are asked separately
            because the two calendars differ: on MCX a GOLDM future expires on
            the 5th while its options expire on the 28th, so an options leg
            resolved against the futures calendar names a contract with no
            strikes behind it.
        rank: One of :data:`EXPIRY_RANKS`.
        api_key: Optional OpenAlgo API key. ``get_expiry_dates`` verifies it
            when supplied and skips verification when it is None, which is what
            an in-process caller wants.

    Returns:
        An :class:`ExpiryResult`. On success ``expiry`` is the ``DD-MMM-YY``
        string the database stores and ``expiry_symbol`` is the ``DDMMMYY``
        form embedded in a symbol.

    Rules:
        weekly, current   the nearest live expiry
        next_week, next   the one after it, falling back to the nearest when
                          only one exists
        monthly           the nearest expiry that is the last within its own
                          calendar month
        next_month        the monthly after that, falling back to the only
                          monthly when there is one
    """
    rank_key = _normalize_rank(rank)
    if rank_key not in EXPIRY_RANKS:
        return ExpiryResult(
            ok=False,
            rank=str(rank),
            error=f"Unknown expiry rank {rank!r}. Supported ranks are {', '.join(EXPIRY_RANKS)}.",
            code="invalid_rank",
        )

    canonical_instrument = _normalize_instrument_type(instrument_type)
    if canonical_instrument is None:
        return ExpiryResult(
            ok=False,
            rank=rank_key,
            error=(
                f"Unknown instrument type {instrument_type!r}. "
                "Expiries are listed for options or futures."
            ),
            code="invalid_instrument_type",
        )

    base_symbol, _embedded = parse_underlying_symbol(str(underlying or ""))
    derivatives = derivatives_exchange(exchange)

    try:
        success, response, _status = expiry_service.get_expiry_dates(
            symbol=base_symbol,
            exchange=derivatives,
            instrumenttype=canonical_instrument,
            api_key=api_key,
        )
    except Exception:
        logger.exception(f"Expiry lookup failed for {base_symbol} on {derivatives}")
        return ExpiryResult(
            ok=False,
            rank=rank_key,
            error=f"Expiry lookup failed for {base_symbol} on {derivatives}.",
            code="expiry_lookup_failed",
        )

    if not success:
        message = (response or {}).get("message", "Expiry lookup failed")
        return ExpiryResult(
            ok=False,
            rank=rank_key,
            error=f"Could not list {canonical_instrument} expiries for "
            f"{base_symbol} on {derivatives}. {message}",
            code="expiry_lookup_failed",
        )

    raw_dates = (response or {}).get("data") or []

    # get_expiry_dates already sorts and drops expired rows. Both are repeated
    # here because the monthly rule is defined against today and against
    # ordering, and a rule that quietly depends on somebody else having run
    # first is the kind that breaks when its input changes.
    today = datetime.now().date()
    pairs: list[tuple[str, date]] = []
    for text in raw_dates:
        parsed = _parse_expiry(text)
        if parsed is None:
            logger.warning(f"Ignoring unparseable expiry {text!r} for {base_symbol}")
            continue
        if parsed >= today:
            pairs.append((str(text).strip().upper(), parsed))
    pairs.sort(key=lambda pair: pair[1])

    if not pairs:
        return ExpiryResult(
            ok=False,
            rank=rank_key,
            error=(
                f"No live {canonical_instrument} expiry found for {base_symbol} on "
                f"{derivatives}. The master contract may need re-downloading."
            ),
            code="no_expiry",
        )

    available = tuple(text for text, _ in pairs)
    fallback = False

    if rank_key in ("weekly", "current"):
        chosen = pairs[0]
    elif rank_key in ("next_week", "next"):
        fallback = len(pairs) < 2
        chosen = pairs[1] if len(pairs) > 1 else pairs[0]
    else:
        monthlies = _monthly_pairs(pairs)
        if rank_key == "monthly":
            chosen = monthlies[0]
        else:
            fallback = len(monthlies) < 2
            chosen = monthlies[1] if len(monthlies) > 1 else monthlies[0]

    text, expiry_date = chosen
    return ExpiryResult(
        ok=True,
        rank=rank_key,
        expiry=text,
        expiry_symbol=expiry_date.strftime("%d%b%y").upper(),
        available=available,
        fallback=fallback,
    )


# ---------------------------------------------------------------------------
# Underlying reference price
# ---------------------------------------------------------------------------


def resolve_underlying_ltp(
    underlying: str,
    exchange: str,
    api_key: str | None = None,
) -> UnderlyingQuote:
    """The instrument an ATM strike is measured against, and its last price.

    What that instrument is depends on the segment, and
    ``option_symbol_service.resolve_underlying_quote`` already encodes it: an
    index option prices off the spot index on NSE_INDEX or BSE_INDEX, a stock
    option off the cash equity on NSE or BSE, and an MCX commodity option off
    its nearest unexpired future, because MCX lists a CRUDEOIL19AUG26FUT and no
    plain CRUDEOIL at all. The same holds for CDS, BCD, NCDEX and NCO.

    Args:
        underlying: Underlying symbol.
        exchange: The exchange the *underlying* quotes on, not the derivatives
            exchange. NFO and BFO are refused by name rather than being guessed
            at, because guessing needs a hardcoded list of index names and gets
            every stock that shares a prefix with one wrong.
        api_key: Optional OpenAlgo API key for ``get_quotes``.

    Returns:
        An :class:`UnderlyingQuote`. ``symbol`` and ``exchange`` are what was
        actually quoted, which for MCX is a FUT contract rather than the name
        that was passed in.
    """
    base_symbol, _embedded = parse_underlying_symbol(str(underlying or ""))
    exch = (exchange or "").strip().upper()

    if not base_symbol:
        return UnderlyingQuote(
            ok=False, error="No underlying symbol supplied.", code="invalid_underlying"
        )

    if exch in ("NFO", "BFO"):
        return UnderlyingQuote(
            ok=False,
            error=(
                f"{exch} is a derivatives exchange and carries no underlying to quote. "
                "Pass the exchange the underlying itself trades on: NSE_INDEX or "
                "BSE_INDEX for an index, NSE or BSE for a stock."
            ),
            code="invalid_underlying_exchange",
        )

    resolved = option_symbol_service.resolve_underlying_quote(base_symbol, exch)
    if resolved is None:
        return UnderlyingQuote(
            ok=False,
            error=(
                f"No unexpired futures contract for {base_symbol} on {exch}, so there is "
                "no reference price for the ATM strike. Check the symbol, or "
                "re-download the master contract."
            ),
            code="no_underlying_contract",
        )

    quote_symbol, quote_exchange = resolved

    try:
        success, response, _status = quotes_service.get_quotes(
            symbol=quote_symbol, exchange=quote_exchange, api_key=api_key
        )
    except Exception:
        logger.exception(f"Quote lookup failed for {quote_symbol} on {quote_exchange}")
        return UnderlyingQuote(
            ok=False,
            symbol=quote_symbol,
            exchange=quote_exchange,
            error=f"Quote lookup failed for {quote_symbol} on {quote_exchange}.",
            code="quote_failed",
        )

    if not success:
        message = (response or {}).get("message", "Quote lookup failed")
        return UnderlyingQuote(
            ok=False,
            symbol=quote_symbol,
            exchange=quote_exchange,
            error=f"Could not fetch a price for {quote_symbol} on {quote_exchange}. {message}",
            code="quote_failed",
        )

    ltp = ((response or {}).get("data") or {}).get("ltp")
    if not _is_positive_number(ltp):
        return UnderlyingQuote(
            ok=False,
            symbol=quote_symbol,
            exchange=quote_exchange,
            error=f"Unusable last price {ltp!r} for {quote_symbol} on {quote_exchange}.",
            code="no_ltp",
        )

    return UnderlyingQuote(ok=True, symbol=quote_symbol, exchange=quote_exchange, ltp=float(ltp))


# ---------------------------------------------------------------------------
# Leg
# ---------------------------------------------------------------------------


def _resolve_leg_expiry(
    leg: Mapping[str, Any],
    underlying: str,
    exchange: str,
    instrument_type: str,
    api_key: str | None,
) -> ExpiryResult:
    """The leg's expiry, whether it named a date or a rank.

    A leg may pin an absolute expiry, which is the only way to write a calendar
    or a diagonal, where the legs deliberately do not share one.
    """
    declared = _leg_value(leg, "expiry_date", "expiryDate", "expiry", "expiry_rank", "expiryRank")

    if isinstance(declared, str) and _LITERAL_EXPIRY_PATTERN.match(declared.strip()):
        forms = _expiry_forms(declared)
        if forms is None:
            return ExpiryResult(
                ok=False,
                rank="literal",
                error=f"Expiry {declared!r} is not a date this platform understands.",
                code="invalid_expiry",
            )
        stored, symbol_form = forms
        return ExpiryResult(ok=True, rank="literal", expiry=stored, expiry_symbol=symbol_form)

    # No date, so it is a rank. "current" is the default because the nearest
    # live expiry is what a strategy that says nothing means.
    return resolve_expiry_rank(
        underlying=underlying,
        exchange=exchange,
        instrument_type=instrument_type,
        rank=declared or "current",
        api_key=api_key,
    )


def _resolve_atm_strike(
    base_symbol: str,
    option_exchange: str,
    expiry_symbol: str,
    option_type: str,
    offset: str,
    ltp: float,
    strike_int: Any,
) -> tuple[float | None, float | None, str | None, str | None]:
    """``(atm, target, error, code)`` for an ATM-relative leg.

    Two methods, both in ``option_symbol_service`` and both delegated to. With
    no strike interval given, the strikes actually listed for that expiry are
    read from the service's cache and walked by position, which is the
    recommended path: it survives an unequal ladder (NIFTY thickens away from
    the money) and fractional strikes without either being described anywhere.
    A caller that supplies an interval gets the arithmetic path instead.
    """
    if strike_int is not None:
        atm_strike = option_symbol_service.get_atm_strike(ltp, strike_int)
        target = option_symbol_service.calculate_offset_strike(
            atm_strike, offset, strike_int, option_type
        )
        return atm_strike, target, None, None

    strikes = option_symbol_service.get_available_strikes(
        base_symbol, expiry_symbol, option_type, option_exchange
    )
    if not strikes:
        return (
            None,
            None,
            f"No {option_type} strikes listed for {base_symbol} expiring {expiry_symbol} "
            f"on {option_exchange}. Check the expiry, or re-download the master contract.",
            "no_strikes",
        )

    atm_strike = option_symbol_service.find_atm_strike_from_actual(ltp, strikes)
    if atm_strike is None:
        return (
            None,
            None,
            f"Could not pick an ATM strike for {base_symbol} from a last price of {ltp!r}.",
            "no_atm_strike",
        )

    target = option_symbol_service.calculate_offset_strike_from_actual(
        atm_strike, offset, option_type, strikes
    )
    if target is None:
        return (
            atm_strike,
            None,
            f"Offset {offset} runs off the end of the {base_symbol} {expiry_symbol} "
            f"{option_type} chain, which lists {len(strikes)} strikes around an ATM of "
            f"{_strike_text(atm_strike)}.",
            "offset_out_of_range",
        )

    return atm_strike, target, None, None


def resolve_leg(
    leg: Mapping[str, Any],
    underlying: str,
    underlying_exchange: str,
    strategy_type: str | None = None,
    *,
    api_key: str | None = None,
    underlying_ltp: float | None = None,
) -> ResolvedLeg:
    """Resolve one strategy leg to an exact tradable contract.

    Args:
        leg: The leg definition. Keys are read in snake_case or camelCase:

            ``segment``     "cash", "futures" or "options". Required.
            ``lots``        Whole number of lots, default 1.
            ``action``      "BUY" or "SELL". Carried through untouched.
            ``expiry``      An expiry rank from :data:`EXPIRY_RANKS`, or a
                            literal date ("28-MAY-26" or "28MAY26"). Futures
                            and options only; default "current".
            ``option_type`` "CE" or "PE". Options only.
            ``strike_mode`` "atm" or "strike". Options only, default "atm".
            ``atm_offset``  "ATM", "ITM1".."ITM5", "OTM1".."OTM5", default
                            "ATM". Used when ``strike_mode`` is "atm".
            ``strike``      An absolute strike, fractional allowed. Used when
                            ``strike_mode`` is "strike".
            ``strike_int``  Optional strike interval. Supplying it switches the
                            ATM calculation from the listed strikes to plain
                            arithmetic.

        underlying: The strategy's underlying, e.g. "NIFTY", "RELIANCE",
            "CRUDEOIL".
        underlying_exchange: The exchange the underlying itself quotes on:
            NSE_INDEX, BSE_INDEX, NSE, BSE, MCX, CDS and so on. The derivatives
            exchange is derived from it.
        strategy_type: The strategy this leg belongs to, e.g. "straddle". It is
            recorded on the result and used in logs; it does not change how the
            leg resolves.
        api_key: Optional OpenAlgo API key for the expiry and quote lookups.
        underlying_ltp: A price already fetched for this underlying. Pass it
            when resolving a basket: every leg of one strategy must be priced
            off the same tick, and re-quoting per leg is both slower and liable
            to straddle a price move, putting two legs of one spread around
            different ATMs.

    Returns:
        A :class:`ResolvedLeg`. ``ok`` is False for anything that could not be
        resolved, with ``code`` naming the class of failure and ``error``
        naming the exact contract that was looked for. Nothing is guessed:
        ``quantity`` is always ``lots * lotsize`` with the lot size read from
        the master contract, and a lot size of zero or less is a refusal rather
        than a fallback to one.
    """
    if not isinstance(leg, Mapping):
        return _fail_leg(
            "invalid_leg", f"A leg must be a mapping of fields, got {type(leg).__name__}."
        )

    context = {"strategy_type": strategy_type, "underlying": None, "action": None}
    try:
        base_symbol, _embedded = parse_underlying_symbol(str(underlying or ""))
        context["underlying"] = base_symbol
        context["action"] = _leg_value(leg, "action", "side", "transaction_type")

        if not base_symbol:
            return _fail_leg("invalid_underlying", "No underlying symbol supplied.", **context)

        segment_raw = _leg_value(leg, "segment", "instrument", "leg_type", "legType")
        segment = str(segment_raw).strip().lower() if segment_raw is not None else ""
        if segment not in SEGMENTS:
            return _fail_leg(
                "invalid_segment",
                f"Unknown segment {segment_raw!r} on a {base_symbol} leg. "
                f"Supported segments are {', '.join(SEGMENTS)}.",
                **context,
            )
        context["segment"] = segment

        lots = _coerce_lots(_leg_value(leg, "lots", "num_lots", "numLots"))
        if lots is None:
            return _fail_leg(
                "invalid_lots",
                f"Lots on a {base_symbol} {segment} leg must be a whole number above zero, "
                f"got {_leg_value(leg, 'lots', 'num_lots', 'numLots')!r}.",
                **context,
            )
        context["lots"] = lots

        if segment == "cash":
            return _resolve_cash_leg(base_symbol, underlying_exchange, context)
        if segment == "futures":
            return _resolve_futures_leg(leg, base_symbol, underlying_exchange, api_key, context)
        return _resolve_options_leg(
            leg, base_symbol, underlying_exchange, api_key, underlying_ltp, context
        )

    except ValueError as error:
        # Raised by the option_symbol_service validators: an unsupported option
        # type, a strike interval that cannot be divided by, an offset it does
        # not recognise. All of them are the caller's input, not a fault.
        return _fail_leg("invalid_leg", str(error), **context)
    except Exception:
        logger.exception(f"Could not resolve a {underlying} leg")
        return _fail_leg(
            "resolver_error",
            f"Could not resolve a {underlying} leg. See the application log for details.",
            **context,
        )


def _finish(
    contract: Mapping[str, Any],
    symbol: str,
    exchange: str,
    context: dict[str, Any],
    *,
    strike: float | None = None,
    expiry: str | None = None,
    expiry_symbol: str | None = None,
    underlying_ltp: float | None = None,
    atm_strike: float | None = None,
    detail: dict[str, Any] | None = None,
) -> ResolvedLeg:
    """Apply the lot size rule and build the successful result.

    The lot size is whatever the master contract says for this exact contract
    and is never assumed: NIFTY has been 25, 50 and 75 within living memory,
    MCX sizes differ per product, and a stock's lot changes on review. A row
    with a missing or non-positive lot size means the master contract is stale
    or the broker shipped a bad column, and multiplying by it would send an
    order for zero or for a negative quantity.
    """
    lotsize = contract.get("lotsize")
    if isinstance(lotsize, bool) or not isinstance(lotsize, int | float) or lotsize <= 0:
        return _fail_leg(
            "invalid_lotsize",
            f"The master contract gives {symbol} on {exchange} a lot size of {lotsize!r}, "
            "so no quantity can be derived from it. Re-download the master contract.",
            symbol=symbol,
            exchange=exchange,
            strike=strike,
            expiry=expiry,
            expiry_symbol=expiry_symbol,
            **context,
        )

    lotsize = int(lotsize)
    lots = context.get("lots") or 1
    tick_size = contract.get("tick_size")

    return ResolvedLeg(
        ok=True,
        symbol=symbol,
        exchange=exchange,
        lotsize=lotsize,
        tick_size=float(tick_size) if _is_positive_number(tick_size) else None,
        strike=strike,
        expiry=expiry,
        expiry_symbol=expiry_symbol,
        quantity=lots * lotsize,
        underlying_ltp=underlying_ltp,
        atm_strike=atm_strike,
        detail=detail or {},
        **context,
    )


def _resolve_cash_leg(
    base_symbol: str, underlying_exchange: str, context: dict[str, Any]
) -> ResolvedLeg:
    """A cash leg is the underlying equity itself."""
    exch = (underlying_exchange or "").strip().upper()
    exchange = CASH_EXCHANGE_FOR.get(exch, exch)

    contract = _lookup_contract(base_symbol, exchange)
    if not contract:
        return _fail_leg(
            "contract_not_found",
            f"No cash contract found for {base_symbol} on {exchange}."
            + (
                " An index has no cash instrument of its own and cannot be traded directly."
                if exch in CASH_EXCHANGE_FOR
                else ""
            ),
            symbol=base_symbol,
            exchange=exchange,
            **context,
        )

    return _finish(contract, base_symbol, exchange, context)


def _resolve_futures_leg(
    leg: Mapping[str, Any],
    base_symbol: str,
    underlying_exchange: str,
    api_key: str | None,
    context: dict[str, Any],
) -> ResolvedLeg:
    """A futures leg is ``{BASE}{DDMMMYY}FUT`` on the derivatives exchange."""
    exchange = derivatives_exchange(underlying_exchange)

    expiry = _resolve_leg_expiry(leg, base_symbol, underlying_exchange, "futures", api_key)
    if not expiry.ok:
        return _fail_leg(
            expiry.code or "no_expiry", expiry.error or "", exchange=exchange, **context
        )

    symbol = f"{base_symbol}{expiry.expiry_symbol}FUT"
    contract = _lookup_contract(symbol, exchange)
    if not contract:
        return _fail_leg(
            "contract_not_found",
            f"No futures contract found for {base_symbol} {expiry.expiry} on {exchange} "
            f"(looked for {symbol}).",
            symbol=symbol,
            exchange=exchange,
            expiry=expiry.expiry,
            expiry_symbol=expiry.expiry_symbol,
            **context,
        )

    return _finish(
        contract,
        symbol,
        exchange,
        context,
        expiry=expiry.expiry,
        expiry_symbol=expiry.expiry_symbol,
        detail={"expiry_rank": expiry.rank, "expiry_fallback": expiry.fallback},
    )


def _resolve_options_leg(
    leg: Mapping[str, Any],
    base_symbol: str,
    underlying_exchange: str,
    api_key: str | None,
    underlying_ltp: float | None,
    context: dict[str, Any],
) -> ResolvedLeg:
    """An options leg, strike named either relative to the money or outright."""
    option_type = option_symbol_service.validate_option_type(
        _leg_value(leg, "option_type", "optionType", "opt_type")
    )
    context["option_type"] = option_type
    exchange = derivatives_exchange(underlying_exchange)

    expiry = _resolve_leg_expiry(leg, base_symbol, underlying_exchange, "options", api_key)
    if not expiry.ok:
        return _fail_leg(
            expiry.code or "no_expiry", expiry.error or "", exchange=exchange, **context
        )

    mode_raw = _leg_value(leg, "strike_mode", "strikeMode")
    strike_mode = str(mode_raw).strip().lower() if mode_raw is not None else "atm"
    if strike_mode not in STRIKE_MODES:
        return _fail_leg(
            "invalid_strike_mode",
            f"Unknown strike mode {mode_raw!r} on a {base_symbol} option leg. "
            f"Supported modes are {', '.join(STRIKE_MODES)}.",
            exchange=exchange,
            expiry=expiry.expiry,
            expiry_symbol=expiry.expiry_symbol,
            **context,
        )

    ltp: float | None = None
    atm_strike: float | None = None
    offset: str | None = None
    detail: dict[str, Any] = {
        "expiry_rank": expiry.rank,
        "expiry_fallback": expiry.fallback,
        "strike_mode": strike_mode,
    }

    if strike_mode == "strike":
        declared = _leg_value(leg, "strike")
        if not _is_positive_number(declared):
            return _fail_leg(
                "invalid_strike",
                f"Strike {declared!r} on a {base_symbol} option leg is not a usable price. "
                "A strike must be a positive number, and may be fractional.",
                exchange=exchange,
                expiry=expiry.expiry,
                expiry_symbol=expiry.expiry_symbol,
                **context,
            )
        # float(), never int(): VEDL25APR24292.5CE is a real contract, and
        # truncating its strike names one that does not exist.
        target_strike = float(declared)
    else:
        offset_raw = _leg_value(leg, "atm_offset", "atmOffset", "offset") or "ATM"
        offset = str(offset_raw).strip().upper()
        if not ATM_OFFSET_PATTERN.match(offset):
            return _fail_leg(
                "invalid_offset",
                f"Unknown offset {offset_raw!r} on a {base_symbol} option leg. "
                "Supported offsets are ATM, ITM1 to ITM5 and OTM1 to OTM5.",
                exchange=exchange,
                expiry=expiry.expiry,
                expiry_symbol=expiry.expiry_symbol,
                **context,
            )
        detail["atm_offset"] = offset

        if underlying_ltp is not None:
            if not _is_positive_number(underlying_ltp):
                return _fail_leg(
                    "no_ltp",
                    f"Unusable last price {underlying_ltp!r} supplied for {base_symbol}.",
                    exchange=exchange,
                    expiry=expiry.expiry,
                    expiry_symbol=expiry.expiry_symbol,
                    **context,
                )
            ltp = float(underlying_ltp)
        else:
            quote = resolve_underlying_ltp(base_symbol, underlying_exchange, api_key)
            if not quote.ok:
                return _fail_leg(
                    quote.code or "no_ltp",
                    quote.error or "",
                    exchange=exchange,
                    expiry=expiry.expiry,
                    expiry_symbol=expiry.expiry_symbol,
                    **context,
                )
            ltp = quote.ltp
            detail["quote_symbol"] = quote.symbol
            detail["quote_exchange"] = quote.exchange

        atm_strike, target_strike, error, code = _resolve_atm_strike(
            base_symbol=base_symbol,
            option_exchange=exchange,
            expiry_symbol=expiry.expiry_symbol,
            option_type=option_type,
            offset=offset,
            ltp=ltp,
            strike_int=_leg_value(leg, "strike_int", "strikeInt", "strike_interval"),
        )
        if target_strike is None:
            return _fail_leg(
                code or "no_strikes",
                error or "",
                exchange=exchange,
                expiry=expiry.expiry,
                expiry_symbol=expiry.expiry_symbol,
                underlying_ltp=ltp,
                atm_strike=atm_strike,
                **context,
            )

    symbol = option_symbol_service.construct_option_symbol(
        base_symbol, expiry.expiry_symbol, target_strike, option_type
    )

    contract = _lookup_contract(symbol, exchange)
    if not contract:
        return _fail_leg(
            "contract_not_found",
            f"No option contract found for {base_symbol} {expiry.expiry} "
            f"{_strike_text(target_strike)} {option_type} on {exchange} "
            f"(looked for {symbol}).",
            symbol=symbol,
            exchange=exchange,
            strike=target_strike,
            expiry=expiry.expiry,
            expiry_symbol=expiry.expiry_symbol,
            underlying_ltp=ltp,
            atm_strike=atm_strike,
            **context,
        )

    return _finish(
        contract,
        symbol,
        exchange,
        context,
        strike=target_strike,
        expiry=expiry.expiry,
        expiry_symbol=expiry.expiry_symbol,
        underlying_ltp=ltp,
        atm_strike=atm_strike,
        detail=detail,
    )
