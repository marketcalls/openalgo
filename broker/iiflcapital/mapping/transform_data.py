import math
from decimal import Decimal
from typing import Any

from database.token_db import get_symbol_info
from utils.logging import get_logger
from utils.mpp_slab import get_instrument_type_from_symbol, get_mpp_percentage

logger = get_logger(__name__)


def _tick_decimals(tick: float) -> int:
    """Number of decimal places implied by a tick size (0.05 -> 2, 0.0025 -> 4)."""
    return max(0, -Decimal(str(tick)).as_tuple().exponent)


def _snap_to_tick(value: float, tick: float, direction: str) -> float:
    """Snap ``value`` to a multiple of ``tick``.

    direction ``"floor"`` rounds down, ``"ceil"`` rounds up — used to keep the
    protective limit strictly on the required side of the trigger after
    snapping (nearest-tick rounding could otherwise land it back on the
    trigger).
    """
    ratio = round(value / tick, 6)  # tame float noise before the floor/ceil
    k = math.floor(ratio) if direction == "floor" else math.ceil(ratio)
    return round(k * tick, _tick_decimals(tick))


def _slm_protected_price(symbol: str, exchange: str, action: str, trigger_price: float) -> float:
    """
    Derive a protective stop-limit price for an SL-M order from its trigger price.

    IIFL Capital's live API does not honor a bare SLM (stop-loss market) order
    -- placed directly, it is blocked under the same SEBI market-protection
    regime that also blocks a bare stop-market order on Dhan (see
    broker/dhan/mapping/transform_data.py::_slm_protected_price, GitHub issue
    #1647, for the reference case this mirrors).

    To place a stop that actually rests, SL-M is mapped to IIFL's SL
    (stop-limit) orderType with a limit price offset by the standard SEBI MPP
    percentage beyond the trigger, in the fill direction (SELL below the
    trigger, BUY above it), so it stays marketable once triggered. Uses the
    same shared utils/mpp_slab.py percentage table as Dhan (and samco) --
    these are exchange-mandated slabs, not broker-specific, so the percentage
    calculation itself is not IIFL-specific even though the order-field
    plumbing is.

    The limit is snapped to the instrument's exchange tick in the
    beyond-trigger direction (SELL floors, BUY ceils) and forced at least one
    tick past the trigger, so it can never round back onto/through the
    trigger or collapse to zero on low-priced options. Fails closed if the
    tick size can't be resolved -- a 2-decimal guess risks a tick-size
    rejection.
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

    pct = (get_mpp_percentage(trigger_price, instrument_type) or 0) / 100.0

    if action.upper() == "SELL":
        # Strictly BELOW trigger, >= one tick away, tick-aligned (floor), and
        # strictly positive.
        raw = min(trigger_price * (1 - pct), trigger_price - tick_size)
        limit = _snap_to_tick(raw, tick_size, "floor")
        if limit <= 0:
            raise ValueError(
                f"SL-M SELL trigger {trigger_price} for {symbol}/{exchange} is too low "
                f"to derive a positive protective limit at tick {tick_size}"
            )
    else:
        # Strictly ABOVE trigger, >= one tick away, tick-aligned (ceil).
        raw = max(trigger_price * (1 + pct), trigger_price + tick_size)
        limit = _snap_to_tick(raw, tick_size, "ceil")

    return limit


def map_exchange(exchange: str) -> str:
    exchange_mapping = {
        "NSE": "NSEEQ",
        "BSE": "BSEEQ",
        "NFO": "NSEFO",
        "BFO": "BSEFO",
        "CDS": "NSECURR",
        "BCD": "BSECURR",
        "MCX": "MCXCOMM",
        "NCDEX": "NCDEXCOMM",
    }
    return exchange_mapping.get((exchange or "").upper(), (exchange or "").upper())


def map_order_type(pricetype: str) -> str:
    order_type_mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "SL",
        "SL-M": "SLM",
    }
    return order_type_mapping.get((pricetype or "").upper(), "MARKET")


def reverse_map_order_type(order_type: str) -> str:
    order_type_mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "SL",
        "SLM": "SL-M",
    }
    return order_type_mapping.get((order_type or "").upper(), "MARKET")


def map_product_type(product: str) -> str:
    product_type_mapping = {
        "MIS": "INTRADAY",
        "CNC": "DELIVERY",
        "NRML": "NORMAL",
    }
    return product_type_mapping.get((product or "").upper(), "INTRADAY")


def reverse_map_product_type(product: str) -> str:
    product_mapping = {
        "INTRADAY": "MIS",
        "DELIVERY": "CNC",
        "NORMAL": "NRML",
        "BNPL": "CNC",
    }
    return product_mapping.get((product or "").upper(), "MIS")


def map_validity(validity: str) -> str:
    validity_mapping = {
        "DAY": "DAY",
        "IOC": "IOC",
    }
    return validity_mapping.get((validity or "").upper(), "DAY")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int_or_zero(value: Any) -> int:
    """Coerce arbitrary input to an int, returning 0 on any failure.
    Catches NaN/inf (which `int()` raises on) along with the usual
    type/value errors so a malformed numeric field never aborts order
    transformation. Caller is expected to apply its own `> 0` guard."""
    try:
        return int(_to_float(value, 0.0) or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def transform_data(data: dict, token: str) -> dict:
    """Transform OpenAlgo order request to IIFL Capital format."""
    transformed = {
        "instrumentId": str(token),
        "exchange": map_exchange(data.get("exchange", "")),
        "transactionType": (data.get("action") or "").upper(),
        "quantity": str(data.get("quantity", "0")),
        "orderComplexity": data.get("order_complexity", "REGULAR"),
        "product": map_product_type(data.get("product", "MIS")),
        "orderType": map_order_type(data.get("pricetype", "MARKET")),
        "validity": map_validity(data.get("validity", "DAY")),
        "apiOrderSource": "openalgo",
    }

    if transformed["orderType"] in ("LIMIT", "SL"):
        transformed["price"] = _to_float(data.get("price", 0.0))

    if transformed["orderType"] in ("SL", "SLM"):
        transformed["slTriggerPrice"] = _to_float(data.get("trigger_price", 0.0))

        # IIFL blocks a bare SLM (stop-loss market) order placed directly --
        # same SEBI market-protection wall Dhan hit (see _slm_protected_price
        # above). Convert to SL (stop-limit) with a protective limit price so
        # the stop actually rests and fills instead of being rejected.
        if transformed["orderType"] == "SLM":
            trigger_price = transformed["slTriggerPrice"]
            protected_price = _slm_protected_price(
                data.get("symbol", ""),
                data.get("exchange", ""),
                data.get("action", ""),
                trigger_price,
            )
            transformed["orderType"] = "SL"
            transformed["price"] = protected_price
            logger.info(
                f"IIFL SL-M -> SL: Symbol={data.get('symbol')}, Action={data.get('action')}, "
                f"Trigger={trigger_price}, ProtectedLimit={protected_price}"
            )

    # Coerce to int via float so zero-equivalent strings ("0", "0.0", " ")
    # don't slip through and surface as a meaningless `disclosedQuantity: 0`
    # field to the broker. NaN / inf / bad input fall back to 0 cleanly
    # instead of raising and aborting the whole order.
    disclosed_qty = _to_int_or_zero(data.get("disclosed_quantity"))
    if disclosed_qty > 0:
        transformed["disclosedQuantity"] = str(disclosed_qty)

    if data.get("strategy"):
        transformed["orderTag"] = str(data["strategy"])[:50]

    return transformed


def transform_modify_order_data(data: dict) -> dict:
    """Transform OpenAlgo modify request to IIFL Capital format."""
    transformed = {}

    if data.get("quantity") is not None:
        transformed["quantity"] = str(data.get("quantity"))

    pricetype = data.get("pricetype")
    if pricetype:
        order_type = map_order_type(pricetype)
        transformed["orderType"] = order_type

        if order_type in ("LIMIT", "SL"):
            transformed["price"] = _to_float(data.get("price", 0.0))

        if order_type in ("SL", "SLM"):
            transformed["slTriggerPrice"] = _to_float(data.get("trigger_price", 0.0))

            # Same SL-M -> protective SL conversion as placement (see
            # _slm_protected_price), so a modified SL-M also rests instead of
            # being blocked.
            if order_type == "SLM":
                trigger_price = transformed["slTriggerPrice"]
                protected_price = _slm_protected_price(
                    data.get("symbol", ""),
                    data.get("exchange", ""),
                    data.get("action", ""),
                    trigger_price,
                )
                transformed["orderType"] = "SL"
                transformed["price"] = protected_price
                logger.info(
                    f"IIFL SL-M modify -> SL: Symbol={data.get('symbol')}, "
                    f"Action={data.get('action')}, Trigger={trigger_price}, "
                    f"ProtectedLimit={protected_price}"
                )

    if "validity" in data:
        transformed["validity"] = map_validity(data.get("validity", "DAY"))

    # Coerce to int via float so zero-equivalent strings ("0", "0.0", " ")
    # don't slip through and surface as a meaningless `disclosedQuantity: 0`
    # field to the broker. NaN / inf / bad input fall back to 0 cleanly
    # instead of raising and aborting the whole order.
    disclosed_qty = _to_int_or_zero(data.get("disclosed_quantity"))
    if disclosed_qty > 0:
        transformed["disclosedQuantity"] = str(disclosed_qty)

    return transformed
