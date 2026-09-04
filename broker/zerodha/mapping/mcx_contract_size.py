"""MCX lot sizes, and the unit conversion Kite needs because of them.

Why this table exists
---------------------
Zerodha's instrument dump (``https://api.kite.trade/instruments/MCX``) reports
``lot_size = 1`` for every one of its ~15,000 MCX rows -- futures, options and
indices alike. That is not a data bug. For MCX, Kite denominates order
``quantity`` in *contracts*, so one contract is quantity 1. Zerodha say so
directly:

    "For all MCX instruments we say quantity(trading quantity) is 1 since
    exchange supports like that."
    -- https://kite.trade/forum/discussion/14531/

Every other Indian broker denominates MCX quantity in *units* and ships the
real market lot in its master contract -- Angel One reports CRUDEOIL as 100 and
COPPER as 2500. Left alone, the same one-lot crude order is ``quantity: 100`` on
Angel and ``quantity: 1`` on Zerodha, which breaks the promise of the OpenAlgo
API: one request body, any broker.

How this is resolved
--------------------
The same way symbol, product and price type already are. OpenAlgo has one
convention, and each broker adapter translates to whatever its broker speaks.
Here that convention is units, and Kite's contract count is confined to this
adapter:

    symtoken.lotsize   = the real market lot (CRUDEOIL 100), same as Angel
    outbound to Kite   = to_kite_quantity()   units -> contracts  (// lot)
    inbound from Kite  = from_kite_quantity() contracts -> units  (*  lot)

So ``quantity: 100`` on CRUDEOIL is one lot on every broker, and it reaches
api.kite.trade as 1. Nothing outside ``broker/zerodha/`` learns that MCX is
special, and ``quantity: 1`` is refused with the same "multiples of lot size"
error the other brokers already give.

The conversion belongs at a Kite boundary and nowhere else. Applying it twice
places a 100x order or a zero-quantity one, so every call site is either a
payload being built for api.kite.trade or a response just read back from it.

Lot size is not the price multiplier
------------------------------------
These are physical contract sizes, and the unit they are measured in is not
always the unit the contract is *quoted* in:

    GOLD     1 KG     quoted per 10 g   -> price multiplier 100, not 1
    ZINC     5 MT     quoted per kg     -> price multiplier 5000, not 5
    SILVER   30 kg    quoted per kg     -> price multiplier 30 (agrees)

Irrelevant to the conversion here, which is a pure change of quantity units,
but it is why these numbers are not also written to ``contract_value``: the
sandbox multiplies P&L by that field, and doing both would square the factor.

Source
------
https://zerodha.com/margin-calculator/Commodity/ scraped 2026-09-02, taken
verbatim. Cross-checked against Angel One's scrip master, which agrees on 27 of
the 29 rows; the exceptions are the index derivatives MCXBULLDEX and MCXMETLDEX,
which Angel reports as 1 and the calculator as 30 and 40.

Known gap: CARDAMOM has live futures on MCX (Angel reports 100 KGS) but is
absent from the scrape, so it resolves to None here rather than being guessed.
An unmapped underlying converts by a factor of 1, i.e. it keeps the
pass-through behaviour that predates this module.
"""

from __future__ import annotations

#: Underlying root -> units of the commodity in one contract.
#:
#: Keyed on the ``name`` column of Zerodha's MCX dump, which already holds the
#: bare root ("CRUDEOIL", "GOLDM") rather than a contract description, so a
#: direct lookup resolves futures and options alike.
MCX_CONTRACT_SIZES: dict[str, int] = {
    "ALUMINI": 1,
    "ALUMINIUM": 5,
    "COPPER": 2500,
    "COTTON": 25,
    "COTTONOIL": 5,
    "CRUDEOIL": 100,
    "CRUDEOILM": 10,
    "ELECDMBL": 50,
    "GOLD": 1,
    "GOLDGUINEA": 8,
    "GOLDM": 100,
    "GOLDPETAL": 1,
    "GOLDTEN": 10,
    "KAPAS": 4,
    "LEAD": 5,
    "LEADMINI": 1,
    "MCXBULLDEX": 30,
    "MCXMETLDEX": 40,
    "MENTHAOIL": 360,
    "NATGASMINI": 250,
    "NATURALGAS": 1250,
    "NICKEL": 250,
    "SILVER": 30,
    "SILVER100": 100,
    "SILVERM": 5,
    "SILVERMIC": 1,
    "STEELREBAR": 5,
    "ZINC": 5,
    "ZINCMINI": 1,
}

