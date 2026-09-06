"""Symbol lookup and resolution.

This is the toolkit that stops the model inventing contracts. Every other tool
takes an ``(symbol, exchange)`` pair as an exact contract identity, so a symbol
the model assembled from memory is not a near miss, it is a different
instrument, an order rejection, or worse, a real order on something nobody
asked for. Expiry dates and strike ladders are facts to look up; they are not
derivable from a calendar.

Three tools, in the order the model should reach for them:

* :meth:`SymbolsToolkit.search_symbols` turns a name or a fragment into the
  exact listed OpenAlgo symbols.
* :meth:`SymbolsToolkit.get_symbol` confirms one contract and returns the
  numbers an order needs: lot size, tick size and freeze quantity.
* :meth:`SymbolsToolkit.get_expiry_dates` lists the live expiries for an
  underlying, which is the only sanctioned source for the date segment of a
  derivative symbol.

Failure is where this toolkit earns its place. A lookup that finds nothing does
not report "not found" and stop: it searches for near matches and raises
``RetryAgentRun`` naming them, so the model corrects itself instead of telling
the operator their instrument does not exist. A model that hears "no such
symbol" reports that to a human; a model that hears "not listed, but these are"
tries the right one.

Everything here reads the platform's own instrument master through
``services/*``. Nothing makes an HTTP request back into this process and
nothing mutates, so no tool needs confirmation and no audit row is owed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, NoReturn

from services import expiry_service, search_service, symbol_service
from services.agent.prompts import wrap_tool_result
from services.agent.tools.base import OpenAlgoToolkit
from utils.logging import get_logger

try:
    from agno.exceptions import RetryAgentRun
except ImportError as exc:  # pragma: no cover - exercised only without the dependency
    raise ImportError(
        "services.agent.tools.symbols requires the 'agno' package. Install it with: uv add agno"
    ) from exc

if TYPE_CHECKING:  # pragma: no cover - typing only
    from services.agent.tools import ToolContext

logger = get_logger(__name__)

#: Rows returned by one search. The service itself caps at 500 matches, which is
#: far more JSON than the model's result budget holds, so the cut is made here
#: where it can be counted and explained rather than by the character cap in
#: ``to_json``, which would drop the tail mid-value.
MAX_SEARCH_RESULTS = 40

#: Near matches named in a correction message. Enough to recognise the right
#: contract, short enough that the message stays readable.
MAX_SUGGESTIONS = 8

#: Exchange codes, from docs/prompt/order-constants.md. Split by what they can
#: do, because the difference is what the model gets wrong: an index feed is
#: quote-only and lists no contract, so it can never answer an expiry question.
CASH_EXCHANGES: tuple[str, ...] = ("NSE", "BSE")
DERIVATIVE_EXCHANGES: tuple[str, ...] = (
    "NFO",
    "BFO",
    "CDS",
    "BCD",
    "MCX",
    "NCDEX",
    "NCO",
    "CRYPTO",
)
INDEX_EXCHANGES: tuple[str, ...] = ("NSE_INDEX", "BSE_INDEX", "MCX_INDEX", "GLOBAL_INDEX")

ALL_EXCHANGES: frozenset[str] = frozenset(CASH_EXCHANGES + DERIVATIVE_EXCHANGES + INDEX_EXCHANGES)

#: Where the derivatives of a cash or index exchange are actually listed. Asking
#: for NIFTY expiries on NSE_INDEX is the single most common version of this
#: mistake, and naming the right exchange fixes it in one turn.
_DERIVATIVE_VENUE: Mapping[str, str] = {
    "NSE": "NFO",
    "NSE_INDEX": "NFO",
    "BSE": "BFO",
    "BSE_INDEX": "BFO",
    "MCX_INDEX": "MCX",
}

#: What the model may call an instrument type, mapped to what the service takes.
_INSTRUMENT_TYPES: Mapping[str, str] = {
    "options": "options",
    "option": "options",
    "opt": "options",
    "opts": "options",
    "ce": "options",
    "pe": "options",
    "optidx": "options",
    "optstk": "options",
    "optfut": "options",
    "optcur": "options",
    "futures": "futures",
    "future": "futures",
    "fut": "futures",
    "futs": "futures",
    "futidx": "futures",
    "futstk": "futures",
    "futcom": "futures",
    "futcur": "futures",
}

#: Recognises a service failure that means "no such row" rather than "the
#: platform broke". Only the first kind is worth answering with suggestions;
#: dressing up a 500 as a spelling problem would send the model hunting for a
#: symbol that was never the issue.
_NOT_FOUND_PATTERN = re.compile(r"HTTP 404|not found|no matching|does not exist", re.IGNORECASE)

#: The leading letters of a symbol, which is its underlying: the root of
#: ``NIFTY28MAR2420800CE`` is ``NIFTY``.
_ROOT_PATTERN = re.compile(r"[A-Za-z&]+")

#: The base symbol in front of a DDMMMYY expiry segment. Non-greedy, so it stops
#: at the first real date: ``726GS203325APR24FUT`` yields ``726GS2033`` and not
#: ``726GS20``.
_UNDERLYING_PATTERN = re.compile(r"\A(.+?)\d{2}[A-Z]{3}\d{0,2}")

#: An expiry as the instrument master stores it: ``31-JUL-25`` or ``31-JUL-2025``.
_EXPIRY_PATTERN = re.compile(r"\A(\d{1,2})-?([A-Z]{3})-?(\d{2}|\d{4})\Z")


def symbol_expiry(value: Any) -> str | None:
    """Render a master-stored expiry the way an OpenAlgo symbol spells it.

    ``31-JUL-25`` and ``31-JUL-2025`` both become ``31JUL25``, which is the
    ``DDMMMYY`` segment every OpenAlgo symbol and every service argument uses.

    Module level and public because more than one toolkit needs the conversion:
    this file pairs it with each listed expiry, and the derived option
    analytics resolve a default expiry from the same service. A second copy
    would drift, and the copy in the path nobody is looking at is the one that
    goes wrong.

    Args:
        value: The expiry exactly as the instrument master or
            ``expiry_service`` returned it.

    Returns:
        The ``DDMMMYY`` form, or None when the value is not an expiry at all.
    """
    if not isinstance(value, str):
        return None
    match = _EXPIRY_PATTERN.match(value.strip().upper())
    if not match:
        return None
    day, month, year = match.groups()
    return f"{int(day):02d}{month}{year[-2:]}"


#: A symbol and an exchange are named back to the model in a plain-text
#: correction message, outside any wrapped block, so they are checked against
#: the shape a real code has rather than escaped. A candidate that does not
#: match is dropped instead of being repaired, because a repaired symbol is a
#: different contract and would be worse than no suggestion at all.
_SAFE_SYMBOL = re.compile(r"\A[A-Za-z0-9._&/-]{1,40}\Z")
_SAFE_EXCHANGE = re.compile(r"\A[A-Z_]{1,20}\Z")

#: Fields carried in a search row. The broker's own symbol and exchange are left
#: out: nothing in the tool layer takes them, and 40 rows of them is budget the
#: model could have spent on 40 more matches.
_SEARCH_FIELDS: tuple[str, ...] = (
    "symbol",
    "exchange",
    "name",
    "instrumenttype",
    "expiry",
    "strike",
    "lotsize",
    "tick_size",
    "freeze_qty",
)

#: Fields dropped from a row when they carry nothing. An equity has no expiry
#: and no strike, and ``"strike": 0.0`` on INFY reads as a fact rather than as
#: an absence.
_OMIT_WHEN_EMPTY: frozenset[str] = frozenset({"expiry", "strike"})


class SymbolsToolkit(OpenAlgoToolkit):
    """Search, resolve and date OpenAlgo contracts."""

    def __init__(self, context: ToolContext) -> None:
        """Register the three lookup tools.

        Args:
            context: The run's tool context. Must carry an OpenAlgo API key.
        """
        super().__init__(
            context,
            name="symbols",
            tools=[self.search_symbols, self.get_symbol, self.get_expiry_dates],
        )

    # -- tools ---------------------------------------------------------------

    def search_symbols(self, query: str, exchange: str = "") -> str:
        """Search OpenAlgo's instrument master for listed contracts.

        This is how a name, a fragment or a description becomes an exact listed
        symbol. Call it before quoting, charting or ordering anything whose
        symbol you were not handed verbatim, then use the ``symbol`` string that
        comes back exactly as it came back. Never assemble a derivative symbol
        yourself: an index expiry is not the last Thursday of the month any
        more, and a strike ladder is not evenly spaced everywhere.

        Every whitespace-separated term must match, against the OpenAlgo symbol,
        the broker symbol, the instrument name or the strike. ``NIFTY 20800 CE``
        is a good query. A sentence is not.

        OpenAlgo symbol format, which is what the ``symbol`` field holds:

        - Equity is the bare base symbol: ``INFY``, ``SBIN``, ``TATAMOTORS``.
        - Futures are ``[Base][DDMMMYY]FUT``: ``BANKNIFTY24APR24FUT``,
          ``CRUDEOILM20MAY24FUT``, ``USDINR10MAY24FUT``.
        - Options are ``[Base][DDMMMYY][Strike][CE or PE]``:
          ``NIFTY28MAR2420800CE``, ``CRUDEOIL17APR246750CE``. A decimal strike
          keeps its decimal point and the point is part of the symbol:
          ``VEDL25APR24292.5CE``.
        - An index carries no expiry and sits on its own exchange code:
          ``NIFTY`` and ``BANKNIFTY`` on ``NSE_INDEX``, ``SENSEX`` on
          ``BSE_INDEX``.

        Args:
            query: What to search for. A base symbol (``RELIANCE``), a company
                name (``State Bank``), a whole contract
                (``NIFTY28MAR2420800CE``), or terms that must all match
                (``BANKNIFTY 56000 PE``). Case does not matter.
            exchange: Exchange filter, one of NSE, BSE, NFO, BFO, CDS, BCD, MCX,
                NCDEX, NCO, CRYPTO, NSE_INDEX, BSE_INDEX, MCX_INDEX,
                GLOBAL_INDEX. Leave it empty to search every exchange, which is
                the right choice when you are not certain where the instrument
                is listed.

        Returns:
            JSON carrying ``matches``, a list of rows with ``symbol``,
            ``exchange``, ``name``, ``instrumenttype``, ``expiry``, ``strike``,
            ``lotsize``, ``tick_size`` and ``freeze_qty``. Fields that do not
            apply to an instrument are omitted. ``total_matches`` says how many
            the search found and ``returned`` how many are in this result, so a
            truncated list is visible rather than silent.
        """
        text = self._require_text(
            "query",
            query,
            "Pass a base symbol, a company name, or the terms to match, such as 'BANKNIFTY 56000 PE'.",
        )
        venue = self._exchange(exchange, allow_blank=True)

        rows = self._search(text, venue)
        if not rows:
            self._suggest_broader_query(text, venue)
            return self._wrap(
                "search_symbols",
                {
                    "query": text,
                    "exchange": venue or "all",
                    "total_matches": 0,
                    "returned": 0,
                    "matches": [],
                    "message": (
                        "Nothing in the instrument master matches that query, on any exchange. "
                        "The instrument may not be listed, or the name may be wrong. Ask the "
                        "operator which instrument they mean rather than guessing a symbol."
                    ),
                },
                query=text,
                exchange=venue or None,
            )

        shown = [self._compact(row, _SEARCH_FIELDS) for row in rows[:MAX_SEARCH_RESULTS]]
        result: dict[str, Any] = {
            "query": text,
            "exchange": venue or "all",
            "total_matches": len(rows),
            "returned": len(shown),
            "matches": shown,
        }
        if len(rows) > len(shown):
            result["truncated"] = True
            result["note"] = (
                f"{len(rows) - len(shown)} further matches were not returned. Add a term to the "
                "query (a strike, an expiry, CE or PE) or set the exchange to narrow it."
            )
        return self._wrap("search_symbols", result, query=text, exchange=venue or None)

    def get_symbol(self, symbol: str, exchange: str) -> str:
        """Confirm one exact contract and return what an order needs to know.

        Use this to verify a symbol before acting on it, and to get the three
        numbers an order depends on: ``lotsize``, ``tick_size`` and
        ``freeze_qty``. They come back together so nothing has to look them up
        twice.

        The pair must be exact. A symbol is only meaningful with its exchange,
        and OpenAlgo treats the pair as a contract identity rather than a label:

        - Equity is the bare base symbol: ``INFY`` on NSE.
        - Futures are ``[Base][DDMMMYY]FUT``: ``BANKNIFTY24APR24FUT`` on NFO.
        - Options are ``[Base][DDMMMYY][Strike][CE or PE]``:
          ``NIFTY28MAR2420800CE`` on NFO, and a decimal strike keeps its point,
          as in ``VEDL25APR24292.5CE``.

        If the contract is not listed, this tool comes back with the listed
        contracts that look closest rather than a bare failure. Take one of
        those; do not adjust an expiry or a strike yourself to make one fit.

        Args:
            symbol: The exact OpenAlgo symbol, for example ``RELIANCE``,
                ``BANKNIFTY24APR24FUT`` or ``NIFTY28MAR2420800CE``. Get it from
                search_symbols rather than composing it.
            exchange: Exchange code the contract is listed on. One of NSE, BSE,
                NFO, BFO, CDS, BCD, MCX, NCDEX, NCO, CRYPTO, NSE_INDEX,
                BSE_INDEX, MCX_INDEX, GLOBAL_INDEX. Equity is NSE or BSE, an
                index future or option is NFO or BFO, and an index itself is
                NSE_INDEX or BSE_INDEX.

        Returns:
            JSON with ``symbol``, ``exchange``, ``name``, ``instrumenttype``,
            ``expiry``, ``strike``, ``lotsize`` (order quantity must be a whole
            multiple of it), ``tick_size`` (a price must be a multiple of it),
            ``freeze_qty`` (the exchange's single-order ceiling, where one
            applies) and the broker's own ``brsymbol`` and ``brexchange``.
        """
        text = self._require_text(
            "symbol",
            symbol,
            "Pass one exact OpenAlgo symbol, such as 'RELIANCE' or 'NIFTY28MAR2420800CE'. "
            "Use search_symbols to find it.",
        )
        venue = self._exchange(exchange, allow_blank=False)

        # The master stores symbols in capitals. Trying the text as given first
        # keeps a genuinely lower-case listing working, and the capitalised form
        # rescues the ordinary case of a model echoing an operator's typing.
        candidates = [text]
        if text.upper() != text:
            candidates.append(text.upper())

        first_failure: RetryAgentRun | None = None
        for candidate in candidates:
            try:
                payload = self.service_call(
                    symbol_service.get_symbol_info, symbol=candidate, exchange=venue
                )
            except RetryAgentRun as exc:
                if not _NOT_FOUND_PATTERN.search(str(exc)):
                    # A platform failure is not a spelling problem. Report it as
                    # it is instead of sending the model off to search.
                    raise
                first_failure = first_failure or exc
                continue

            info = payload.get("data") if isinstance(payload, Mapping) else None
            if isinstance(info, Mapping) and info:
                row = {key: value for key, value in info.items() if key != "id"}
                return self._wrap(
                    "get_symbol",
                    self._compact(row, tuple(row)),
                    symbol=candidate,
                    exchange=venue,
                )

        self._raise_not_listed(text, venue, first_failure)

    def get_expiry_dates(self, symbol: str, exchange: str, instrument_type: str) -> str:
        """List the live expiry dates for a futures or options underlying.

        This is the only sanctioned source for the date segment of a derivative
        symbol. Expired contracts are excluded and the dates come back in
        chronological order, so the first entry is the nearest expiry and the
        weekly or monthly rhythm is visible rather than assumed.

        Each entry carries the date twice: ``expiry`` as the exchange writes it
        (``31-JUL-25``) and ``symbol_expiry`` as an OpenAlgo symbol spells it
        (``31JUL25``). A symbol is that segment between the base and the rest:

        - Futures: ``[Base][symbol_expiry]FUT``, so BANKNIFTY plus ``24APR24``
          is ``BANKNIFTY24APR24FUT``.
        - Options: ``[Base][symbol_expiry][Strike][CE or PE]``, so NIFTY plus
          ``28MAR24`` plus 20800 is ``NIFTY28MAR2420800CE``, and a decimal
          strike keeps its point: ``VEDL25APR24292.5CE``.

        The expiry is a fact you now have; the strike is not. Confirm the whole
        contract with search_symbols before quoting or ordering it, because a
        strike outside the listed ladder produces a symbol that does not exist.

        Args:
            symbol: The underlying, not a contract. ``NIFTY``, ``BANKNIFTY``,
                ``RELIANCE``, ``CRUDEOIL``, ``USDINR``. Passing a full contract
                symbol here finds nothing.
            exchange: The exchange the derivatives are listed on, one of NFO,
                BFO, CDS, BCD, MCX, NCDEX, NCO, CRYPTO. NIFTY and BANKNIFTY
                options are on NFO even though the index itself is quoted on
                NSE_INDEX; SENSEX options are on BFO.
            instrument_type: ``options`` or ``futures``. Nothing else.

        Returns:
            JSON with ``expiries``, a chronological list of
            ``{"expiry", "symbol_expiry"}`` entries, plus ``symbol``,
            ``exchange``, ``instrument_type`` and ``count``.
        """
        underlying = self._require_text(
            "symbol",
            symbol,
            "Pass the underlying alone, such as 'NIFTY' or 'RELIANCE', not a full contract symbol.",
        ).upper()
        venue = self._expiry_exchange(exchange)
        kind = self._instrument_type(instrument_type)

        payload = self.service_call(
            expiry_service.get_expiry_dates,
            symbol=underlying,
            exchange=venue,
            instrumenttype=kind,
        )
        dates = payload.get("data") if isinstance(payload, Mapping) else None
        entries = self._expiry_entries(dates)

        if not entries:
            self._suggest_underlying(underlying, venue, kind)
            return self._wrap(
                "get_expiry_dates",
                {
                    "symbol": underlying,
                    "exchange": venue,
                    "instrument_type": kind,
                    "count": 0,
                    "expiries": [],
                    "message": (
                        f"No live {kind} expiries for {underlying} on {venue}, and no similar "
                        "underlying is listed there either. Check the underlying with the "
                        "operator rather than guessing an expiry."
                    ),
                },
                symbol=underlying,
                exchange=venue,
            )

        return self._wrap(
            "get_expiry_dates",
            {
                "symbol": underlying,
                "exchange": venue,
                "instrument_type": kind,
                "count": len(entries),
                "expiries": entries,
                "note": (
                    "symbol_expiry is the date segment of the OpenAlgo symbol. The strike is "
                    "not derivable the same way, so confirm the full contract with "
                    "search_symbols before using it."
                ),
            },
            symbol=underlying,
            exchange=venue,
        )

    # -- argument checking ---------------------------------------------------

    def _require_text(self, field: str, value: Any, fix: str) -> str:
        """Return a stripped non-empty string, or reject the argument.

        Args:
            field: Argument name as the model sees it.
            value: The value the model passed.
            fix: What a usable value looks like.

        Returns:
            The value stripped of surrounding whitespace.

        Raises:
            RetryAgentRun: When the value is not a non-empty string.
        """
        if not isinstance(value, str) or not value.strip():
            self.invalid_argument(field, "it was empty.", fix)
        return value.strip()

    def _exchange(self, value: Any, *, allow_blank: bool) -> str:
        """Normalise an exchange code and check it is one OpenAlgo knows.

        Args:
            value: The value the model passed.
            allow_blank: True when an empty value means "every exchange".

        Returns:
            The upper-case exchange code, or an empty string when blank was
            allowed and the value was blank.

        Raises:
            RetryAgentRun: When the code is missing and required, or unknown.
        """
        text = value.strip().upper() if isinstance(value, str) else ""
        if not text:
            if allow_blank:
                return ""
            self.invalid_argument(
                "exchange",
                "it was empty, and a symbol only identifies a contract together with its exchange.",
                f"Pass one of: {', '.join(sorted(ALL_EXCHANGES))}.",
            )
        if text not in ALL_EXCHANGES:
            self.invalid_argument(
                "exchange",
                f"{text!r} is not an OpenAlgo exchange code.",
                f"Pass one of: {', '.join(sorted(ALL_EXCHANGES))}.",
            )
        return text

    def _expiry_exchange(self, value: Any) -> str:
        """Normalise an exchange code for an expiry lookup.

        A cash or index exchange lists no derivative, so it can never answer
        this question. Rather than reporting an empty list, name the exchange
        the derivatives are actually on.

        Args:
            value: The value the model passed.

        Returns:
            The upper-case derivatives exchange code.

        Raises:
            RetryAgentRun: When the code is unknown or lists no derivatives.
        """
        text = self._exchange(value, allow_blank=False)
        if text in DERIVATIVE_EXCHANGES:
            return text

        venue = _DERIVATIVE_VENUE.get(text)
        if venue:
            self.invalid_argument(
                "exchange",
                f"{text} lists no futures or options"
                + (" and is a quote-only index feed" if text in INDEX_EXCHANGES else "")
                + ".",
                f"Its derivatives are listed on {venue}; call the tool again with "
                f"exchange='{venue}'.",
            )
        self.invalid_argument(
            "exchange",
            f"{text} lists no futures or options.",
            f"Pass a derivatives exchange: {', '.join(DERIVATIVE_EXCHANGES)}.",
        )

    def _instrument_type(self, value: Any) -> str:
        """Normalise the instrument type to what the service accepts.

        Args:
            value: The value the model passed. Singulars and the master's own
                type codes (``OPTIDX``, ``FUTSTK``) are accepted.

        Returns:
            ``options`` or ``futures``.

        Raises:
            RetryAgentRun: When the value is neither.
        """
        text = (
            value.strip().lower().replace("-", "").replace("_", "")
            if isinstance(value, str)
            else ""
        )
        kind = _INSTRUMENT_TYPES.get(text)
        if kind is None:
            self.invalid_argument(
                "instrument_type",
                f"{value!r} is not an instrument type.",
                "Pass 'options' or 'futures'.",
            )
        return kind

    # -- lookups -------------------------------------------------------------

    def _search(self, query: str, exchange: str) -> list[Mapping[str, Any]]:
        """Run one instrument-master search through the service layer.

        Args:
            query: The search text.
            exchange: Exchange filter, or an empty string for all exchanges.

        Returns:
            The matching rows, empty when nothing matched.

        Raises:
            RetryAgentRun: When the search itself failed.
        """
        payload = self.service_call(
            search_service.search_symbols, query=query, exchange=exchange or None
        )
        rows = payload.get("data") if isinstance(payload, Mapping) else None
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            return []
        return [row for row in rows if isinstance(row, Mapping)]

    def _quiet_search(self, query: str, exchange: str = "") -> list[Mapping[str, Any]]:
        """Search for suggestions, swallowing every failure.

        A suggestion lookup runs while another call has already failed. If it
        fails too, the model must still receive the original failure, so nothing
        here is allowed to raise.

        Args:
            query: The search text.
            exchange: Exchange filter, or an empty string for all exchanges.

        Returns:
            The matching rows, or an empty list on any failure.
        """
        if not query:
            return []
        try:
            success, payload, _status = search_service.search_symbols(
                query=query, exchange=exchange or None, api_key=self.api_key
            )
        except Exception:
            logger.exception("Near-match search for %r failed", query)
            return []

        if not success or not isinstance(payload, Mapping):
            return []
        rows = payload.get("data")
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            return []
        return [row for row in rows if isinstance(row, Mapping)]

    # -- corrections ---------------------------------------------------------

    def _suggest_broader_query(self, query: str, exchange: str) -> None:
        """Retry a search that found nothing, and correct the model if it works.

        Two things go wrong often enough to be worth undoing automatically: an
        exchange filter that excludes the instrument, and a whole contract
        symbol pasted where its underlying was wanted.

        Args:
            query: The query that found nothing.
            exchange: The exchange filter that was applied, if any.

        Raises:
            RetryAgentRun: When a broader query does find something.
        """
        root = self._root(query)
        attempts: list[tuple[str, str, str]] = []
        if exchange:
            attempts.append((query, "", f"dropping the exchange filter {exchange}"))
        if root and root != query.upper():
            if exchange:
                attempts.append((root, exchange, f"searching for the underlying {root} instead"))
            attempts.append((root, "", f"searching for the underlying {root} on every exchange"))

        for text, venue, description in attempts:
            pairs = self._pairs(self._quiet_search(text, venue))
            if not pairs:
                continue
            raise RetryAgentRun(
                f"Nothing matches {query!r}"
                + (f" on {exchange}" if exchange else "")
                + f", but {description} finds listed contracts: {self._render(pairs)}. "
                "Call search_symbols again with the query and exchange that work, then use a "
                "symbol exactly as it comes back."
            )

    def _suggest_underlying(self, underlying: str, exchange: str, kind: str) -> None:
        """Correct an expiry lookup that matched no underlying.

        Args:
            underlying: The underlying that returned no expiries.
            exchange: The derivatives exchange that was queried.
            kind: ``options`` or ``futures``.

        Raises:
            RetryAgentRun: When a similar underlying is listed somewhere.
        """
        root = self._root(underlying) or underlying
        attempts = (
            (exchange, False, f"do have {kind} contracts on {exchange}", "one of them"),
            ("", True, "are listed on other exchanges", "the underlying and exchange that match"),
        )
        for venue, with_exchange, where, correction in attempts:
            rows = self._quiet_search(root, venue)
            # The failed underlying is excluded only while searching the same
            # exchange, where repeating it says nothing. Across exchanges it is
            # the whole answer: SENSEX options are on BFO, not on NFO.
            names = self._underlyings(
                rows, exclude="" if with_exchange else underlying, with_exchange=with_exchange
            )
            if with_exchange:
                # Whatever else turns up, do not offer back the pair that just
                # produced no expiries.
                names = [name for name in names if name != f"{underlying} ({exchange})"]
            if not names:
                continue
            raise RetryAgentRun(
                f"{underlying} has no live {kind} expiries on {exchange}. These underlyings "
                f"{where}: {', '.join(names)}. Call get_expiry_dates again with {correction}, or "
                "use search_symbols if none of them is what the operator meant."
            )

    def _raise_not_listed(
        self, symbol: str, exchange: str, original: RetryAgentRun | None
    ) -> NoReturn:
        """Report an unlisted contract with the listed contracts nearest to it.

        Args:
            symbol: The symbol that was not found.
            exchange: The exchange it was looked for on.
            original: The failure the service produced, re-raised when there is
                nothing better to say.

        Raises:
            RetryAgentRun: Always.
        """
        root = self._root(symbol)
        for text, venue, where in (
            (symbol, exchange, f"on {exchange}"),
            (symbol, "", "on another exchange"),
            (root, exchange, f"on {exchange}"),
            (root, "", "on another exchange"),
        ):
            pairs = [
                pair
                for pair in self._pairs(self._quiet_search(text, venue))
                if (pair[0].upper(), pair[1]) != (symbol.upper(), exchange)
            ]
            if not pairs:
                continue
            raise RetryAgentRun(
                f"{symbol} is not listed on {exchange}. These contracts are listed {where}: "
                f"{self._render(pairs)}. Use one of those symbols exactly as written, or call "
                "search_symbols to see the rest. Do not adjust an expiry or a strike yourself to "
                "make a symbol fit."
            )

        if original is not None:
            raise original
        raise RetryAgentRun(
            f"{symbol} is not listed on {exchange}, and nothing similar is listed anywhere. "
            "Ask the operator which instrument they mean rather than guessing a symbol."
        )

    # -- shaping -------------------------------------------------------------

    def _wrap(self, tool: str, payload: Any, **attributes: Any) -> str:
        """Serialise a result and label it as data before it re-enters context.

        Args:
            tool: The tool's registered name.
            payload: The result to return.
            **attributes: Labels for the opening tag, such as the symbol the
                result is about. A None value is omitted.

        Returns:
            A ``<tool_result>`` block holding the capped JSON.
        """
        return wrap_tool_result(tool, self.to_json(payload), **attributes)

    @staticmethod
    def _compact(row: Mapping[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
        """Narrow one instrument-master row to the fields worth returning.

        Args:
            row: The row as the service produced it.
            fields: Field names to keep, in the order the model should see them.

        Returns:
            The kept fields, with absent ones dropped.
        """
        out: dict[str, Any] = {}
        for field in fields:
            if field not in row:
                continue
            value = row[field]
            if value is None or value == "":
                continue
            if field in _OMIT_WHEN_EMPTY and not value:
                continue
            out[field] = value
        return out

    @staticmethod
    def _root(text: str) -> str:
        """Return the leading letters of a symbol, which are its underlying.

        Args:
            text: A symbol or a query.

        Returns:
            The leading run of letters in capitals, empty when there is none.
        """
        match = _ROOT_PATTERN.match(text.strip())
        return match.group(0).upper() if match else ""

    @staticmethod
    def _pairs(
        rows: Sequence[Mapping[str, Any]], limit: int | None = MAX_SUGGESTIONS
    ) -> list[tuple[str, str]]:
        """Turn search rows into symbol and exchange pairs safe to name in prose.

        A correction message is plain text outside any wrapped block, so each
        candidate is checked against the shape a real code has and dropped when
        it does not fit. Dropping is deliberate: a repaired symbol would name a
        different contract, which is worse than suggesting nothing.

        Args:
            rows: Search rows.
            limit: How many pairs to keep. None keeps every usable row, which is
                what the underlying reduction needs: a search for NIFTY on NFO
                returns hundreds of NIFTY option contracts before the first
                different underlying appears, so stopping at eight rows would
                find exactly one root and it would be the one that just failed.

        Returns:
            Unique pairs, in relevance order.
        """
        pairs: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            symbol = str(row.get("symbol") or "").strip()
            exchange = str(row.get("exchange") or "").strip().upper()
            if not _SAFE_SYMBOL.match(symbol) or not _SAFE_EXCHANGE.match(exchange):
                continue
            pair = (symbol.upper(), exchange)
            if pair in seen:
                continue
            seen.add(pair)
            pairs.append((symbol, exchange))
            if limit is not None and len(pairs) >= limit:
                break
        return pairs

    @classmethod
    def _underlyings(
        cls, rows: Sequence[Mapping[str, Any]], exclude: str = "", with_exchange: bool = False
    ) -> list[str]:
        """Reduce contract symbols to the distinct underlyings behind them.

        A search for NIFTY on NFO returns option contracts, not the underlying.
        For an expiry correction the useful answer is the base symbol, so the
        expiry segment and everything after it is stripped off.

        Args:
            rows: Search rows.
            exclude: An underlying to leave out, normally the one that failed.
            with_exchange: True to append the exchange to each name, which is
                required whenever the search was not filtered to one exchange:
                naming an underlying without saying where it trades leaves the
                model no better off than it was.

        Returns:
            Up to :data:`MAX_SUGGESTIONS` distinct underlyings.
        """
        skip = exclude.strip().upper()
        names: list[str] = []
        seen: set[str] = set()
        for symbol, exchange in cls._pairs(rows, limit=None):
            match = _UNDERLYING_PATTERN.match(symbol.upper())
            name = match.group(1) if match else symbol.upper()
            key = f"{name}:{exchange}" if with_exchange else name
            if not name or name == skip or key in seen:
                continue
            seen.add(key)
            names.append(f"{name} ({exchange})" if with_exchange else name)
            if len(names) >= MAX_SUGGESTIONS:
                break
        return names

    @staticmethod
    def _expiry_entries(dates: Any) -> list[dict[str, str]]:
        """Pair each expiry with the form an OpenAlgo symbol spells it in.

        Args:
            dates: The service's list of expiry strings.

        Returns:
            One entry per usable date, carrying ``expiry`` as stored and
            ``symbol_expiry`` as ``DDMMMYY`` when the date parses. Order is
            preserved, because the service already sorted it chronologically.
        """
        if not isinstance(dates, Sequence) or isinstance(dates, (str, bytes)):
            return []

        entries: list[dict[str, str]] = []
        for value in dates:
            if not isinstance(value, str) or not value.strip():
                continue
            expiry = value.strip().upper()
            entry = {"expiry": expiry}
            spelled = symbol_expiry(expiry)
            if spelled:
                entry["symbol_expiry"] = spelled
            entries.append(entry)
        return entries

    @staticmethod
    def _render(pairs: Sequence[tuple[str, str]]) -> str:
        """Render candidate contracts for a correction message.

        Args:
            pairs: Symbol and exchange pairs.

        Returns:
            A comma-separated list such as ``NIFTY28MAR2420800CE (NFO)``.
        """
        return ", ".join(f"{symbol} ({exchange})" for symbol, exchange in pairs)
