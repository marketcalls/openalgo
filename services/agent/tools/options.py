"""Options analytics: the chain, strike resolution, Greeks and the synthetic future.

Four read-only tools over four internal services. Nothing here mutates anything,
so no tool in this toolkit requires confirmation and none writes an audit row.

What the model has to be told, and why it is in the docstrings
-------------------------------------------------------------

* **The chain is the cheap way to get Greeks.**
  ``get_option_chain(with_greeks=True)`` inverts implied volatility and prices
  delta, gamma, theta and vega from the quotes it has already fetched, in one
  vectorised Black-76 pass. It costs no broker request beyond the chain itself,
  and it is not bound by the 50-symbol cap the platform's batch Greeks endpoint
  enforces. ``get_option_greeks`` is the single-contract tool; a model that
  reaches for it forty times to cover a ladder makes forty round trips for data
  one call already had. The docstrings say so on both sides.

* **A full chain does not fit in a tool result.**
  The service treats ``strike_count=None`` as "every listed strike", which for a
  NIFTY weekly is hundreds of rows. The tool's default is a small window around
  ATM, and asking for the whole chain is spelled explicitly rather than being
  what happens when the argument is left out.

* **Greeks come from the service, and this module computes none of them.**
  They are Black-76 off a forward derived from the ATM call and put by put-call
  parity, not off spot, because Indian index futures carry a premium over spot
  and pricing a chain off the spot LTP biases every delta. That belongs to
  ``services/option_greeks_service.py``; this file only names the convention so
  the model reads the numbers correctly.

Result budget
-------------

``OpenAlgoToolkit.to_json`` caps a result at :data:`~services.agent.tools.base.MAX_JSON_CHARS`
characters, and a chain row with Greeks costs roughly 700 of them. An oversized
result would come back as a truncation envelope holding JSON cut mid-value, which
is close to useless. :func:`_narrow_chain_to_budget` drops whole strikes from the
outside in instead, keeping a contiguous window centred on ATM and saying how many
were dropped, which is the base class's own advice: a tool that knows its result
is a list should slice it rather than let characters be dropped.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from services.agent.prompts import wrap_tool_result
from services.agent.tools.base import (
    MAX_JSON_CHARS,
    OpenAlgoToolkit,
    dumps_capped,
    invalid_argument,
)
from services.option_chain_service import get_option_chain as fetch_option_chain
from services.option_greeks_service import get_option_greeks as fetch_option_greeks
from services.option_symbol_service import get_option_symbol as resolve_option_symbol
from services.synthetic_future_service import calculate_synthetic_future as fetch_synthetic_future
from utils.constants import FNO_EXCHANGES, VALID_EXCHANGES
from utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from services.agent.tools import ToolContext

logger = get_logger(__name__)

#: Strikes on each side of ATM when the model does not say. Eleven strikes with
#: Greeks is about 7,600 characters, which fits one result with room to spare.
DEFAULT_STRIKE_COUNT = 5

#: Upper bound on ``strike_count``, matching the REST schema's own limit.
MAX_STRIKE_COUNT = 100

#: The value that means "every listed strike". The service spells this as None;
#: the model needs an integer it can put in a JSON argument, and it has to be
#: explicit rather than being what omitting the argument does.
ALL_STRIKES = 0

#: Exchanges an option contract itself can live on: NFO, BFO, MCX, CDS, BCD,
#: NCDEX, NCO and CRYPTO. Taken from ``utils.constants`` so onboarding a segment
#: is still the one-line change it is there.
OPTION_EXCHANGES: tuple[str, ...] = tuple(sorted(FNO_EXCHANGES))

#: Exchanges an underlying can be named on, which is the wider list because an
#: option chain is asked for by its index, stock or commodity.
UNDERLYING_EXCHANGES: tuple[str, ...] = tuple(VALID_EXCHANGES)

_MONTHS = frozenset(
    {"JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"}
)

# DDMMMYY, the one expiry format every OpenAlgo symbol and service uses.
_EXPIRY_PATTERN = re.compile(r"\A(\d{2})([A-Z]{3})(\d{2})\Z")

# The same expiry appearing inside a symbol, as NIFTY28OCT25FUT carries it.
_EMBEDDED_EXPIRY_PATTERN = re.compile(r"\d{2}[A-Z]{3}\d{2}")

# ATM, ITM1..ITM50, OTM1..OTM50. Same vocabulary the REST schema validates.
_OFFSET_PATTERN = re.compile(r"\A(?:ATM|(?:ITM|OTM)(?:[1-9]|[1-4][0-9]|50))\Z")

_TRUE_WORDS = frozenset({"true", "t", "yes", "y", "1", "on"})
_FALSE_WORDS = frozenset({"false", "f", "no", "n", "0", "off"})

# Effectively no cap, used to measure a payload's real serialised length before
# deciding what to drop.
_UNCAPPED = 1 << 30

_CHAIN_TRIMMED_NOTE = (
    "The full ladder was larger than one tool result can carry, so the strikes farthest from "
    "ATM were dropped. What is returned is a contiguous window centred on the ATM strike. Call "
    "again with a smaller strike_count, or name the specific strike you need, rather than "
    "assuming the missing strikes do not exist."
)


def _measure(payload: Any) -> int:
    """Return the exact character length the toolkit's serialiser would produce.

    Args:
        payload: Any JSON-safe-able object.

    Returns:
        Length of the compact JSON text, uncapped. This is the same serialiser
        :meth:`OpenAlgoToolkit.to_json` uses, so the measurement and the cap
        cannot drift apart.
    """
    return len(dumps_capped(payload, _UNCAPPED))


def _atm_row_index(chain: list[Any], atm_strike: Any) -> int:
    """Locate the ATM row so a trimmed window can be centred on it.

    Args:
        chain: The assembled chain rows.
        atm_strike: The ATM strike the service reported.

    Returns:
        Index of the row whose strike is the ATM strike, or the middle of the
        ladder when the service reported no usable ATM strike.
    """
    for index, row in enumerate(chain):
        if isinstance(row, Mapping) and row.get("strike") == atm_strike:
            return index
    return len(chain) // 2


def _narrow_chain_to_budget(payload: Any, budget: int = MAX_JSON_CHARS) -> Any:
    """Drop the strikes farthest from ATM until the chain fits one tool result.

    Dropping whole rows beats letting the character cap cut the JSON mid-value:
    the model gets valid data plus an honest count of what is missing, instead of
    a string that stops in the middle of a strike.

    Args:
        payload: The service's chain response.
        budget: Characters the serialised result may occupy.

    Returns:
        The payload unchanged when it already fits, otherwise a copy whose
        ``chain`` is a contiguous window centred on ATM, carrying
        ``strikes_returned``, ``strikes_omitted`` and a note telling the model
        what happened and how to ask for less.
    """
    if not isinstance(payload, Mapping):
        return payload

    chain = payload.get("chain")
    if not isinstance(chain, list) or len(chain) <= 1:
        return payload

    if _measure(payload) <= budget:
        return payload

    centre = _atm_row_index(chain, payload.get("atm_strike"))

    # Measure the response with no rows at all, including the fields the trimmed
    # copy will carry, so the row budget is what is genuinely left over.
    skeleton = dict(payload)
    skeleton["chain"] = []
    skeleton["strikes_returned"] = len(chain)
    skeleton["strikes_omitted"] = len(chain)
    skeleton["note"] = _CHAIN_TRIMMED_NOTE
    used = _measure(skeleton)

    # One extra character per row for the comma that joins it to its neighbour.
    sizes = [_measure(row) + 1 for row in chain]

    low = high = centre
    used += sizes[centre]
    while True:
        grew = False
        if low > 0 and used + sizes[low - 1] <= budget:
            low -= 1
            used += sizes[low]
            grew = True
        if high + 1 < len(chain) and used + sizes[high + 1] <= budget:
            high += 1
            used += sizes[high]
            grew = True
        if not grew:
            break

    kept = chain[low : high + 1]
    logger.info(
        "Agent options chain trimmed to %d of %d strikes to fit the result budget",
        len(kept),
        len(chain),
    )

    trimmed = dict(payload)
    trimmed["chain"] = kept
    trimmed["strikes_returned"] = len(kept)
    trimmed["strikes_omitted"] = len(chain) - len(kept)
    trimmed["note"] = _CHAIN_TRIMMED_NOTE
    return trimmed


# ---------------------------------------------------------------------------
# Shared argument handling
# ---------------------------------------------------------------------------
#
# Module level rather than methods because the visualization toolkit asks for
# the same chain, by the same underlying, exchange, expiry and strike count. A
# second copy of these checks would drift from this one.


def normalise_symbol(value: Any, field: str) -> str:
    """Normalise a symbol argument to the upper case the platform stores.

    Args:
        value: The model's value.
        field: Argument name, used in the failure message.

    Returns:
        The trimmed, upper-cased symbol.

    Raises:
        RetryAgentRun: If it is empty.
    """
    text = "" if value is None else str(value).strip().upper()
    if not text:
        invalid_argument(
            field,
            "it is empty.",
            "Pass the symbol, for example 'NIFTY' for an underlying or "
            "'NIFTY28NOV2524000CE' for a contract.",
        )
    return text


def normalise_exchange(value: Any, allowed: tuple[str, ...]) -> str:
    """Check an exchange code against the codes that segment accepts.

    Args:
        value: The model's value.
        allowed: The exchange codes this argument permits.

    Returns:
        The trimmed, upper-cased exchange code.

    Raises:
        RetryAgentRun: If it is not one of ``allowed``.
    """
    text = "" if value is None else str(value).strip().upper()
    if text not in allowed:
        invalid_argument(
            "exchange",
            f"{text or 'it'} is not an exchange this tool accepts.",
            f"Use one of: {', '.join(allowed)}.",
        )
    return text


def normalise_expiry(value: Any, underlying: str, allow_embedded: bool) -> str:
    """Check an expiry against the DDMMMYY format every service expects.

    Args:
        value: The model's value.
        underlying: The already-normalised underlying, checked for an embedded
            expiry when the argument is empty.
        allow_embedded: True when an empty value is acceptable because the
            underlying may carry the expiry itself.

    Returns:
        The trimmed, upper-cased expiry, or an empty string when the underlying
        carries it.

    Raises:
        RetryAgentRun: If it is missing where it is required, or malformed.
    """
    text = "" if value is None else str(value).strip().upper()

    if not text:
        if allow_embedded and _EMBEDDED_EXPIRY_PATTERN.search(underlying):
            return ""
        invalid_argument(
            "expiry_date",
            (
                "no expiry was given and the underlying does not carry one."
                if allow_embedded
                else "no expiry was given, and this tool needs one named explicitly."
            ),
            "Pass the expiry in DDMMMYY format, for example '28NOV25'. Look up the "
            "listed expiries first rather than guessing a date.",
        )

    match = _EXPIRY_PATTERN.match(text)
    if not match or match.group(2) not in _MONTHS:
        invalid_argument(
            "expiry_date",
            f"{text!r} is not a DDMMMYY expiry.",
            "Use two digits for the day, a three-letter month and two digits for the "
            "year, for example '28NOV25' or '05JAN26'.",
        )
    return text


def normalise_int(value: Any, field: str, minimum: int, maximum: int) -> int:
    """Coerce a whole-number argument and check its range.

    A model routinely sends ``"5"`` or ``5.0`` where an integer is wanted, so
    both are accepted; anything that is not a whole number in range is refused
    with the range spelled out.

    Args:
        value: The model's value.
        field: Argument name, used in the failure message.
        minimum: Smallest acceptable value, inclusive.
        maximum: Largest acceptable value, inclusive.

    Returns:
        The value as an int.

    Raises:
        RetryAgentRun: If it is not a whole number inside the range.
    """
    if isinstance(value, bool):
        number = None
    elif isinstance(value, int):
        number = value
    elif isinstance(value, float):
        number = int(value) if value.is_integer() else None
    else:
        text = "" if value is None else str(value).strip()
        try:
            parsed = float(text)
        except ValueError:
            number = None
        else:
            number = int(parsed) if parsed.is_integer() else None

    if number is None or not minimum <= number <= maximum:
        invalid_argument(
            field,
            f"{value!r} is not a whole number between {minimum} and {maximum}.",
            f"Pass an integer in that range; {DEFAULT_STRIKE_COUNT} is a sensible "
            f"{field} for a first look.",
        )
    return number


class OptionsToolkit(OpenAlgoToolkit):
    """Option chain, strike resolution, Greeks and the synthetic future.

    Every tool reads; none of them places, modifies or cancels anything, so the
    toolkit declares no confirmation-gated tool. Instance attributes are set by
    the base class before agno introspects the bound methods, which is why this
    subclass assigns nothing of its own.
    """

    def __init__(self, context: ToolContext) -> None:
        """Register the four options tools.

        Args:
            context: The run's tool context, carrying the OpenAlgo API key the
                service layer resolves the broker session from.
        """
        super().__init__(
            context,
            name="options",
            tools=[
                self.get_option_chain,
                self.get_option_symbol,
                self.get_option_greeks,
                self.get_synthetic_future,
            ],
        )

    # -- tools ---------------------------------------------------------------

    def get_option_chain(
        self,
        underlying: str,
        exchange: str,
        expiry_date: str,
        strike_count: int = DEFAULT_STRIKE_COUNT,
        with_greeks: bool = False,
    ) -> str:
        """Fetch the option chain around ATM for one underlying and one expiry.

        Returns a strike ladder centred on the at-the-money strike, with a call
        and a put leg per strike, each carrying its live quote, its lot size and
        its ATM/ITM/OTM label. Set ``with_greeks`` to add implied volatility and
        delta, gamma, theta and vega to every leg.

        Prefer this over ``get_option_greeks`` for anything covering more than a
        contract or two. The Greeks here are computed from the quotes this call
        has already fetched, so they cost no extra broker request, and they are
        not bound by the 50-symbol cap the platform's batch Greeks path enforces.
        Calling ``get_option_greeks`` once per strike is many broker round trips
        for data this single call already returned.

        Keep ``strike_count`` small. A strike with Greeks costs roughly 700
        characters of the result budget, so about 7 strikes each side is the most
        that fits; beyond that the strikes farthest from ATM are dropped to keep
        the result valid, and ``strikes_omitted`` reports how many.

        Args:
            underlying: Underlying symbol, not an option symbol. ``NIFTY``,
                ``BANKNIFTY``, ``SENSEX``, ``RELIANCE``, ``CRUDEOIL``, ``BTC``. A
                futures symbol that carries its own expiry, such as
                ``NIFTY28OCT25FUT``, is accepted and its embedded expiry then
                wins over ``expiry_date``.
            exchange: Exchange of the **underlying**, not of the options.
                ``NSE_INDEX`` for NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY;
                ``BSE_INDEX`` for SENSEX, BANKEX; ``NSE`` or ``BSE`` for a stock;
                ``MCX`` for a commodity; ``CDS`` or ``BCD`` for currency;
                ``CRYPTO`` for crypto. ``NFO`` and ``BFO`` are accepted too and
                are mapped back to the right underlying automatically.
            expiry_date: Expiry in DDMMMYY format, for example ``28NOV25`` or
                ``30DEC25``. Look the expiry up first rather than guessing one; a
                date with no listed contracts returns an error, not an empty
                chain. Pass an empty string only when ``underlying`` already
                carries the expiry, as ``NIFTY28OCT25FUT`` does.
            strike_count: How many strikes to return on each side of ATM, so the
                ladder is ``2 * strike_count + 1`` strikes wide. Defaults to 5,
                which is 11 strikes. Pass 0 for the entire listed chain, which is
                rarely wanted: a NIFTY weekly runs to hundreds of strikes, takes
                far longer to fetch, and is trimmed to fit the result anyway. The
                maximum is 100.
            with_greeks: True to attach ``implied_volatility``, ``delta``,
                ``gamma``, ``theta`` and ``vega`` to every leg. Costs no extra
                broker request. The Greeks are Black-76, priced off a forward
                derived from the ATM call and put by put-call parity rather than
                off the spot price, because an index future trades at a premium
                to spot and pricing off spot biases every delta.

        Returns:
            JSON carrying ``underlying``, ``underlying_ltp``, ``expiry_date``,
            ``atm_strike``, ``forward_price`` and ``chain``: one row per strike
            with ``strike``, ``ce`` and ``pe``. Each leg holds ``symbol``,
            ``label`` (ATM, ITM1.., OTM1..), ``ltp``, ``bid``, ``ask``,
            ``volume``, ``oi``, ``lotsize`` and ``tick_size``, plus the Greeks
            when they were requested. A leg the exchange does not list is null.
            ``theta`` is per day and ``vega`` per one point of implied
            volatility. When the ladder was too large for one result,
            ``strikes_returned`` and ``strikes_omitted`` say what was dropped.
        """
        underlying = self._symbol_argument(underlying, "underlying")
        exchange = self._exchange_argument(exchange, UNDERLYING_EXCHANGES)
        expiry = self._expiry_argument(expiry_date, underlying, allow_embedded=True)
        count = self._int_argument(strike_count, "strike_count", ALL_STRIKES, MAX_STRIKE_COUNT)
        greeks = self._bool_argument(with_greeks, "with_greeks")

        payload = self.service_call(
            fetch_option_chain,
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry,
            strike_count=None if count == ALL_STRIKES else count,
            with_greeks=greeks,
        )

        return wrap_tool_result(
            "get_option_chain",
            self.to_json(_narrow_chain_to_budget(payload)),
            underlying=underlying,
            exchange=exchange,
            expiry=expiry or None,
        )

    def get_option_symbol(
        self,
        underlying: str,
        exchange: str,
        expiry_date: str,
        offset: str,
        option_type: str,
    ) -> str:
        """Resolve one tradable option symbol from an offset relative to ATM.

        Use this to turn "the second out-of-the-money NIFTY call for the 28NOV25
        expiry" into the exact OpenAlgo symbol, lot size and tick size an order
        needs. The strike is picked from the strikes the exchange actually lists,
        so an underlying with uneven strike spacing resolves correctly and a
        symbol that does not exist is reported rather than invented.

        For a view of several strikes at once, call ``get_option_chain``: one
        request covers the whole ladder and every leg comes back with its symbol
        already resolved.

        Args:
            underlying: Underlying symbol, not an option symbol. ``NIFTY``,
                ``BANKNIFTY``, ``SENSEX``, ``RELIANCE``, ``CRUDEOIL``. A futures
                symbol carrying its own expiry, such as ``NIFTY28OCT25FUT``, is
                accepted and its embedded expiry is used.
            exchange: Exchange of the **underlying**. ``NSE_INDEX`` for NIFTY,
                BANKNIFTY, FINNIFTY, MIDCPNIFTY; ``BSE_INDEX`` for SENSEX,
                BANKEX; ``NSE`` or ``BSE`` for a stock; ``MCX``, ``CDS``,
                ``BCD``, ``NCDEX``, ``NCO``, ``CRYPTO`` for their own products.
                ``NFO`` and ``BFO`` are accepted and mapped back automatically.
            expiry_date: Expiry in DDMMMYY format, for example ``28OCT25``. Pass
                an empty string only when ``underlying`` already carries the
                expiry.
            offset: Which strike to take, counted in **listed strikes** away from
                ATM rather than in points. ``ATM`` is the listed strike nearest
                the underlying price. ``ITM1`` to ``ITM50`` step into the money
                and ``OTM1`` to ``OTM50`` step out of it, one listed strike per
                step. In the money is a **lower** strike for a CE and a
                **higher** strike for a PE; out of the money is the opposite.
                With NIFTY at 24230 and strikes listed every 50, ATM is 24250,
                so: ``OTM2`` with option_type CE is 24350, ``ITM2`` with CE is
                24150, ``OTM2`` with PE is 24150, ``ITM2`` with PE is 24350. Case
                does not matter. An offset past the end of the listed ladder is
                an error, not a clamp to the last strike.
            option_type: ``CE`` for a call or ``PE`` for a put.

        Returns:
            JSON with ``symbol`` (the OpenAlgo option symbol to trade),
            ``exchange`` (the derivatives exchange the contract lists on, such as
            NFO, which is not the exchange you passed in), ``lotsize``,
            ``tick_size``, ``freeze_qty`` (the largest quantity the exchange
            accepts in one order) and ``underlying_ltp`` (the price ATM was
            resolved against).
        """
        underlying = self._symbol_argument(underlying, "underlying")
        exchange = self._exchange_argument(exchange, UNDERLYING_EXCHANGES)
        expiry = self._expiry_argument(expiry_date, underlying, allow_embedded=True)
        offset = self._offset_argument(offset)
        option_type = self._option_type_argument(option_type)

        payload = self.service_call(
            resolve_option_symbol,
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry or None,
            # None selects the strikes the exchange actually lists, instead of
            # deriving them from an assumed interval, which is what constructs
            # symbols that do not exist wherever spacing is uneven.
            strike_int=None,
            offset=offset,
            option_type=option_type,
        )

        return wrap_tool_result(
            "get_option_symbol",
            self.to_json(payload),
            underlying=underlying,
            exchange=exchange,
            expiry=expiry or None,
            offset=offset,
            option_type=option_type,
        )

    def get_option_greeks(self, symbol: str, exchange: str) -> str:
        """Fetch implied volatility and the Greeks for one option contract.

        This is the single-contract tool. For a ladder, a spread, or any question
        about more than a couple of strikes, call ``get_option_chain`` with
        ``with_greeks=True`` instead: it returns the same Greeks for every leg
        from quotes it has already fetched, costs no extra broker request, and is
        not limited to 50 symbols the way the batch Greeks path is. Calling this
        tool repeatedly across a chain is the slow way to get data one call
        already had.

        The numbers are Black-76, priced off the forward for that expiry, which
        is derived from the ATM call and put by put-call parity where those are
        available and falls back to the underlying spot otherwise. Read them as
        given; do not recompute or re-scale them.

        Args:
            symbol: The exact OpenAlgo option symbol, in
                ``[Base][DDMMMYY][Strike][CE|PE]`` form, for example
                ``NIFTY28NOV2524000CE`` or ``VEDL25APR24292.5PE``. Resolve it
                with ``get_option_symbol`` or read it from a chain leg first; a
                symbol assembled by guesswork usually does not exist.
            exchange: The exchange the **option** lists on, which is not the
                underlying's exchange. One of NFO, BFO, MCX, CDS, BCD, NCDEX,
                NCO, CRYPTO. A NIFTY option is NFO, a SENSEX option is BFO.

        Returns:
            JSON with ``symbol``, ``underlying``, ``strike``, ``option_type``,
            ``expiry_date``, ``days_to_expiry``, ``option_price``,
            ``interest_rate``, ``implied_volatility`` (annualised percentage),
            ``spot_price`` (the forward the Greeks were priced off, not
            necessarily the spot LTP) and ``greeks`` holding ``delta``,
            ``gamma``, ``theta``, ``vega`` and ``rho``. ``theta`` is per day and
            ``vega`` is per one point of implied volatility.
        """
        symbol = self._symbol_argument(symbol, "symbol")
        exchange = self._exchange_argument(exchange, OPTION_EXCHANGES)

        payload = self.service_call(
            fetch_option_greeks,
            option_symbol=symbol,
            exchange=exchange,
        )

        return wrap_tool_result(
            "get_option_greeks",
            self.to_json(payload),
            symbol=symbol,
            exchange=exchange,
        )

    def get_synthetic_future(self, underlying: str, exchange: str, expiry_date: str) -> str:
        """Compute the forward the options market is pricing for one expiry.

        The synthetic future is what the ATM call and put imply the underlying
        will be worth at expiry: ``strike + call price - put price``. Compare it
        with the spot price to read the basis, or with the listed future to spot
        a dislocation. It is also the reference every Black-76 Greek in this
        toolkit is priced off, which is why a chain's own ``forward_price`` and
        this number agree.

        When a chain is being fetched anyway, ``get_option_chain`` already
        returns ``forward_price`` for that expiry, so this tool is for the case
        where the forward is the whole question.

        Args:
            underlying: Plain underlying symbol: ``NIFTY``, ``BANKNIFTY``,
                ``SENSEX``, ``RELIANCE``. Unlike the other tools here this one
                takes the base symbol only, never a futures symbol with the
                expiry inside it.
            exchange: Exchange of the **underlying**. ``NSE_INDEX`` for NIFTY,
                BANKNIFTY, FINNIFTY, MIDCPNIFTY; ``BSE_INDEX`` for SENSEX,
                BANKEX; ``NSE`` or ``BSE`` for a stock; ``MCX``, ``CDS``,
                ``BCD``, ``NCDEX``, ``NCO``, ``CRYPTO`` for their own products.
            expiry_date: Expiry in DDMMMYY format, for example ``28OCT25``.
                Required: every expiry has its own forward.

        Returns:
            JSON with ``underlying``, ``underlying_ltp`` (the spot or near-month
            reference price), ``expiry``, ``atm_strike`` and
            ``synthetic_future_price``. The basis is
            ``synthetic_future_price - underlying_ltp``: positive means the
            options are pricing a premium to spot, which is normal for an index
            before expiry.
        """
        underlying = self._symbol_argument(underlying, "underlying")
        exchange = self._exchange_argument(exchange, UNDERLYING_EXCHANGES)
        expiry = self._expiry_argument(expiry_date, underlying, allow_embedded=False)

        # This service recovers the ATM strike by removing the underlying and the
        # expiry from the resolved option symbol, so a symbol that already
        # carries its expiry leaves nothing that parses as a number. Refuse it
        # here with the fix, rather than letting it fail as a parse error the
        # model cannot act on.
        if _EMBEDDED_EXPIRY_PATTERN.search(underlying):
            self.invalid_argument(
                "underlying",
                f"{underlying!r} carries its own expiry, which this tool cannot take.",
                "Pass the base symbol on its own, such as 'NIFTY', and name the expiry in "
                "expiry_date.",
            )

        payload = self.service_call(
            fetch_synthetic_future,
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry,
        )

        return wrap_tool_result(
            "get_synthetic_future",
            self.to_json(payload),
            underlying=underlying,
            exchange=exchange,
            expiry=expiry or None,
        )

    # -- argument checking ---------------------------------------------------
    #
    # Every check here runs before a broker request is spent, and every failure
    # raises RetryAgentRun through invalid_argument, so the model is told which
    # argument to correct and what a valid value looks like instead of being
    # handed a service error it has to interpret.

    def _symbol_argument(self, value: Any, field: str) -> str:
        """Delegate to :func:`normalise_symbol`, kept for call-site readability."""
        return normalise_symbol(value, field)

    def _exchange_argument(self, value: Any, allowed: tuple[str, ...]) -> str:
        """Delegate to :func:`normalise_exchange`."""
        return normalise_exchange(value, allowed)

    def _expiry_argument(self, value: Any, underlying: str, allow_embedded: bool) -> str:
        """Delegate to :func:`normalise_expiry`."""
        return normalise_expiry(value, underlying, allow_embedded)

    def _offset_argument(self, value: Any) -> str:
        """Check a strike offset against the ATM/ITMn/OTMn vocabulary.

        Args:
            value: The model's value.

        Returns:
            The trimmed, upper-cased offset.
        """
        text = "" if value is None else str(value).strip().upper()
        if not _OFFSET_PATTERN.match(text):
            self.invalid_argument(
                "offset",
                f"{text or 'it'} is not a strike offset.",
                "Use 'ATM', or 'ITM' or 'OTM' followed by 1 to 50, for example 'OTM2'. "
                "Each step is one listed strike, not one point of price.",
            )
        return text

    def _option_type_argument(self, value: Any) -> str:
        """Check an option type is a call or a put.

        Args:
            value: The model's value.

        Returns:
            ``CE`` or ``PE``.
        """
        text = "" if value is None else str(value).strip().upper()
        if text not in ("CE", "PE"):
            self.invalid_argument(
                "option_type",
                f"{text or 'it'} is not an option type.",
                "Use 'CE' for a call or 'PE' for a put.",
            )
        return text

    def _int_argument(self, value: Any, field: str, minimum: int, maximum: int) -> int:
        """Delegate to :func:`normalise_int`."""
        return normalise_int(value, field, minimum, maximum)

    def _bool_argument(self, value: Any, field: str) -> bool:
        """Coerce a true/false argument, accepting the words a model may send.

        Args:
            value: The model's value.
            field: Argument name, used in the failure message.

        Returns:
            The value as a bool.
        """
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        if isinstance(value, (int, float)):
            return bool(value)

        text = str(value).strip().lower()
        if text in _TRUE_WORDS:
            return True
        if text in _FALSE_WORDS or not text:
            return False

        self.invalid_argument(
            field,
            f"{value!r} is not true or false.",
            "Pass true or false.",
        )