#: Roots longest-first, so prefix matching resolves the specific contract before
#: the general one. "SILVERMIC26SEPFUT" must not match "SILVER", and
#: "CRUDEOILM26SEPFUT" must not match "CRUDEOIL" -- their sizes differ 30x and
#: 10x respectively.
_ROOTS_LONGEST_FIRST: tuple[tuple[str, int], ...] = tuple(
    sorted(MCX_CONTRACT_SIZES.items(), key=lambda kv: -len(kv[0]))
)


class McxQuantityError(ValueError):
    """A quantity cannot be expressed as a whole number of MCX contracts."""


def get_contract_size(underlying: str | None) -> int | None:
    """Units of the commodity in one contract, or None if unknown.

    Takes an exact underlying root, as found in the ``name`` column of Kite's
    MCX dump. Unknown is returned rather than a default of 1 on purpose: 1 is a
    real lot size here (GOLD is 1 KG, SILVERMIC is 1 KG), so a caller cannot
    otherwise tell "one unit per contract" from "we have no idea".

    Anything that is not a string is unknown. The type check is not decoration:
    Kite ships rows with a blank ``name`` (8,000-odd of them on NSE, BSE and
    NCO), pandas reads those as float NaN, and NaN is *truthy* -- a falsiness
    check passes it straight through to ``.strip()`` and takes the whole master
    contract download down with an AttributeError.
    """
    if not isinstance(underlying, str):
        return None
    return MCX_CONTRACT_SIZES.get(underlying.strip().upper())


def units_per_contract(symbol: str | None, exchange: str | None) -> int:
    """Conversion factor between OpenAlgo units and Kite contracts.

    Accepts a full trading symbol in either OpenAlgo or Kite form
    ("CRUDEOIL21SEP26FUT", "CRUDEOIL26SEPFUT", "CRUDEOIL26SEP8650CE") and
    resolves the underlying by longest prefix, since both forms lead with the
    root and neither carries it as a separate field at these call sites.

    Returns 1 -- a no-op conversion -- for every non-MCX exchange and for any
    MCX underlying missing from the table. A factor of 1 is the safe direction
    to fail: quantity reaches Kite unchanged rather than scaled by a number we
    are not sure of.
    """
    if not isinstance(symbol, str) or not symbol:
        return 1
    if not isinstance(exchange, str) or exchange.strip().upper() != "MCX":
        return 1
    text = symbol.strip().upper()
    for root, size in _ROOTS_LONGEST_FIRST:
        if text.startswith(root):
            return size
    return 1


def to_kite_quantity(
    quantity, symbol: str | None, exchange: str | None, field: str = "Quantity"
) -> int:
    """OpenAlgo units -> the contract count Kite expects. Outbound only.

    Args:
        field: what to call the offending value if it will not convert. An
            order carries more than one quantity, and reporting a bad
            ``disclosed_quantity`` as "Quantity" sends the user looking at the
            one field that was fine.

    Raises:
        McxQuantityError: the quantity is not a whole number of contracts.
            Refused rather than rounded -- rounding 150 CRUDEOIL down to 1
            contract silently halves the order, and rounding it up doubles it.
    """
    qty = int(quantity)
    size = units_per_contract(symbol, exchange)
    if size == 1:
        return qty
    contracts, remainder = divmod(abs(qty), size)
    if remainder:
        raise McxQuantityError(
            f"{field} must be in multiples of lot size {size} for {symbol}, got {abs(qty)}"
        )
    return -contracts if qty < 0 else contracts


def from_kite_quantity(quantity, symbol: str | None, exchange: str | None) -> int:
    """Kite contract count -> OpenAlgo units. Inbound only.

    Returns the input unchanged when it cannot be read as a number, so a
    malformed or absent field in a Kite response degrades to pass-through
    rather than breaking the whole orderbook.
    """
    size = units_per_contract(symbol, exchange)
    if size == 1:
        return quantity
    try:
        return int(quantity) * size
    except (TypeError, ValueError):
        return quantity
