# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping HDFC Securities InvestRight Trading Parameters (developer.hdfcsec.com)
#
# InvestRight addresses instruments by THREE fields at once, unlike most
# brokers' single token:
#   exchange           NSE / BSE / MCX  (the parent exchange, never NFO/BFO/CDS)
#   instrument_segment EQUITY / FUTIDX / OPTIDX / FUTSTK / OPTSTK / FUTCUR /
#                      OPTCUR / FUTCOM / OPTFUT
#   security_id        the alphanumeric broker code (SymToken.brsymbol)
# and derivative orders additionally need expiry_date / strike_price /
# option_type / underlying_symbol spelled out in the body.
#
# `underlying_symbol` is the CASH row's security_id, not the display name --
# NIFTY options carry "NIFTYEQEQNR", CIPLA futures carry "CIPLTDEQNR". It is
# recovered from the master contract by looking the underlying up on its cash
# or index exchange; that resolution was verified to reproduce the exact value
# the master's `underline_symbol` column carries for all 208 F&O underlyings.
#
# This module also owns the exchange-code translation used across the whole
# plugin (api/, database/, streaming/).

import threading
import time
from datetime import datetime

from database.token_db import get_symbol_info
from utils.logging import get_logger

logger = get_logger(__name__)

# --- exchange codes -------------------------------------------------------

# OpenAlgo index exchanges (quote-only).
OA_INDEX_EXCHANGES = {"NSE_INDEX", "BSE_INDEX"}

# OpenAlgo exchange -> the `exchange` value InvestRight's REST endpoints want.
# Derivatives are addressed by their PARENT exchange plus an
# `instrument_segment`, so NFO collapses to NSE and BFO to BSE.
_OA_TO_IR_REST = {
    "NSE": "NSE",
    "BSE": "BSE",
    "NFO": "NSE",
    "BFO": "BSE",
    "CDS": "NSE",
    "MCX": "MCX",
    "NSE_INDEX": "NSE",
    "BSE_INDEX": "BSE",
}

# (REST exchange, instrument_segment) -> OpenAlgo exchange. This is what makes
# an order-book or position row addressable again: "NSE" alone is ambiguous.
_IR_SEGMENT_TO_OA = {
    ("NSE", "EQUITY"): "NSE",
    ("NSE", "FUTIDX"): "NFO",
    ("NSE", "OPTIDX"): "NFO",
    ("NSE", "FUTSTK"): "NFO",
    ("NSE", "OPTSTK"): "NFO",
    ("NSE", "FUTCUR"): "CDS",
    ("NSE", "OPTCUR"): "CDS",
    ("NSE", "UNDCUR"): "CDS",
    ("BSE", "EQUITY"): "BSE",
    ("BSE", "FUTIDX"): "BFO",
    ("BSE", "OPTIDX"): "BFO",
    ("BSE", "FUTSTK"): "BFO",
    ("BSE", "OPTSTK"): "BFO",
    ("MCX", "FUTCOM"): "MCX",
    ("MCX", "OPTFUT"): "MCX",
    ("MCX", "FUTIDX"): "MCX",
    ("MCX", "OPTIDX"): "MCX",
    ("MCX", "COM"): "MCX",
}

# WebSocket scripId prefix per OpenAlgo exchange. Straight from the docs'
# "Prefix for each Exchange and segment" table: the feed keys instruments as
# "<PREFIX>_<TOKEN>" and uses dedicated *_INDEX prefixes for index feeds.
_OA_TO_WS_PREFIX = {
    "NSE": "NSE",
    "BSE": "BSE",
    "NFO": "NFO",
    "BFO": "BFO",
    "CDS": "NCD",
    "MCX": "MCX",
    "NSE_INDEX": "NSE_INDEX",
    "BSE_INDEX": "BSE_INDEX",
}

_WS_PREFIX_TO_OA = {v: k for k, v in _OA_TO_WS_PREFIX.items()}

# Index underlyings per derivative exchange, from the live master. Used only as
# the fallback when the underlying is missing from the SymToken table.
NFO_INDEX_UNDERLYINGS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}
BFO_INDEX_UNDERLYINGS = {"SENSEX", "SENSEX50", "BANKEX", "FOCIT"}
MCX_INDEX_UNDERLYINGS = {"MCXBULLDEX", "MCXMETLDEX"}


