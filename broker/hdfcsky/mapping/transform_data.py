# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping HDFC Sky Trading Parameters (developer.hdfcsky.com)
#
# HDFC Sky's vocabulary is very close to OpenAlgo's -- the only real
# translation is the stop-loss-market order type:
#   product   : CNC / MIS / NRML     -> identical
#   side      : BUY / SELL           -> order_side, identical
#   pricetype : MARKET/LIMIT/SL/SL-M -> MARKET / LIMIT / SL / SLM
#
# Instruments are addressed by `instrument_token` (the Security Master's
# exchange_token), NOT by trading symbol.
#
# This module also owns the exchange-code translation and index-symbol
# standardization used across the whole plugin (api/, database/, streaming/).

import time

from broker.hdfcsky.api.baseurl import get_client_id
from database.token_db import get_token

# --- exchange codes -------------------------------------------------------
#
# Verified against the live Security Master
# (https://hdfcsky.com/api/v1/contract/Compact?info=download -> CompactScrip.csv,
# ~182k rows). The CSV's `exchange` column already uses OpenAlgo-compatible
# codes (NSE / BSE / NFO / BFO / CDS / MCX); the only split OpenAlgo needs is
# pulling indices out into NSE_INDEX / BSE_INDEX, which the CSV flags via the
# `segment` column (NSE -> "INDICES", BSE -> "IDX").

# OpenAlgo index exchanges (quote-only).
OA_INDEX_EXCHANGES = {"NSE_INDEX", "BSE_INDEX"}

# CSV `segment` value that marks an index row, keyed by the CSV `exchange`.
INDEX_SEGMENTS = {"NSE": "INDICES", "BSE": "IDX"}

# OpenAlgo exchange -> the code HDFC Sky's REST endpoints (orders, positions,
# chart data) expect. Indices resolve to their parent cash exchange.
#
# The LTP endpoint is the exception - it wants the dedicated index codes, so
# use to_ltp_exchange() there, not this map.
_OA_TO_HDFCSKY_REST = {
    "NSE": "NSE",
    "BSE": "BSE",
    "NFO": "NFO",
    "BFO": "BFO",
    "CDS": "CDS",
    "MCX": "MCX",
    "NSE_INDEX": "NSE",
    "BSE_INDEX": "BSE",
}

