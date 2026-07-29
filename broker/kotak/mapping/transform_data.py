# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Kotak Neo API Parameters

import math
from decimal import Decimal

from database.token_db import get_br_symbol, get_symbol_info
from utils.logging import get_logger
from utils.mpp_slab import get_instrument_type_from_symbol

logger = get_logger(__name__)

# Kotak's published Market Price Protection grid
# (broker-api-docs/kotak-api-docs/03-static-ip-whitelisting.md:134-144).
# EQ/FUT matches utils/mpp_slab.py exactly; the OPT grid does not — Kotak adds
# two extra bands below 5 and an ABSOLUTE 0.10 floor below 1, which a
# percentage-only table cannot express. Kept local so the shared slabs stay
# broker-neutral.
_KOTAK_EQ_FUT_MPP = [(100, 2.0), (500, 1.0), (float("inf"), 0.5)]
_KOTAK_OPT_MPP = [(5, 10.0), (10, 5.0), (100, 3.0), (500, 2.0), (float("inf"), 1.0)]

# Below this price Kotak protects options by an absolute rupee amount, not a
# percentage (a 10% band on a 0.50 option is smaller than one tick).
_KOTAK_OPT_ABSOLUTE_BELOW = 1.0
_KOTAK_OPT_ABSOLUTE_OFFSET = 0.10


def _mpp_offset(price, instrument_type):
    """Kotak's protection offset (in rupees) for a price and instrument type."""
    if instrument_type in ("CE", "PE"):
        if price < _KOTAK_OPT_ABSOLUTE_BELOW:
            return _KOTAK_OPT_ABSOLUTE_OFFSET
        slabs = _KOTAK_OPT_MPP
    else:
        slabs = _KOTAK_EQ_FUT_MPP

    for max_price, percentage in slabs:
        if price < max_price:
            return price * percentage / 100.0
    return 0.0


def _tick_decimals(tick):
    """Number of decimal places implied by a tick size (0.05 -> 2, 0.0025 -> 4)."""
    return max(0, -Decimal(str(tick)).as_tuple().exponent)


def _snap_to_tick(value, tick, direction):
    """Snap to a multiple of ``tick``, away from the trigger.

    Nearest-tick rounding could land the limit back on the trigger, so the
    direction is forced: "floor" for SELL, "ceil" for BUY.
    """
    ratio = round(value / tick, 6)  # tame float noise before the floor/ceil
    k = math.floor(ratio) if direction == "floor" else math.ceil(ratio)
    return round(k * tick, _tick_decimals(tick))


def _slm_protected_price(symbol, exchange, action, trigger_price):
    """
    Derive the protective limit price that turns an SL-M into a Kotak SL.

    Kotak rejects SL-M from API sessions outright: "Market order with Algo Id
    not allowed" (observed live 2026-07-28, order 260728000251866). Per SEBI,
    market orders are not permitted for retail algos, and Kotak's APIs append
    an exchange-compliant Algo ID to every order automatically
    (03-static-ip-whitelisting.md:130,154). Plain MKT survives because Kotak
    substitutes its own protection limit server-side; a stop-market has no LTP
    to protect against at placement time, so it is refused instead.

    The fix mirrors the Dhan SL-M path (issue #1647): send pt="SL" with a limit
    offset one MPP band beyond the trigger in the fill direction — BUY above,
    SELL below — so the stop still rests and stays marketable once triggered.

    The limit is snapped to the instrument's exchange tick away from the
    trigger and forced at least one tick past it, so it can never round back
    onto the trigger. Fails closed when the tick size is unresolvable rather
    than guessing 2 decimals, which Kotak would reject.
    """
    instrument_type = get_instrument_type_from_symbol(symbol)

    symbol_info = get_symbol_info(symbol, exchange)
    try:
        tick_size = float(getattr(symbol_info, "tick_size", None)) if symbol_info else 0.0
    except (TypeError, ValueError):
        tick_size = 0.0
    if not math.isfinite(tick_size) or tick_size <= 0:
        raise ValueError(
            f"Cannot resolve tick size from DB for {symbol}/{exchange}; required to "
            f"build a valid SL-M protective limit price"
        )

    offset = _mpp_offset(trigger_price, instrument_type)

    if action.upper() == "SELL":
        # Strictly BELOW the trigger, at least one tick away, tick-aligned.
        raw = min(trigger_price - offset, trigger_price - tick_size)
        limit = _snap_to_tick(raw, tick_size, "floor")
        if limit <= 0:
            raise ValueError(
                f"SL-M SELL trigger {trigger_price} for {symbol}/{exchange} is too low "
                f"to derive a positive protective limit at tick {tick_size}"
            )
    else:
        # Strictly ABOVE the trigger, at least one tick away, tick-aligned.
        raw = max(trigger_price + offset, trigger_price + tick_size)
        limit = _snap_to_tick(raw, tick_size, "ceil")

    return limit


