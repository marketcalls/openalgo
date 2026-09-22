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

CARDAMOM is absent from that scrape and is sourced from Angel One instead,
which reports 100 on every live expiry. Every other row was verified against
Angel's master as well, and after the MCXBULLDEX revision below the two agree
on all 30.

An underlying in neither source converts by a factor of 1, i.e. it keeps the
pass-through behaviour that predates this module.
"""

from __future__ import annotations

from datetime import date

#: Underlying root -> units of the commodity in one contract.
#:
#: Keyed on the ``name`` column of Zerodha's MCX dump, which already holds the
#: bare root ("CRUDEOIL", "GOLDM") rather than a contract description, so a
#: direct lookup resolves futures and options alike.
MCX_CONTRACT_SIZES: dict[str, int] = {
    "ALUMINI": 1,
    "ALUMINIUM": 5,
    # Absent from the Zerodha calculator scrape; taken from Angel One's scrip
    # master, which carries 100 on all five live expiries. Sourcing it there
    # rather than leaving it unmapped is the same cross-check the other 29 rows
    # already passed, and it is what stops one lot of CARDAMOM meaning 100
    # contracts on Zerodha and one on Angel.
    "CARDAMOM": 100,
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

#: Roots whose contract size MCX has revised, as (first expiry on the new size,
#: new size), ascending. A single number per root is not enough: MCX halved
#: MCXBULLDEX from the November 2026 contract, so September and October 2026
#: trade at 30 while November and December trade at 15, all live at once.
#: Confirmed against Angel One's scrip master, which carries both.
MCX_SIZE_REVISIONS: dict[str, tuple[tuple[date, int], ...]] = {
    "MCXBULLDEX": ((date(2026, 11, 1), 15),),
}

#: Roots longest-first, so prefix matching resolves the specific contract before
#: the general one. "SILVERMIC26SEPFUT" must not match "SILVER", and
#: "CRUDEOILM26SEPFUT" must not match "CRUDEOIL" -- their sizes differ 30x and
#: 10x respectively.
_ROOTS_LONGEST_FIRST: tuple[tuple[str, int], ...] = tuple(
    sorted(MCX_CONTRACT_SIZES.items(), key=lambda kv: -len(kv[0]))
)


#: Underlying root -> units of the QUOTATION basis in one contract, where that
#: differs from the trading unit above. This is the number a price is multiplied
#: by to value one contract, and it is NOT the contract size:
#:
#:     GOLD        traded in 1 kg,   quoted per 10 g   -> 100, lot size 1
#:     GOLDM       traded in 100 g,  quoted per 10 g   -> 10,  lot size 100
#:     GOLDGUINEA  traded in 8 g,    quoted per 8 g    -> 1,   lot size 8
#:     ZINC        traded in 5 MT,   quoted per kg     -> 5000, lot size 5
#:
#: A root absent here quotes in the unit it trades in, so its lot size already
#: is the multiplier -- CRUDEOIL is 100 barrels quoted per barrel, SILVER is
#: 30 kg quoted per kg. Only the gold family, the base metals and three
#: agricultural contracts diverge, and only those are listed.
#:
#: Every entry is `contract size / quotation unit`, written out so the number
#: can be checked against an MCX contract specification without deriving it
#: again. Both halves are stated because the trap here is a comment that
#: describes a different contract from the one the number came from: a reader
#: who trusts the prose over the value talks themselves out of a correct
#: multiplier.
#:
#: Used for DISPLAY VALUATION ONLY. It never sizes an order. For live position
#: P&L, prefer Kite's own `multiplier` field, which is authoritative and arrives
#: with the positionbook; this table exists for the tradebook, where Kite sends
#: no multiplier of its own.
MCX_QUOTATION_MULTIPLIERS: dict[str, int] = {
    "GOLD": 100,  # 1 kg / 10 g
    "GOLDM": 10,  # 100 g / 10 g
    "GOLDGUINEA": 1,  # 8 g / 8 g
    "GOLDTEN": 1,  # 10 g / 10 g
    "SILVER100": 10,  # 100 g / 10 g
    "ZINC": 5000,  # 5 MT / kg
    "ZINCMINI": 1000,  # 1 MT / kg
    "LEAD": 5000,  # 5 MT / kg
    "LEADMINI": 1000,  # 1 MT / kg
    "ALUMINIUM": 5000,  # 5 MT / kg
    "ALUMINI": 1000,  # 1 MT / kg
    "KAPAS": 200,  # 4,000 kg / 20 kg
    "COTTONOIL": 500,  # 5,000 kg / 10 kg
}


def price_multiplier(symbol: str | None, exchange: str | None) -> int:
    """What one contract's price must be multiplied by to value it in rupees.

    Returns 1 off MCX, so a non-MCX quantity times its price is unchanged.

    The underlying is resolved in full before the multiplier is looked up. A
    prefix match against this table alone would read GOLDPETAL as GOLD and
    value a 1 gram contract as though it were a kilo -- the same collision the
    lot-size table is ordered longest-first to avoid, which is why both now go
    through one resolver.
    """
    root = _underlying_root(symbol, exchange)
    if root is None:
        return 1
    multiplier = MCX_QUOTATION_MULTIPLIERS.get(root)
    if multiplier is not None:
        return multiplier
    # Quoted in the unit it trades in: the lot size is the multiplier.
    return units_per_contract(symbol, exchange)


def _underlying_root(symbol: str | None, exchange: str | None) -> str | None:
    """The full MCX underlying a symbol belongs to, or None.

    Resolved against the complete root list longest-first, so GOLDPETAL wins
    over GOLD and SILVERMIC over SILVER.
    """
    if not isinstance(symbol, str) or not symbol:
        return None
    if not isinstance(exchange, str) or exchange.strip().upper() != "MCX":
        return None
    text = symbol.strip().upper()
    for root, _size in _ROOTS_LONGEST_FIRST:
        if text.startswith(root):
            return root
    return None


class McxQuantityError(ValueError):
    """A quantity cannot be expressed as a whole number of MCX contracts."""


def get_contract_size(underlying: str | None, expiry: date | None = None) -> int | None:
    """Units of the commodity in one contract, or None if unknown.

    Takes an exact underlying root, as found in the ``name`` column of Kite's
    MCX dump. Unknown is returned rather than a default of 1 on purpose: 1 is a
    real lot size here (GOLD is 1 KG, SILVERMIC is 1 KG), so a caller cannot
    otherwise tell "one unit per contract" from "we have no idea".

    Args:
        expiry: the contract's expiry. Required to size a root that MCX has
            revised, since its old and new sizes are both live at once. Without
            it the pre-revision size is returned, which is right for the near
            months and wrong for the far ones -- so the master contract, which
            has the expiry on every row, always passes it.

    Anything that is not a string is unknown. The type check is not decoration:
    Kite ships rows with a blank ``name`` (8,000-odd of them on NSE, BSE and
    NCO), pandas reads those as float NaN, and NaN is *truthy* -- a falsiness
    check passes it straight through to ``.strip()`` and takes the whole master
    contract download down with an AttributeError.
    """
    if not isinstance(underlying, str):
        return None
    root = underlying.strip().upper()
    size = MCX_CONTRACT_SIZES.get(root)
    if size is None:
        return None
    if expiry is not None:
        for effective_from, revised in MCX_SIZE_REVISIONS.get(root, ()):
            if expiry >= effective_from:
                size = revised
    return size


def _master_contract_lot_size(symbol: str, exchange: str) -> int | None:
    """The lot size the master contract holds for this exact contract.

    This is the authoritative factor, and not merely a better one. OpenAlgo
    computes an order as ``lots * symtoken.lotsize`` and this module divides
    that back down to contracts, so anything other than the same number turns
    a correct request into a wrong order. Reading the row also makes every
    expiry right for free, since each contract is its own row -- no symbol
    parsing, and no second place to update when MCX revises a size.

    Returns None when the lookup cannot be made (no database, no app context,
    an unseeded table), so the caller falls back to the static table.
    """
    try:
        from database.token_db import get_oa_symbol
        from database.token_db_enhanced import get_symbol_info

        info = get_symbol_info(symbol, exchange)
        if info is None:
            # Inbound call sites hold Kite's tradingsymbol, which is not what
            # symtoken is keyed on. One translation covers both directions.
            oa_symbol = get_oa_symbol(brsymbol=symbol, exchange=exchange)
            if oa_symbol and oa_symbol != symbol:
                info = get_symbol_info(oa_symbol, exchange)
        lot_size = getattr(info, "lotsize", None)
        if lot_size and int(lot_size) > 0:
            return int(lot_size)
    except Exception:
        # Never let a lookup failure break an order path; the table still answers.
        pass
    return None


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

    # The master contract row wins: it is per contract, so it is already right
    # for a root whose size differs by expiry, and it is the same number the
    # quantity was built from.
    return _resolve_size(symbol, exchange) or 1


def _resolve_size(symbol: str | None, exchange: str | None) -> int | None:
    """The conversion factor, or None when it genuinely cannot be established.

    None is returned only for an underlying whose size MCX has revised, when
    the master contract row is unavailable. The static table is keyed by root
    alone, and a root under revision has two live sizes at once -- MCXBULLDEX
    is 30 into October 2026 and 15 from November -- so the table cannot answer
    without an expiry, and the symbol does not reliably carry one: Kite writes
    MCXBULLDEX26NOV30000CE (year, month, strike) where OpenAlgo writes
    MCXBULLDEX27NOV2630000CE (day, month, year, strike), and the two cannot be
    told apart by pattern.

    Guessing the pre-revision size sends half the order or twice it, so the
    callers decide: an outbound conversion refuses, an inbound one passes the
    quantity through unscaled.
    """
    if not isinstance(symbol, str) or not symbol:
        return 1
    if not isinstance(exchange, str) or exchange.strip().upper() != "MCX":
        return 1

    from_master = _master_contract_lot_size(symbol, exchange)
    if from_master is not None:
        return from_master

    text = symbol.strip().upper()
    for root, size in _ROOTS_LONGEST_FIRST:
        if text.startswith(root):
            return None if root in MCX_SIZE_REVISIONS else size
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
    size = _resolve_size(symbol, exchange)
    if size is None:
        raise McxQuantityError(
            f"Cannot size {symbol}: MCX has revised its contract size and the "
            f"master contract has no row for this expiry. Re-download the master "
            f"contract, then retry."
        )
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