# HDFC Sky REST exchange code -> OpenAlgo exchange (normalizing responses).
# Note this is intentionally NOT the inverse of the map above: an order-book
# row on "NSE" is a cash instrument, never an index.
_HDFCSKY_REST_TO_OA = {
    "NSE": "NSE",
    "BSE": "BSE",
    "NFO": "NFO",
    "BFO": "BFO",
    "CDS": "CDS",
    "NCD": "CDS",
    "MCX": "MCX",
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


def to_rest_exchange(oa_exchange):
    """OpenAlgo exchange -> HDFC Sky REST exchange code."""
    return _OA_TO_HDFCSKY_REST.get(oa_exchange, oa_exchange)


def to_ltp_exchange(oa_exchange):
    """OpenAlgo exchange -> the exchange code the /fetch-ltp endpoint expects.

    Unlike every other REST endpoint, fetch-ltp addresses indices by their own
    codes, "NSE_INDEX" and "BSE_INDEX", which happen to match the OpenAlgo
    names. Sending the parent cash exchange instead is not an error: the
    instrument is simply omitted from the response, which surfaces as an LTP of
    zero. Non-index exchanges use the ordinary REST codes.
    """
    if is_index_exchange(oa_exchange):
        return oa_exchange
    return to_rest_exchange(oa_exchange)


def to_oa_exchange(hdfcsky_exchange):
    """HDFC Sky REST exchange code -> OpenAlgo exchange."""
    return _HDFCSKY_REST_TO_OA.get(str(hdfcsky_exchange).upper(), hdfcsky_exchange)


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


# --- index symbol mapping -------------------------------------------------
#
# HDFC Sky ships index rows with human display names on NSE ("Nifty 50",
# "Nifty Bank") and short codes on BSE ("SENSEX", "SNSX50", "BSE HC").
# OpenAlgo standardizes both to the symbols documented in
# docs/prompt/symbol-format.md -- the same set the Zerodha reference
# implementation produces, so option tools that start from an index LTP
# (option chain, IV smile, max pain, GEX, OI tracker) resolve identically
# across brokers.
#
# Lookup keys are uppercased with all whitespace removed. Anything not listed
# falls back to its cleaned (uppercased, space-stripped) name, which keeps new
# indices addressable the moment HDFC adds them.

_NSE_INDEX_MAP = {
    # Derivative underlyings -- these five MUST match the NFO `name` column
    # so the options tools can join index spot to its option chain.
    "NIFTY50": "NIFTY",
    "NIFTYBANK": "BANKNIFTY",
    "NIFTYFINSERVICE": "FINNIFTY",
    "NIFTYMIDSELECT": "MIDCPNIFTY",
    "NIFTYNEXT50": "NIFTYNXT50",
    "INDIAVIX": "INDIAVIX",
    # Broad market
    "NIFTY100": "NIFTY100",
    "NIFTY200": "NIFTY200",
    "NIFTY500": "NIFTY500",
    # Sectoral
    "NIFTYALPHA50": "NIFTYALPHA50",
    "NIFTYAUTO": "NIFTYAUTO",
    "NIFTYCHEMICALS": "NIFTYCHEMICALS",
    "NIFTYCOMMODITIES": "NIFTYCOMMODITIES",
    "NIFTYCONSUMPTION": "NIFTYCONSUMPTION",
    "NIFTYCPSE": "NIFTYCPSE",
    "NIFTYDIVOPPS50": "NIFTYDIVOPPS50",
    "NIFTYENERGY": "NIFTYENERGY",
    "NIFTYFMCG": "NIFTYFMCG",
    "NIFTYGROWSECT15": "NIFTYGROWSECT15",
    "NIFTYHEALTHCARE": "NIFTYHEALTHCARE",
    "NIFTYINFRA": "NIFTYINFRA",
    "NIFTYIT": "NIFTYIT",
    "NIFTYMEDIA": "NIFTYMEDIA",
    "NIFTYMETAL": "NIFTYMETAL",
    "NIFTYMNC": "NIFTYMNC",
    "NIFTYOILANDGAS": "NIFTYOILANDGAS",
    "NIFTYPHARMA": "NIFTYPHARMA",
    "NIFTYPSE": "NIFTYPSE",
    "NIFTYPSUBANK": "NIFTYPSUBANK",
    "NIFTYPVTBANK": "NIFTYPVTBANK",
    "NIFTYREALTY": "NIFTYREALTY",
    "NIFTYSERVSECTOR": "NIFTYSERVSECTOR",
    # Market cap
    "NIFTYMIDLIQ15": "NIFTYMIDLIQ15",
    "NIFTYMIDCAP50": "NIFTYMIDCAP50",
    "NIFTYMIDCAP100": "NIFTYMIDCAP100",
    "NIFTYMIDCAP150": "NIFTYMIDCAP150",
    "NIFTYMIDSML400": "NIFTYMIDSML400",
    "NIFTYSMLCAP50": "NIFTYSMLCAP50",
    "NIFTYSMLCAP100": "NIFTYSMLCAP100",
    "NIFTYSMLCAP250": "NIFTYSMLCAP250",
    # Strategy
    "NIFTY100EQLWGT": "NIFTY100EQLWGT",
    "NIFTY100LIQ15": "NIFTY100LIQ15",
    "NIFTY100LOWVOL30": "NIFTY100LOWVOL30",
    "NIFTY100QUALTY30": "NIFTY100QUALTY30",
    "NIFTY200QUALTY30": "NIFTY200QUALTY30",
    "NIFTY50DIVPOINT": "NIFTY50DIVPOINT",
    "NIFTY50EQLWGT": "NIFTY50EQLWGT",
    "NIFTY50PR1XINV": "NIFTY50PR1XINV",
    "NIFTY50PR2XLEV": "NIFTY50PR2XLEV",
    "NIFTY50TR1XINV": "NIFTY50TR1XINV",
    "NIFTY50TR2XLEV": "NIFTY50TR2XLEV",
    "NIFTY50VALUE20": "NIFTY50VALUE20",
    # Government securities
    "NIFTYGS10YR": "NIFTYGS10YR",
    "NIFTYGS10YRCLN": "NIFTYGS10YRCLN",
    "NIFTYGS1115YR": "NIFTYGS1115YR",
    "NIFTYGS15YRPLUS": "NIFTYGS15YRPLUS",
    "NIFTYGS48YR": "NIFTYGS48YR",
    "NIFTYGS813YR": "NIFTYGS813YR",
    "NIFTYGSCOMPSITE": "NIFTYGSCOMPSITE",
}

# BSE short codes (the CSV's `trading_symbol` for IDX rows) -> OpenAlgo symbol.
_BSE_INDEX_MAP = {
    "SENSEX": "SENSEX",
    "BANKEX": "BANKEX",
    "SNSX50": "SENSEX50",
    "SNXT50": "BSESENSEXNEXT50",
    "BSE100": "BSE100",
    "BSE200": "BSE200",
    "BSE500": "BSE500",
    "MID150": "BSE150MIDCAPINDEX",
    "LMI250": "BSE250LARGEMIDCAPINDEX",
    "MSL400": "BSE400MIDSMALLCAPINDEX",
    "AUTO": "BSEAUTO",
    "BSECG": "BSECAPITALGOODS",
    "BSECD": "BSECONSUMERDURABLES",
    "CPSE": "BSECPSE",
    "ENERGY": "BSEENERGY",
    "BSEFMC": "BSEFASTMOVINGCONSUMERGOODS",
    "FINSER": "BSEFINANCIALSERVICES",
    "BSEHC": "BSEHEALTHCARE",
    "INFRA": "BSEINDIAINFRASTRUCTUREINDEX",
    "INDSTR": "BSEINDUSTRIALS",
    "BSEIT": "BSEINFORMATIONTECHNOLOGY",
    "BSEIPO": "BSEIPO",
    "METAL": "BSEMETAL",
    "MIDSEL": "BSEMIDCAPSELECTINDEX",
    "OILGAS": "BSEOIL&GAS",
    "POWER": "BSEPOWER",
    "BSEPSU": "BSEPSU",
    "REALTY": "BSEREALTY",
    "SMLSEL": "BSESMALLCAPSELECTINDEX",
    "SMEIPO": "BSESMEIPO",
    "TECK": "BSETECK",
    "TELCOM": "BSETELECOM",
    "UTILS": "BSEUTILITIES",
    "ESG100": "ESG100",
    "BHRT22": "BHRT22",
    "FOCIT": "FOCIT",
}

_INDEX_MAPS = {"NSE_INDEX": _NSE_INDEX_MAP, "BSE_INDEX": _BSE_INDEX_MAP}


def _norm(name):
    return "".join(str(name).upper().split())


def classify_index_symbol(display_name, oa_exchange):
    """HDFC Sky index display name -> the OpenAlgo index symbol.

    Unmapped names fall back to their normalized (uppercase, space-free) form
    so newly listed indices are still addressable.
    """
    key = _norm(display_name)
    return _INDEX_MAPS.get(oa_exchange, {}).get(key, key)


# --- index derivative underlyings ----------------------------------------
#
# Needed by the chart-data API, whose `seriesType` distinguishes index from
# stock derivatives (FUTIDX vs FUTSTK on NFO, IF/IO vs SF/SO on BFO). Taken
# from the live master: these are exactly the `company_name` values carried by
# NFO OPTIDX/FUTIDX and BFO IF/IO rows.
NFO_INDEX_UNDERLYINGS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}
BFO_INDEX_UNDERLYINGS = {"SENSEX", "SENSEX50", "BANKEX", "FOCIT"}