def to_rest_exchange(oa_exchange):
    """OpenAlgo exchange -> InvestRight REST `exchange` value."""
    return _OA_TO_IR_REST.get(oa_exchange, oa_exchange)


def to_ltp_exchange(oa_exchange):
    """OpenAlgo exchange -> the exchange code /fetch-ltp expects.

    The feed and the LTP snapshot address indices by their own codes; the
    ordinary parent-exchange code would simply omit the instrument from the
    response, which would surface as an LTP of zero.
    """
    if is_index_exchange(oa_exchange):
        return oa_exchange
    return to_rest_exchange(oa_exchange)


def to_oa_exchange(ir_exchange, instrument_segment=None):
    """InvestRight (exchange, instrument_segment) -> OpenAlgo exchange.

    Without a segment the parent exchange is the best available answer, which
    is correct for cash rows and wrong only for derivatives -- so always pass
    the segment when the payload carries one.
    """
    exchange = str(ir_exchange or "").upper()
    segment = str(instrument_segment or "").upper()
    if segment:
        mapped = _IR_SEGMENT_TO_OA.get((exchange, segment))
        if mapped:
            return mapped
    return exchange


def to_ws_prefix(oa_exchange):
    """OpenAlgo exchange -> WebSocket scripId prefix."""
    return _OA_TO_WS_PREFIX.get(oa_exchange, oa_exchange)


def ws_scrip_id(oa_exchange, token):
    """Build the WebSocket scripId, e.g. ('NSE_INDEX', 26000) -> 'NSE_INDEX_26000'."""
    return f"{to_ws_prefix(oa_exchange)}_{token}"


def from_ws_scrip_id(scrip_id):
    """Split a scripId back into (oa_exchange, token). Returns (None, None)
    when the prefix is unknown."""
    text = str(scrip_id)
    # Longest prefix first so "NSE_INDEX" wins over "NSE".
    for prefix in sorted(_WS_PREFIX_TO_OA, key=len, reverse=True):
        if text.startswith(prefix + "_"):
            return _WS_PREFIX_TO_OA[prefix], text[len(prefix) + 1 :]
    return None, None


def is_index_exchange(oa_exchange):
    return oa_exchange in OA_INDEX_EXCHANGES


# --- instrument segment ---------------------------------------------------

# Where a derivative's underlying is listed, most specific first. The index
# exchange is checked before the cash exchange so NIFTY resolves to the index
# row rather than to an equally named ETF.
_UNDERLYING_EXCHANGES = {
    "NFO": ("NSE_INDEX", "NSE"),
    "BFO": ("BSE_INDEX", "BSE"),
    "CDS": ("CDS",),
    "MCX": ("MCX",),
}


def _underlying_row(name, oa_exchange):
    """SymToken row for a derivative's underlying, or None."""
    for underlying_exchange in _UNDERLYING_EXCHANGES.get(oa_exchange, ()):
        if underlying_exchange == oa_exchange:
            continue
        try:
            info = get_symbol_info(name, underlying_exchange)
        except Exception as e:
            logger.debug(f"Underlying lookup failed for {underlying_exchange}:{name}: {e}")
            continue
        if info is not None:
            return info
    return None


def _is_index_underlying(name, oa_exchange, underlying):
    """True when the derivative is written on an index rather than a scrip."""
    if underlying is not None:
        return is_index_exchange(getattr(underlying, "exchange", ""))
    fallback = {
        "NFO": NFO_INDEX_UNDERLYINGS,
        "BFO": BFO_INDEX_UNDERLYINGS,
        "MCX": MCX_INDEX_UNDERLYINGS,
    }.get(oa_exchange, set())
    return name in fallback


def instrument_segment(oa_exchange, instrumenttype, name, underlying=None):
    """The `instrument_segment` InvestRight wants for this instrument.

    Args:
        oa_exchange: OpenAlgo exchange (NSE, NFO, BFO, CDS, MCX, ...).
        instrumenttype: SymToken instrumenttype (EQ / FUT / CE / PE).
        name: the underlying's OpenAlgo symbol (SymToken.name).
        underlying: the underlying's SymToken row when already resolved.
    """
    is_option = instrumenttype in ("CE", "PE")

    if oa_exchange in ("NSE", "BSE") or is_index_exchange(oa_exchange):
        return "EQUITY"
    if oa_exchange == "CDS":
        return "OPTCUR" if is_option else "FUTCUR"
    if oa_exchange == "MCX":
        if _is_index_underlying(name, oa_exchange, underlying):
            return "OPTIDX" if is_option else "FUTIDX"
        # MCX commodity options are written on the FUTURE, hence OPTFUT.
        return "OPTFUT" if is_option else "FUTCOM"
    # NFO / BFO
    if _is_index_underlying(name, oa_exchange, underlying):
        return "OPTIDX" if is_option else "FUTIDX"
    return "OPTSTK" if is_option else "FUTSTK"


