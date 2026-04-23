# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Kotak Neo API Parameters

import math

from broker.kotak.api.data import BrokerData
from database.token_db import get_br_symbol
from utils.logging import get_logger
from utils.mpp_slab import get_instrument_type_from_symbol, get_mpp_percentage

logger = get_logger(__name__)

# mp=0 means "no MPP" — correct for limit-priced orders (LIMIT/SL) where price is specified.
NO_MPP = "0"
# Minimum integer slab value; used only as a safe fallback for MARKET/SL-M when slab lookup fails.
FALLBACK_MP = "1"


def _mp_from_percentage(percentage):
    """Kotak mp is an integer percentage; slabs < 1% floor to 1."""
    return str(max(1, math.ceil(percentage)))


def _compute_mp(data, auth_token):
    """
    Compute Kotak's mp (market protection %) from the MPP slab.

    Only MARKET and SL-M orders need MPP — they execute at market price.
    LIMIT/SL orders carry their own price, so mp is not applicable and is sent as 0.

    Reference price for slab lookup:
      - MARKET: LTP (fetched via quotes)
      - SL-M:   trigger_price (the level at which the order converts to MARKET)
    """
    pricetype = data.get("pricetype")
    symbol = data["symbol"]
    exchange = data["exchange"]

    if pricetype not in ("MARKET", "SL-M"):
        return NO_MPP

    instrument_type = get_instrument_type_from_symbol(symbol)

    if pricetype == "MARKET":
        if not auth_token:
            return FALLBACK_MP
        try:
            quote_data = BrokerData(auth_token).get_quotes(symbol, exchange)
            ltp = float(quote_data.get("ltp", 0)) if quote_data else 0.0
            if ltp <= 0:
                logger.warning(f"MPP: LTP invalid for {symbol}/{exchange}, using mp={FALLBACK_MP}")
                return FALLBACK_MP
            percentage = get_mpp_percentage(ltp, instrument_type)
            mp_value = _mp_from_percentage(percentage)
            logger.info(
                f"MPP (MARKET): Symbol={symbol}, LTP={ltp}, InstrumentType={instrument_type}, "
                f"SlabPct={percentage}%, mp={mp_value}"
            )
            return mp_value
        except Exception as e:
            logger.warning(f"MPP: Failed to compute mp for {symbol}/{exchange}: {e}. Using mp={FALLBACK_MP}")
            return FALLBACK_MP

    # SL-M
    try:
        trigger_price = float(data.get("trigger_price", 0))
    except (TypeError, ValueError):
        trigger_price = 0.0
    if trigger_price <= 0:
        logger.warning(
            f"MPP: trigger_price invalid for SL-M {symbol}/{exchange}, using mp={FALLBACK_MP}"
        )
        return FALLBACK_MP
    try:
        percentage = get_mpp_percentage(trigger_price, instrument_type)
        mp_value = _mp_from_percentage(percentage)
    except Exception as e:
        logger.warning(
            f"MPP: Failed to compute mp for SL-M {symbol}/{exchange}: {e}. Using mp={FALLBACK_MP}"
        )
        return FALLBACK_MP
    logger.info(
        f"MPP (SL-M): Symbol={symbol}, TriggerPrice={trigger_price}, "
        f"InstrumentType={instrument_type}, SlabPct={percentage}%, mp={mp_value}"
    )
    return mp_value