# --- order parameters -----------------------------------------------------

# OpenAlgo pricetype -> HDFC Sky `order_type`.
_ORDER_TYPE_MAP = {
    "MARKET": "MARKET",
    "LIMIT": "LIMIT",
    "SL": "SL",
    "SL-M": "SLM",
}

# HDFC Sky `order_type` -> OpenAlgo pricetype (normalizing responses).
_REVERSE_ORDER_TYPE_MAP = {
    "MARKET": "MARKET",
    "LIMIT": "LIMIT",
    "SL": "SL",
    "SLM": "SL-M",
    "SL-M": "SL-M",
}

# Products are identical in both vocabularies; the maps exist so callers have
# one place to look and unknown values degrade predictably.
_PRODUCT_MAP = {"CNC": "CNC", "NRML": "NRML", "MIS": "MIS"}
_REVERSE_PRODUCT_MAP = {"CNC": "CNC", "NRML": "NRML", "MIS": "MIS", "MTF": "CNC"}

# Numeric product codes used by the margin calculator, from the GenericDTO
# proto's ProdType enum (NRML = 0, CNC = 1, MIS = 2).
PRODUCT_NUMERIC_CODES = {"NRML": "0", "CNC": "1", "MIS": "2"}


def map_order_type(pricetype):
    """OpenAlgo pricetype -> HDFC Sky order_type. Defaults to MARKET."""
    return _ORDER_TYPE_MAP.get(str(pricetype).upper(), "MARKET")