def underlying_security_id(name, oa_exchange, underlying=None):
    """The `underlying_symbol` a derivative order must carry.

    That field is the underlying's own `security_id`, e.g. "NIFTYEQEQNR" for
    NIFTY and "CIPLTDEQNR" for CIPLA. MCX and currency underlyings have no
    separate broker code and carry the plain name.
    """
    if underlying is None:
        underlying = _underlying_row(name, oa_exchange)
    if underlying is not None:
        return getattr(underlying, "brsymbol", None) or name
    return name


# --- order parameters -----------------------------------------------------

# OpenAlgo pricetype -> InvestRight `order_type`. The profile endpoint reports
# the account's order_types as exactly MARKET / LIMIT / SL / SL-M, which is the
# authoritative spelling (the place-order parameter table's "SL-L" is a typo).
_ORDER_TYPE_MAP = {
    "MARKET": "MARKET",
    "LIMIT": "LIMIT",
    "SL": "SL",
    "SL-M": "SL-M",
}

_REVERSE_ORDER_TYPE_MAP = {
    "MARKET": "MARKET",
    "LIMIT": "LIMIT",
    "SL": "SL",
    "SL-L": "SL",
    "SLM": "SL-M",
    "SL-M": "SL-M",
}

# OpenAlgo product -> InvestRight product, per exchange class. Delivery only
# exists on the cash market; a carry-forward derivative position is OVERNIGHT.
_CASH_PRODUCT_MAP = {"CNC": "DELIVERY", "NRML": "DELIVERY", "MIS": "INTRADAY"}
_DERIV_PRODUCT_MAP = {"CNC": "OVERNIGHT", "NRML": "OVERNIGHT", "MIS": "INTRADAY"}

_REVERSE_PRODUCT_MAP = {
    "DELIVERY": "CNC",
    "MTF": "CNC",
    "COLL-SELL": "CNC",
    "ENCASH": "CNC",
    "OVERNIGHT": "NRML",
    "INTRADAY": "MIS",
    "COVER": "MIS",
}

_CASH_EXCHANGES = {"NSE", "BSE", "NSE_INDEX", "BSE_INDEX"}


def map_order_type(pricetype):
    """OpenAlgo pricetype -> InvestRight order_type. Defaults to MARKET."""
    return _ORDER_TYPE_MAP.get(str(pricetype).upper(), "MARKET")


def reverse_map_order_type(order_type):
    return _REVERSE_ORDER_TYPE_MAP.get(str(order_type).upper(), order_type)


def map_product_type(product, exchange="NSE"):
    """OpenAlgo product -> InvestRight product. Defaults to INTRADAY."""
    table = _CASH_PRODUCT_MAP if exchange in _CASH_EXCHANGES else _DERIV_PRODUCT_MAP
    return table.get(str(product).upper(), "INTRADAY")


def reverse_map_product_type(exchange, product):
    """InvestRight product -> OpenAlgo product.

    `exchange` is accepted for signature parity with the other brokers;
    InvestRight's product codes are exchange-independent on the way back.
    """
    return _REVERSE_PRODUCT_MAP.get(str(product).upper())


def map_transaction_type(action):
    return "BUY" if str(action).upper() == "BUY" else "SELL"


def reverse_map_transaction_type(transaction_type):
    """InvestRight echoes the side title-cased ("Buy"); OpenAlgo wants BUY."""
    return str(transaction_type or "").upper()


# InvestRight returns option_type as "Call" / "Put" even though orders send
# CE / PE.
_OPTION_TYPE_TO_OA = {"CALL": "CE", "PUT": "PE", "CE": "CE", "PE": "PE"}


def reverse_map_option_type(option_type):
    return _OPTION_TYPE_TO_OA.get(str(option_type or "").upper(), "")


