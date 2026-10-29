"""MCX and CDS quantities: OpenAlgo units in, Fyers lots out.

Why this module exists
----------------------
Fyers denominates MCX and CDS order quantity in *lots*. Its own symbol masters
say so: every row of ``MCX_COM_sym_master.json`` and ``NSE_CD_sym_master.json``
has ``minLotSize`` 1, and carries the units in one lot as ``qtyMultiplier``
(CRUDEOILM 10, CRUDEOIL 100, GOLDM 10, USDINR 1000).

The master contract stores that ``qtyMultiplier`` as ``symtoken.lotsize``, so
on these two segments OpenAlgo's quantity is units -- one lot of CRUDEOILM is
``quantity: 10`` and one lot of USDINR is ``quantity: 1000`` -- just as it is on
NFO and on every other broker. Kite has the same mismatch on MCX, and
broker/zerodha/mapping/mcx_contract_size.py translates it the same way.

Until this module, the plugin sent that quantity on to Fyers unchanged as
``qty``, so a one-lot order reached Fyers as 10 or 1000 lots. Fyers' margin
calculator (``POST /api/v3/multiorder/margin``), one buy, 2026-10-29:

    CRUDEOILM19NOV26FUT   qty 1:     30,616   qty 10:     3,05,982
    GOLDM05NOV26FUT       qty 1:   1,31,406   qty 10:    13,13,880
    USDINR26NOV26FUT      qty 1:      2,313   qty 1000:  22,92,585

How it is resolved
------------------
    outbound to Fyers   = to_fyers_qty()    units -> lots   (/ lotsize)
    inbound from Fyers  = from_fyers_qty()  lots  -> units  (* lotsize)

The factor is the ``symtoken.lotsize`` of the exact contract. OpenAlgo builds a
quantity as ``lots * lotsize``, so dividing by any other number turns a correct
request into a wrong order. NSE, BSE, NFO and BFO quantities are units at Fyers
and pass through untouched.

Every call site is either a payload being built for Fyers or a value just read
back from it. Converting twice sends a 10x order or a zero one.
"""

from database.token_db import get_symbol_info
from utils.logging import get_logger

logger = get_logger(__name__)

#: OpenAlgo exchanges whose Fyers ``qty`` counts lots rather than units.
LOT_DENOMINATED_EXCHANGES = frozenset({"MCX", "CDS"})


class LotQuantityError(ValueError):
    """A quantity that is not a whole number of lots, or a contract with no lot size."""


def is_lot_denominated(exchange) -> bool:
    """True for the OpenAlgo exchanges whose Fyers quantity is lots.

    Anything that is not a string is not one of them: a book row whose symbol
    did not map keeps Fyers' numeric exchange code.
    """
    return isinstance(exchange, str) and exchange.strip().upper() in LOT_DENOMINATED_EXCHANGES


def lot_size(symbol, exchange) -> int:
    """``symtoken.lotsize`` of the contract, or 0 when the master contract has none."""
    if not symbol or not isinstance(exchange, str):
        return 0
    try:
        info = get_symbol_info(symbol, exchange.strip().upper())
        size = int(float(getattr(info, "lotsize", 0) or 0))
    except Exception:
        # A failed lookup must not break a book; to_fyers_qty refuses on 0.
        logger.exception(f"Lot size lookup failed for {exchange}:{symbol}")
        return 0
    return max(size, 0)


def to_fyers_qty(quantity, symbol, exchange, field="Quantity") -> int:
    """OpenAlgo units -> the quantity Fyers expects. Outbound only.

    Lots on MCX and CDS; unchanged on every other exchange.

    Args:
        quantity: the OpenAlgo quantity, already parsed by the caller.
        field: what to call the value in an error. An order carries more than
            one quantity, and blaming "Quantity" for a bad disclosed quantity
            points the user at the field that was fine.

    Raises:
        LotQuantityError: the quantity is not a whole number of lots, or the
            contract has no lot size. Refused rather than rounded: rounding 15
            CRUDEOILM down to one lot silently cuts the order, and up doubles it.
    """
    qty = int(quantity)
    if qty == 0 or not is_lot_denominated(exchange):
        return qty
    size = lot_size(symbol, exchange)
    if size == 0:
        raise LotQuantityError(
            f"Cannot size {symbol} on {exchange}: the master contract has no lot size "
            f"for it. Download the master contract again, then retry."
        )
    lots, remainder = divmod(abs(qty), size)
    if remainder:
        raise LotQuantityError(
            f"{field} must be in multiples of lot size {size} for {symbol}, got {abs(qty)}"
        )
    return -lots if qty < 0 else lots


def from_fyers_qty(quantity, symbol, exchange):
    """Fyers' quantity -> OpenAlgo units. Inbound only.

    Lots times the lot size on MCX and CDS; unchanged on every other exchange.
    A value that is not a number, or a contract with no lot size, is returned as
    Fyers sent it (and logged), so one odd row cannot break a book.
    """
    if not is_lot_denominated(exchange):
        return quantity
    size = lot_size(symbol, exchange)
    if size == 0:
        logger.warning(f"No lot size for {exchange}:{symbol}; its quantity is in Fyers' lots")
        return quantity
    try:
        return int(float(quantity)) * size
    except (TypeError, ValueError):
        return quantity