def reverse_map_order_type(order_type):
    return _REVERSE_ORDER_TYPE_MAP.get(str(order_type).upper(), order_type)


def map_product_type(product):
    """OpenAlgo product -> HDFC Sky product. Defaults to MIS."""
    return _PRODUCT_MAP.get(str(product).upper(), "MIS")


def reverse_map_product_type(exchange, product):
    """HDFC Sky product -> OpenAlgo product. `exchange` is accepted for
    signature parity with the other brokers (HDFC Sky's codes are
    exchange-independent)."""
    return _REVERSE_PRODUCT_MAP.get(str(product).upper())


def map_transaction_type(action):
    return "BUY" if str(action).upper() == "BUY" else "SELL"


def _user_order_id():
    """HDFC Sky wants a caller-generated numeric `user_order_id`. Millisecond
    epoch truncated to 9 digits keeps it unique within a trading day and well
    inside the field's numeric range."""
    return int(time.time() * 1000) % 1_000_000_000


def _resolve_token(symbol, exchange):
    token = get_token(symbol, exchange)
    if token is None:
        raise ValueError(f"No HDFC Sky instrument token found for {exchange}:{symbol}")
    return str(token)


def transform_data(data, auth_token):
    """OpenAlgo order dict -> HDFC Sky place-order payload.

    OpenAlgo order fields: symbol, exchange, action, pricetype, quantity,
    product, price, trigger_price, disclosed_quantity, strategy.
    """
    exchange = data["exchange"]
    order_type = map_order_type(data.get("pricetype", "MARKET"))

    payload = {
        "exchange": to_rest_exchange(exchange),
        "instrument_token": _resolve_token(data["symbol"], exchange),
        "client_id": get_client_id(auth_token),
        "order_type": order_type,
        "order_side": map_transaction_type(data["action"]),
        "product": map_product_type(data.get("product", "MIS")),
        "quantity": int(data.get("quantity", 0)),
        "price": float(data.get("price", 0) or 0),
        "trigger_price": float(data.get("trigger_price", 0) or 0),
        "disclosed_quantity": int(data.get("disclosed_quantity", 0) or 0),
        "validity": "DAY",
        "device": "WEB",
        "execution_type": "REGULAR",
        "amo": False,
        "user_order_id": _user_order_id(),
    }

    strategy = str(data.get("strategy", "") or "").strip()
    if strategy:
        # Optional order tagging; HDFC Sky expects an array of strings.
        payload["tags"] = [strategy[:32]]

    return payload


def transform_modify_order_data(data, auth_token):
    """OpenAlgo modify-order dict -> HDFC Sky modify payload.

    HDFC Sky modifies via PUT /oapi/v1/orders with the SAME body shape as
    placement plus `oms_order_id`. The product cannot be changed, but the
    field is still required by the validator.
    """
    exchange = data["exchange"]
    order_type = map_order_type(data.get("pricetype", "MARKET"))

    return {
        "exchange": to_rest_exchange(exchange),
        "instrument_token": _resolve_token(data["symbol"], exchange),
        "client_id": get_client_id(auth_token),
        "oms_order_id": str(data["orderid"]),
        "order_type": order_type,
        "product": map_product_type(data.get("product", "MIS")),
        "quantity": int(data.get("quantity", 0)),
        "price": float(data.get("price", 0) or 0),
        "trigger_price": float(data.get("trigger_price", 0) or 0),
        "disclosed_quantity": int(data.get("disclosed_quantity", 0) or 0),
        "validity": "DAY",
        "execution_type": "REGULAR",
    }
