# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Flattrade Broking Parameters https://piconnect.flattrade.in/docs/

import math
from decimal import Decimal

from broker.flattrade.api.data import BrokerData
from database.token_db import get_br_symbol, get_symbol_info
from utils.logging import get_logger
from utils.mpp_slab import (
    calculate_protected_price,
    get_instrument_type_from_symbol,
    get_mpp_percentage,
)

logger = get_logger(__name__)

SLM_NO_TRIGGER_MESSAGE = (
    "A stop-loss market (SL-M) order needs a trigger price. "
    "Set a trigger price above zero and place the order again."
)


class SLMOrderRefused(ValueError):
    """An SL-M order that cannot be priced; refused before anything is sent."""


def slm_trigger_price(data):
    """Return the SL-M trigger price, refusing an order that has none."""
    try:
        trigger = float(data.get("trigger_price") or 0)
    except (TypeError, ValueError):
        trigger = 0.0
    if not math.isfinite(trigger) or trigger <= 0:
        raise SLMOrderRefused(SLM_NO_TRIGGER_MESSAGE)
    return trigger


def _snap_to_tick(value, tick, direction):
    """Snap to a multiple of ``tick``: "floor" rounds down, "ceil" rounds up."""
    ratio = round(value / tick, 6)  # tame float noise before the floor/ceil
    steps = math.floor(ratio) if direction == "floor" else math.ceil(ratio)
    decimals = max(0, -Decimal(str(tick)).as_tuple().exponent)
    return round(steps * tick, decimals)


def slm_limit_from_trigger(trigger, action, symbol, tick_size):
    """Protective limit for an SL-M sent as SL-LMT, priced off the trigger.

    SELL goes below the trigger and BUY above it, by the MPP slab of the
    trigger price and at least one tick, snapped away from the trigger so
    rounding can never pull it back onto or across the trigger. Same rule as
    broker/dhan and broker/kotak.

    Without a tick size the limit cannot be snapped safely, so the trigger
    itself (already tick-valid) is the limit. A SELL trigger within one tick
    of zero has no valid price below it, so it also keeps the trigger.
    """
    try:
        tick = float(tick_size) if tick_size else 0.0
    except (TypeError, ValueError):
        tick = 0.0
    if not math.isfinite(tick) or tick <= 0:
        return trigger

    instrument_type = get_instrument_type_from_symbol(symbol)
    pct = (get_mpp_percentage(trigger, instrument_type) or 0) / 100.0

    if action == "SELL":
        limit = _snap_to_tick(min(trigger * (1 - pct), trigger - tick), tick, "floor")
        return limit if limit > 0 else trigger
    return _snap_to_tick(max(trigger * (1 + pct), trigger + tick), tick, "ceil")