def _apply_slm_conversion(transformed, data):
    """Rewrite an SL-M payload in place as a protective Kotak SL order."""
    if data.get("pricetype") != "SL-M":
        return

    trigger_price = float(data.get("trigger_price", 0) or 0)
    if trigger_price <= 0:
        raise ValueError("Trigger price is required and must be positive for SL-M orders")

    protected_price = _slm_protected_price(
        data["symbol"], data["exchange"], data["action"], trigger_price
    )
    transformed["pt"] = "SL"
    transformed["pr"] = _fmt_price(protected_price)
    logger.debug(
        f"Kotak SL-M -> SL: Symbol={data['symbol']}, Action={data['action']}, "
        f"Trigger={trigger_price}, ProtectedLimit={protected_price}"
    )


def _fmt_price(value):
    """Kotak rejects '0.0' on numeric fields — emit '0' for zero, otherwise stringified value."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value) if value is not None else "0"
    if f == 0:
        return "0"
    return str(value)


def transform_data(data, token):
    """
    Transforms the new API request structure to the current expected structure.
    ALL values must be strings for Kotak API.
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])

    order_type = map_order_type(data["pricetype"])
    action = data["action"].upper()

    transformed = {
        "am": "NO",
        "dq": str(data.get("disclosed_quantity", "0")),
        "es": reverse_map_exchange(data["exchange"]),
        "mp": "0",
        "pc": data.get("product", "MIS"),
        "pf": "N",
        "pr": _fmt_price(data.get("price", 0)),
        "pt": order_type,
        "qt": str(data["quantity"]),
        "rt": "DAY",
        "tp": _fmt_price(data.get("trigger_price", 0)),
        "ts": symbol,
        "tt": "B" if action == "BUY" else ("S" if action == "SELL" else "None"),
    }

    _apply_slm_conversion(transformed, data)

    logger.debug(f"Transformed order data: {transformed}")
    return transformed


def transform_modify_order_data(data, token):
    symbol = get_br_symbol(data["symbol"], data["exchange"])
    transformed = {
        "tk": str(token),
        "dq": str(data.get("disclosed_quantity", "0")),
        "es": reverse_map_exchange(data["exchange"]),
        "mp": "0",
        "dd": "NA",
        "vd": "DAY",
        "pc": data.get("product", "MIS"),
        "pr": _fmt_price(data.get("price", 0)),
        "pt": map_order_type(data["pricetype"]),
        "qt": str(data["quantity"]),
        "tp": _fmt_price(data.get("trigger_price", 0)),
        "ts": symbol,
        "no": str(data["orderid"]),
        "tt": "B" if data["action"] == "BUY" else ("S" if data["action"] == "SELL" else "None"),
    }

    # A modify must carry the same conversion as the placement, or an SL-M
    # modify would hand Kotak back the pt it already rejected.
    _apply_slm_conversion(transformed, data)

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
