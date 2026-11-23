"""OpenAlgo margin positions to Pocketful's margin calculator, and back.

POST /api/space/v1/orderapis/marginCalculations (Pocketful docs, "Margin
Calculator"; SDK 0.1.2 has no route for it) takes every leg in one ``data``
array and answers a portfolio-netted ``combinedMargin`` block, so a basket is
always sent whole and its hedges net at Pocketful, never summed here.

One leg, field by field, as the docs' request table defines it:

    exchange    Pocketful exchange code (SymToken.brexchange)
    mode        "NEW"
    price       limit price as a string; "0" for a market order, as the docs say
    product     "MIS", "CNC" or "NRML". The docs describe the field as
                '"2" for NRML, or "MIS", "CNC"', but Pocketful's own position
                pages report prod_type 2 on an MIS position and 0 on an NRML
                one, so the number is ambiguous. The name is sent instead: the
                docs list names as accepted, and a name cannot be read as the
                other product.
    quantity    units, as a string (the docs' 309 is one ADANIENT lot)
    segment     "Capital" for NSE and BSE, "FutOpt" for NFO and BFO
    series      "EQ", "FUTIDX", "FUTSTK", "OPTIDX" or "OPTSTK" (the docs' list),
                or the series Pocketful's own instrument file gives the row
                when the master contract kept it
    side        "BUY" or "SELL"
    symbol      Pocketful trading symbol (SymToken.brsymbol)
    token       instrument token
    underlying  instrument token of the underlying (the docs' "25" is
                ADANIENT's NSE token); a cash leg is its own underlying

MCX and currency legs are refused: the docs do not say which series or
underlying a commodity or currency contract takes, and a guess would price the
wrong contract.
"""

from database.token_db import get_symbol_info
from utils.logging import get_logger
from utils.mpp_slab import get_instrument_type_from_symbol

logger = get_logger(__name__)

CASH_EXCHANGES = ("NSE", "BSE")
DERIVATIVE_EXCHANGES = {
    # Where a derivative's underlying is listed: the index first, then the
    # cash market. Found on the index exchange means an index derivative.
    "NFO": ("NSE_INDEX", "NSE"),
    "BFO": ("BSE_INDEX", "BSE"),
}
PRODUCTS = ("MIS", "CNC", "NRML")

# Instrument types OpenAlgo itself writes into SymToken. Anything else in that
# column came from Pocketful's instrument file and is already the series.
_GENERIC_TYPES = {"", "EQ", "FUT", "CE", "PE", "OPT", "INDEX", "IDX"}

# combinedMargin members that add to the requirement, and the one that
# subtracts (docs, "Response Parameters"). The docs give no total, so the
# requirement is the sum of the add-ons less the premium benefit, the same
# reading broker/hdfcsky makes of the same calculator's answer.
MARGIN_COMPONENTS = (
    "span",
    "exposureMargin",
    "premiumMargin",
    "varMargin",
    "extremeLossMargin",
    "deliveryMargin",
    "additionalMargin",
    "spanSpreadMargin",
    "somtierMargin",
)
MARGIN_BENEFIT = "premiumBenefit"


class MarginRefused(Exception):
    """A position that cannot be priced; the message is for the trader."""


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _number_text(value):
    """A price or quantity as the docs write it: "2954", "2939.7"."""
    number = _float(value)
    return str(int(number)) if number.is_integer() else str(number)


def _series(position, info, is_index):
    instrument = str(info.instrumenttype or "").upper()
    if instrument not in _GENERIC_TYPES:
        return instrument
    kind = instrument if instrument in ("FUT", "CE", "PE") else ""
    kind = kind or get_instrument_type_from_symbol(position["symbol"], position["exchange"])
    if kind == "FUT":
        return "FUTIDX" if is_index else "FUTSTK"
    if kind in ("CE", "PE"):
        return "OPTIDX" if is_index else "OPTSTK"
    raise MarginRefused(
        f"{position['symbol']} on {position['exchange']} is not a future or an option "
        "in the master contract, so its margin cannot be worked out. Download the "
        "master contract again and retry."
    )


def _underlying(position, info):
    """(underlying token, is_index) for a derivative leg."""
    name = info.name or getattr(info, "underlying", None)
    for exchange in DERIVATIVE_EXCHANGES[position["exchange"]]:
        found = get_symbol_info(name, exchange) if name else None
        if found is not None and found.token:
            return str(found.token), exchange.endswith("_INDEX")
    raise MarginRefused(
        f"The underlying of {position['symbol']} is not in the master contract, so "
        "its margin cannot be worked out. Download the master contract again and retry."
    )


def build_margin_leg(position):
    """One OpenAlgo position as a Pocketful margin leg. Raises MarginRefused."""
    symbol = position["symbol"]
    exchange = position["exchange"]

    if exchange not in CASH_EXCHANGES and exchange not in DERIVATIVE_EXCHANGES:
        raise MarginRefused(
            f"Margin for {exchange} contracts is not available with Pocketful yet. "
            "Check the margin for this leg in Pocketful's app."
        )

    product = str(position.get("product", "")).upper()
    if product not in PRODUCTS:
        raise MarginRefused(f"{symbol}: the product must be MIS, CNC or NRML.")

    info = get_symbol_info(symbol, exchange)
    if info is None or not info.token:
        raise MarginRefused(
            f"{symbol} on {exchange} is not in the Pocketful master contract. Check "
            "the symbol, or download the master contract again and retry."
        )

    if exchange in CASH_EXCHANGES:
        segment, series, underlying = "Capital", "EQ", str(info.token)
    else:
        underlying, is_index = _underlying(position, info)
        segment, series = "FutOpt", _series(position, info, is_index)

    return {
        "exchange": info.brexchange or exchange,
        "mode": "NEW",
        "price": _number_text(position.get("price", 0)),
        "product": product,
        "quantity": _number_text(int(_float(position.get("quantity")))),
        "segment": segment,
        "series": series,
        "side": str(position.get("action", "")).upper(),
        "symbol": info.brsymbol,
        "token": str(info.token),
        "underlying": underlying,
    }


def _requirement(block):
    """(total, span, exposure) for one margin block."""
    if not isinstance(block, dict):
        return 0.0, 0.0, 0.0
    total = sum(_float(block.get(key)) for key in MARGIN_COMPONENTS)
    total -= _float(block.get(MARGIN_BENEFIT))
    return max(total, 0.0), _float(block.get("span")), _float(block.get("exposureMargin"))


def parse_margin_response(payload):
    """Pocketful's ``data`` block to OpenAlgo's margin payload, or None if unreadable.

    ``combinedMargin`` is the basket figure with offsets applied. If it comes
    back all zero while ``individualMarginValues`` has entries, the entries are
    summed instead: broker/hdfcsky saw the same calculator leave the combined
    block empty on a single leg. The docs do not list the members of an
    individual entry; they are read with the combined block's names.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("combinedMargin"), dict):
        return None

    total, span, exposure = _requirement(payload["combinedMargin"])
    individuals = payload.get("individualMarginValues") or []
    if total <= 0 and isinstance(individuals, list) and individuals:
        logger.debug("Pocketful combinedMargin empty; summing individual legs")
        total = span = exposure = 0.0
        for entry in individuals:
            leg_total, leg_span, leg_exposure = _requirement(entry)
            total += leg_total
            span += leg_span
            exposure += leg_exposure

    return {
        "status": "success",
        "data": {
            "total_margin_required": round(total, 2),
            "span_margin": round(span, 2),
            "exposure_margin": round(exposure, 2),
        },
    }