def transform_data(data, token, auth_token=None):
    """
    Transforms the new API request structure to the current expected structure.
    MARKET orders are sent as LMT priced off the LTP using MPP (Market Price
    Protection); SL-M orders are sent as SL-LMT priced off the trigger price:
    - EQ/FUT: Price < 100: 2%, 100-500: 1%, > 500: 0.5%
    - OPT (CE/PE): Price < 10: 5%, 10-100: 3%, 100-500: 2%, > 500: 1%

    Args:
        data: Order data dictionary
        token: Instrument token
        auth_token: Authentication token for fetching quotes (passed from order_api)
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])
    # Handle special characters in symbol
    if symbol and "&" in symbol:
        symbol = symbol.replace("&", "%26")

    # Default values
    price = str(data.get("price", "0"))
    order_type = map_order_type(data["pricetype"])
    action = data["action"].upper()

    # Flattrade runs the same Noren OMS as Shoonya, which blocks both MKT and
    # SL-MKT price types for API orders, so both are sent as protective limit
    # orders.
    #
    # SL-M goes out as SL-LMT priced off the trigger, never the LTP: the limit
    # only matters once the trigger is hit, so pricing it off the LTP put a
    # SELL stop's limit above its trigger (or a BUY stop's below), and the
    # triggered order rested away from the market. Issue #2390.
    if data["pricetype"] == "SL-M":
        trigger = slm_trigger_price(data)
        tick_size = None
        if auth_token:
            try:
                # Flattrade's quote carries the exchange tick ("ti").
                tick_size = (
                    BrokerData(auth_token)
                    .get_quotes(data["symbol"], data["exchange"])
                    .get("tick_size")
                )
            except Exception:
                logger.exception(
                    f"SL-M: quote for the tick size failed for Symbol={data['symbol']}; "
                    f"using the master contract tick"
                )
        if not tick_size:
            try:
                info = get_symbol_info(data["symbol"], data["exchange"])
                tick_size = getattr(info, "tick_size", None)
            except Exception:
                logger.exception(
                    f"SL-M: master contract tick lookup failed for Symbol={data['symbol']}; "
                    f"using the trigger as the limit"
                )
        limit = slm_limit_from_trigger(trigger, action, data["symbol"], tick_size)
        price = str(limit)
        order_type = "SL-LMT"
        logger.info(
            f"MPP SL-M->SL-LMT: Symbol={data['symbol']}, Action={action}, "
            f"Trigger={trigger}, TickSize={tick_size}, Limit={limit}"
        )

    # Apply Market Price Protection for MARKET orders, priced off the LTP.
    if data["pricetype"] == "MARKET":
        original_type = data["pricetype"]
        logger.info(
            f"MPP: {original_type} order detected for Symbol={data['symbol']}, Exchange={data['exchange']}, Action={action}"
        )
        try:
            if auth_token:
                # Create BrokerData instance to fetch quotes
                broker_data = BrokerData(auth_token)

                # Fetch quotes for the symbol (includes tick_size from API)
                quote_data = broker_data.get_quotes(data["symbol"], data["exchange"])
                logger.info(
                    f"MPP Quote Response: Symbol={data['symbol']}, Exchange={data['exchange']}, "
                    f"LTP={quote_data.get('ltp')}, Bid={quote_data.get('bid')}, Ask={quote_data.get('ask')}, "
                    f"TickSize={quote_data.get('tick_size')}"
                )

                # Get instrument type from symbol
                instrument_type = get_instrument_type_from_symbol(data["symbol"])

                # Get tick_size from quote response
                tick_size = quote_data.get("tick_size")
                logger.info(
                    f"MPP Symbol Info: InstrumentType={instrument_type}, TickSize={tick_size}"
                )

                # Get LTP for price calculation
                ltp = float(quote_data.get("ltp", 0))

                if ltp > 0:
                    # Calculate protected price using centralized MPP slab with tick size rounding
                    protected_price = calculate_protected_price(
                        price=ltp,
                        action=action,
                        symbol=data["symbol"],
                        instrument_type=instrument_type,
                        tick_size=tick_size,
                    )
                    price = str(protected_price)
                    # Convert MARKET to LIMIT
                    order_type = "LMT"

                    logger.info(
                        f"MPP Conversion Complete: Symbol={data['symbol']}, "
                        f"OrderType={original_type}->{order_type}, FinalPrice={protected_price}"
                    )
                else:
                    logger.warning(
                        f"MPP Warning: LTP is 0 or invalid for Symbol={data['symbol']}, "
                        f"Exchange={data['exchange']}. Proceeding with regular {original_type} order"
                    )
            else:
                logger.warning(
                    f"MPP Warning: No auth token available for Symbol={data['symbol']}. "
                    f"Cannot fetch quotes for MPP adjustment"
                )
        except Exception as e:
            logger.error(
                f"MPP Error: Failed to apply MPP for Symbol={data['symbol']}, "
                f"Exchange={data['exchange']}, Error={str(e)}. Proceeding with regular {original_type} order."
            )

    # Basic mapping - ensure all numeric values are strings
    transformed = {
        "uid": data["apikey"],
        "actid": data["apikey"],
        "exch": data["exchange"],
        "tsym": symbol,
        "qty": str(data["quantity"]),
        "prc": price,
        "trgprc": str(data.get("trigger_price", "0")),
        "dscqty": str(data.get("disclosed_quantity", "0")),
        "prd": map_product_type(data["product"]),
        "trantype": "B" if action == "BUY" else "S",
        "prctyp": order_type,
        "mkt_protection": "0",
        "ret": "DAY",
        "ordersource": "API",
    }

    # Log order data without sensitive fields (uid, actid contain API keys)
    safe_log = {k: v for k, v in transformed.items() if k not in ("uid", "actid")}
    logger.info(f"Transformed order data: {safe_log}")
    return transformed


def transform_modify_order_data(data, token):
    # Handle special characters in symbol
    symbol = data["symbol"]
    if symbol and "&" in symbol:
        symbol = symbol.replace("&", "%26")

    result = {
        "uid": data["apikey"],
        "exch": data["exchange"],
        "norenordno": data["orderid"],
        "prctyp": map_order_type(data["pricetype"]),
        "prc": str(data["price"]),
        "qty": str(data["quantity"]),
        "tsym": symbol,
        "ret": "DAY",
        "dscqty": str(data.get("disclosed_quantity") or 0),
    }

    # Only include trigger price for SL/SL-M orders
    # Sending trgprc=0 for LIMIT orders causes "Trigger price invalid - 0.00" error
    if data["pricetype"] in ["SL", "SL-M"]:
        result["trgprc"] = str(data.get("trigger_price") or 0)

    return result


def map_order_type(pricetype):
    """
    Maps the new pricetype to the existing order type.
    """
    order_type_mapping = {"MARKET": "MKT", "LIMIT": "LMT", "SL": "SL-LMT", "SL-M": "SL-MKT"}
    return order_type_mapping.get(pricetype, "MARKET")  # Default to MARKET if not found


def map_product_type(product):
    """
    Maps the new product type to the existing product type.
    """
    product_type_mapping = {
        "CNC": "C",
        "NRML": "M",
        "MIS": "I",
    }
    return product_type_mapping.get(product, "I")  # Default to DELIVERY if not found


def reverse_map_product_type(product):
    """
    Maps the new product type to the existing product type.
    """
    reverse_product_type_mapping = {
        "C": "CNC",
        "M": "NRML",
        "I": "MIS",
    }
    return reverse_product_type_mapping.get(product)
