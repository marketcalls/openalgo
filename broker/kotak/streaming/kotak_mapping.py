"""
Mapping utilities for Kotak broker integration.
Provides exchange, product, and order type mappings between OpenAlgo and Kotak formats.
"""

# Exchange code mappings
OPENALGO_TO_KOTAK_EXCHANGE = {
    "NSE": "nse_cm",
    "nse": "nse_cm",
    "BSE": "bse_cm",
    "bse": "bse_cm",
    "NFO": "nse_fo",
    "nfo": "nse_fo",
    "BFO": "bse_fo",
    "bfo": "bse_fo",
    "CDS": "cde_fo",
    "cds": "cde_fo",
    "BCD": "bcs-fo",
    "bcd": "bcs-fo",
    "MCX": "mcx_fo",
    "mcx": "mcx_fo",
    "NSE_INDEX": "nse_cm",
    "BSE_INDEX": "bse_cm"
}

KOTAK_TO_OPENALGO_EXCHANGE = {v: k for k, v in OPENALGO_TO_KOTAK_EXCHANGE.items()}

# Product type mappings
OPENALGO_TO_KOTAK_PRODUCT = {
    "Normal": "NRML",
    "NRML": "NRML",
    "CNC": "CNC",
    "cnc": "CNC",
    "Cash and Carry": "CNC",
    "MIS": "MIS",
    "mis": "MIS",
    "INTRADAY": "INTRADAY",
    "intraday": "INTRADAY",
    "Cover Order": "CO",
    "co": "CO",
    "CO": "CO",
    "BO": "Bracket Order",
    "Bracket Order": "Bracket Order",
    "bo": "Bracket Order"
}

KOTAK_TO_OPENALGO_PRODUCT = {v: k for k, v in OPENALGO_TO_KOTAK_PRODUCT.items()}

# Order type mappings
OPENALGO_TO_KOTAK_ORDER_TYPE = {
    "Limit": "L",
    "L": "L",
    "l": "L",
    "MKT": "MKT",
    "mkt": "MKT",
    "Market": "MKT",
    "sl": "SL",
    "SL": "SL",
    "Stop loss limit": "SL",
    "Stop loss market": "SL-M",
    "SL-M": "SL-M",
    "sl-m": "SL-M",
    "Spread": "SP",
    "SP": "SP",
    "sp": "SP",
    "2L": "2L",
    "2l": "2L",
    "Two Leg": "2L",
    "3L": "3L",
    "3l": "3L",
    "Three leg": "3L"
}

KOTAK_TO_OPENALGO_ORDER_TYPE = {v: k for k, v in OPENALGO_TO_KOTAK_ORDER_TYPE.items()}

def get_kotak_exchange(openalgo_exchange: str) -> str:
    """
    Convert OpenAlgo exchange code to Kotak exchange code.
    """
    return OPENALGO_TO_KOTAK_EXCHANGE.get(openalgo_exchange, openalgo_exchange)

def get_openalgo_exchange(kotak_exchange: str) -> str:
    """
    Convert Kotak exchange code to OpenAlgo exchange code.
    """
    return KOTAK_TO_OPENALGO_EXCHANGE.get(kotak_exchange, kotak_exchange)

def get_kotak_product(openalgo_product: str) -> str:
    """
    Convert OpenAlgo product type to Kotak product type.
    """
    return OPENALGO_TO_KOTAK_PRODUCT.get(openalgo_product, openalgo_product)

def get_openalgo_product(kotak_product: str) -> str:
    """
    Convert Kotak product type to OpenAlgo product type.
    """
    return KOTAK_TO_OPENALGO_PRODUCT.get(kotak_product, kotak_product)

def get_kotak_order_type(openalgo_order_type: str) -> str:
    """
    Convert OpenAlgo order type to Kotak order type.
    """
    return OPENALGO_TO_KOTAK_ORDER_TYPE.get(openalgo_order_type, openalgo_order_type)

def get_openalgo_order_type(kotak_order_type: str) -> str:
    """
    Convert Kotak order type to OpenAlgo order type.
    """
    return KOTAK_TO_OPENALGO_ORDER_TYPE.get(kotak_order_type, kotak_order_type)