_reference_lock = threading.Lock()
_last_reference = 0


def _external_reference_number():
    """A caller-supplied tracking id: numeric, max 20 characters.

    A strictly increasing millisecond counter. The wall clock alone is not
    enough -- a basket, or an algo firing several orders back to back, lands
    them inside the same millisecond and would reuse one reference number for
    all of them. Rather than pad with a sequence that itself wraps, the value
    borrows from the future when a millisecond is already spent, so it can
    never repeat within the process no matter how large the burst. 13 digits,
    well inside the field's length limit.
    """
    global _last_reference
    with _reference_lock:
        value = max(int(time.time() * 1000), _last_reference + 1)
        _last_reference = value
    return str(value)


def to_order_expiry(expiry):
    """SymToken expiry "25-AUG-26" -> the "20260825" the order API expects.

    The parameter table documents YYYY-MM-DD but every worked example in the
    docs sends YYYYMMDD, which is what the order gateway actually accepts.
    """
    if not expiry:
        return ""
    try:
        return datetime.strptime(str(expiry).upper(), "%d-%b-%y").strftime("%Y%m%d")
    except ValueError:
        logger.warning(f"Unrecognised expiry format from the master contract: {expiry!r}")
        return ""


def _instrument(symbol, exchange):
    info = get_symbol_info(symbol, exchange)
    if info is None:
        raise ValueError(f"No HDFC Securities instrument found for {exchange}:{symbol}")
    return info


def _derivative_fields(info, exchange):
    """expiry / strike / option_type / underlying_symbol for a derivative leg."""
    instrumenttype = str(getattr(info, "instrumenttype", "") or "").upper()
    if instrumenttype not in ("FUT", "CE", "PE"):
        return {}

    name = getattr(info, "name", "") or ""
    underlying = _underlying_row(name, exchange)

    fields = {
        "expiry_date": to_order_expiry(getattr(info, "expiry", "")),
        "underlying_symbol": underlying_security_id(name, exchange, underlying),
    }
    if instrumenttype in ("CE", "PE"):
        fields["option_type"] = instrumenttype
        fields["strike_price"] = float(getattr(info, "strike", 0) or 0)
    return fields


def transform_data(data):
    """OpenAlgo order dict -> InvestRight place-order payload.

    OpenAlgo order fields: symbol, exchange, action, pricetype, quantity,
    product, price, trigger_price, disclosed_quantity, strategy.
    """
    exchange = data["exchange"]
    info = _instrument(data["symbol"], exchange)
    instrumenttype = str(getattr(info, "instrumenttype", "") or "").upper()
    name = getattr(info, "name", "") or ""
    underlying = _underlying_row(name, exchange) if instrumenttype != "EQ" else None

    payload = {
        "exchange": to_rest_exchange(exchange),
        "security_id": info.brsymbol,
        "instrument_segment": instrument_segment(exchange, instrumenttype, name, underlying),
        "transaction_type": map_transaction_type(data["action"]),
        "product": map_product_type(data.get("product", "MIS"), exchange),
        "order_type": map_order_type(data.get("pricetype", "MARKET")),
        "quantity": int(float(data.get("quantity", 0) or 0)),
        "price": float(data.get("price", 0) or 0),
        "trigger_price": float(data.get("trigger_price", 0) or 0),
        "disclosed_quantity": int(float(data.get("disclosed_quantity", 0) or 0)),
        "validity": "DAY",
        "amo": False,
        "external_reference_number": _external_reference_number(),
    }
    payload.update(_derivative_fields(info, exchange))
    return payload


def transform_modify_order_data(data):
    """OpenAlgo modify-order dict -> InvestRight modify payload.

    Modification is PUT /oapi/v1/orders/regular/<order_id> and carries only the
    mutable fields; the instrument itself is fixed by the original order.
    """
    return {
        "quantity": int(float(data.get("quantity", 0) or 0)),
        "order_type": map_order_type(data.get("pricetype", "MARKET")),
        "validity": "DAY",
        "disclosed_quantity": int(float(data.get("disclosed_quantity", 0) or 0)),
        "product": map_product_type(data.get("product", "MIS"), data.get("exchange", "NSE")),
        "price": float(data.get("price", 0) or 0),
        "trigger_price": float(data.get("trigger_price", 0) or 0),
        "amo": False,
    }