def transform_data(data, token, auth_token=None):
    """
    Transforms the new API request structure to the current expected structure.
    ALL values must be strings for Kotak API.

    Kotak Neo applies Market Price Protection natively when mp > 0 is passed.
    For MARKET orders, mp is derived from the MPP slab based on LTP + instrument type.
    MARKET/SL-M orders are forwarded as-is (no local MKT->L / SL-M->SL conversion).

    Args:
        data: Order data dictionary
        token: Instrument token
        auth_token: Authentication token used to fetch LTP for mp computation
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])

    price = str(data.get("price", "0"))
    order_type = map_order_type(data["pricetype"])
    action = data["action"].upper()
    mp_value = _compute_mp(data, auth_token)

    # Basic mapping - ALL values must be strings for Kotak API
    transformed = {
        "am": "NO",
        "dq": str(data.get("disclosed_quantity", "0")),
        "bc": "1",
        "es": reverse_map_exchange(data["exchange"]),
        "mp": mp_value,
        "pc": data.get("product", "MIS"),
        "pf": "N",
        "pr": price,
        "pt": order_type,
        "qt": str(data["quantity"]),
        "rt": "DAY",
        "tp": str(data.get("trigger_price", "0")),
        "ts": symbol,
        "tt": "B" if action == "BUY" else ("S" if action == "SELL" else "None"),
    }

    # Log order data
    logger.info(f"Transformed order data: {transformed}")
    return transformed


def transform_modify_order_data(data, token, auth_token=None):
    symbol = get_br_symbol(data["symbol"], data["exchange"])
    # Basic mapping - ALL values must be strings for Kotak API
    transformed = {
        "tk": str(token),
        "dq": str(data.get("disclosed_quantity", "0")),
        "es": reverse_map_exchange(data["exchange"]),
        "mp": _compute_mp(data, auth_token),
        "dd": "NA",
        "vd": "DAY",
        "pc": data.get("product", "MIS"),
        "pr": str(data.get("price", "0")),
        "pt": map_order_type(data["pricetype"]),
        "qt": str(data["quantity"]),
        "tp": str(data.get("trigger_price", "0")),
        "ts": symbol,
        "no": str(data["orderid"]),
        "tt": "B" if data["action"] == "BUY" else ("S" if data["action"] == "SELL" else "None"),
    }
    return transformed


def map_order_type(pricetype):
    """
    Maps the new pricetype to the existing order type.
    """
    order_type_mapping = {"MARKET": "MKT", "LIMIT": "L", "SL": "SL", "SL-M": "SL-M"}
    return order_type_mapping.get(pricetype, "MARKET")  # Default to MARKET if not found


def map_product_type(product):
    """
    Maps the new product type to the existing product type.
    """
    product_type_mapping = {
        "CNC": "CNC",
        "NRML": "NRML",
        "MIS": "MIS",
    }
    return product_type_mapping.get(product)  # Default to DELIVERY if not found


def map_variety(pricetype):
    """
    Maps the pricetype to the existing order variety.
    """
    variety_mapping = {"MARKET": "NORMAL", "LIMIT": "NORMAL", "SL": "STOPLOSS", "SL-M": "STOPLOSS"}
    return variety_mapping.get(pricetype, "NORMAL")  # Default to DELIVERY if not found


def map_exchange(brexchange):
    """
    Maps the Broker Exchange to the OpenAlgo Exchange.
    """

    exchange_mapping = {
        "nse_cm": "NSE",
        "bse_cm": "BSE",
        "cde_fo": "CDS",
        "nse_fo": "NFO",
        "bse_fo": "BFO",
        "bcs_fo": "BCD",
        "mcx_fo": "MCX",
    }
    return exchange_mapping.get(brexchange)


def reverse_map_exchange(exchange):
    """
    Maps the Broker Exchange to the OpenAlgo Exchange.
    """

    exchange_mapping = {
        "NSE": "nse_cm",
        "BSE": "bse_cm",
        "CDS": "cde_fo",
        "NFO": "nse_fo",
        "BFO": "bse_fo",
        "BCD": "bcs_fo",
        "MCX": "mcx_fo",
    }
    return exchange_mapping.get(exchange)


def reverse_map_product_type(product):
    """
    Maps the new product type to the existing product type.
    """
    reverse_product_type_mapping = {
        "CNC": "CNC",
        "NRML": "NRML",
        "MIS": "MIS",
    }
    return reverse_product_type_mapping.get(product)
