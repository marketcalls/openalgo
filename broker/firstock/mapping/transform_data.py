# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Firstock V1 API Parameters https://api.firstock.in/V1/placeOrder

import os

from database.token_db import get_br_symbol, get_symbol_info
from utils.logging import get_logger
from utils.mpp_slab import calculate_protected_price, get_instrument_type_from_symbol

logger = get_logger(__name__)


def transform_data(data, token, auth_token=None):
    """
    Transforms the OpenAlgo API request to Firstock's V1 /placeOrder structure.

    For MARKET and SL-M orders, applies client-side Market Price Protection
    (MPP): fetch LTP, compute a protected price via the OpenAlgo MPP slab,
    convert the order type to LMT / SL-LMT. Also sets mkt_protection="0" so
    Firstock's server-side MPP (V1.7+) is a no-op on the already-protected
    price. Mirrors the pattern in broker/shoonya and broker/flattrade.

    Args:
        data: Order data dictionary (OpenAlgo format).
        token: Instrument token (accepted for signature parity).
        auth_token: Firstock jKey. Required for MPP — if absent, MARKET/SL-M
                    flows through unchanged and Firstock's server-side MPP
                    handles it.
    """
    # Derive userId: prefer the apikey supplied in the request, fall back to
    # the BROKER_API_KEY env var (same source place_order_api uses to
    # overwrite userId just before sending). This makes transform_data robust
    # to callers like the close_position endpoint that don't include apikey.
    raw_apikey = data.get("apikey") or os.getenv("BROKER_API_KEY", "")
    userid = raw_apikey.replace("_API", "") if raw_apikey else ""

    # Get broker symbol and handle special characters
    symbol = get_br_symbol(data["symbol"], data["exchange"])
    if symbol and "&" in symbol:
        symbol = symbol.replace("&", "%26")

    # Default values
    price = str(data.get("price", "0"))
    order_type = map_order_type(data["pricetype"])
    action = data["action"].upper()

    # Apply MPP for MARKET and SL-M orders (V1.7 supports SL-MKT->SL-LMT too).
    if data["pricetype"] in ("MARKET", "SL-M"):
        original_type = data["pricetype"]
        logger.info(
            f"MPP: {original_type} order detected for Symbol={data['symbol']}, "
            f"Exchange={data['exchange']}, Action={action}"
        )
        try:
            if auth_token:
                # Lazy import to avoid circular dependency
                from broker.firstock.api.data import BrokerData

                broker_data = BrokerData(auth_token)
                quote_data = broker_data.get_quotes(data["symbol"], data["exchange"])
                logger.info(
                    f"MPP Quote Response: Symbol={data['symbol']}, Exchange={data['exchange']}, "
                    f"LTP={quote_data.get('ltp')}, Bid={quote_data.get('bid')}, Ask={quote_data.get('ask')}, "
                    f"TickSize={quote_data.get('tick_size')}"
                )

                instrument_type = get_instrument_type_from_symbol(data["symbol"])

                # Firstock's /getQuote response omits tick size, so fetch it
                # from the local master contract DB (same pattern as kotak).
                tick_size = quote_data.get("tick_size")
                if not tick_size:
                    symbol_info = get_symbol_info(data["symbol"], data["exchange"])
                    if symbol_info and symbol_info.tick_size:
                        tick_size = symbol_info.tick_size
                logger.info(
                    f"MPP Symbol Info: InstrumentType={instrument_type}, TickSize={tick_size}"
                )

                ltp = float(quote_data.get("ltp", 0))

                if ltp > 0:
                    protected_price = calculate_protected_price(
                        price=ltp,
                        action=action,
                        symbol=data["symbol"],
                        instrument_type=instrument_type,
                        tick_size=tick_size,
                    )
                    price = str(protected_price)
                    order_type = "LMT" if original_type == "MARKET" else "SL-LMT"
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

    transaction_type = "B" if action == "BUY" else "S"

    transformed = {
        "userId": userid,
        "exchange": data["exchange"],
        "tradingSymbol": symbol,
        "quantity": str(data["quantity"]),
        "price": price,
        "triggerPrice": str(data.get("trigger_price", "0")),
        "product": map_product_type(data["product"]),
        "transactionType": transaction_type,
        "priceType": order_type,
        "retention": "DAY",
        "mkt_protection": "0",
        "remarks": data.get("strategy", "Place Order"),
    }

    # Log order data without sensitive userId field
    safe_log = {k: v for k, v in transformed.items() if k != "userId"}
    logger.info(f"Transformed order data: {safe_log}")
    return transformed


def transform_modify_order_data(data, token, auth_token=None):
    """
    Transform modify order data to Firstock's V1 /modifyOrder format.

    V1.7 extended server-side MPP to modifyOrder too; we apply the same
    client-side MARKET -> LMT / SL-M -> SL-LMT conversion here so the price
    is fully owned by OpenAlgo instead of depending on broker defaults.
    """
    # Handle special characters in symbol
    symbol = data["symbol"]
    if "&" in symbol:
        symbol = symbol.replace("&", "%26")

    price = str(data.get("price", "0"))
    order_type = map_order_type(data["pricetype"])
    action = data.get("action", "BUY").upper()

    if data["pricetype"] in ("MARKET", "SL-M"):
        original_type = data["pricetype"]
        logger.info(
            f"Modify MPP: {original_type} order detected for Symbol={data['symbol']}, "
            f"Exchange={data['exchange']}"
        )
        try:
            if auth_token:
                from broker.firstock.api.data import BrokerData

                broker_data = BrokerData(auth_token)
                quote_data = broker_data.get_quotes(data["symbol"], data["exchange"])
                instrument_type = get_instrument_type_from_symbol(data["symbol"])

                # Firstock's /getQuote response omits tick size, so fetch it
                # from the local master contract DB (same pattern as kotak).
                tick_size = quote_data.get("tick_size")
                if not tick_size:
                    symbol_info = get_symbol_info(data["symbol"], data["exchange"])
                    if symbol_info and symbol_info.tick_size:
                        tick_size = symbol_info.tick_size

                ltp = float(quote_data.get("ltp", 0))

                if ltp > 0:
                    protected_price = calculate_protected_price(
                        price=ltp,
                        action=action,
                        symbol=data["symbol"],
                        instrument_type=instrument_type,
                        tick_size=tick_size,
                    )
                    price = str(protected_price)
                    order_type = "LMT" if original_type == "MARKET" else "SL-LMT"
                    logger.info(
                        f"Modify MPP Conversion Complete: {original_type}->{order_type}, "
                        f"FinalPrice={protected_price}"
                    )
                else:
                    logger.warning(
                        f"Modify MPP Warning: LTP<=0 for Symbol={data['symbol']}; "
                        f"sending {original_type} unchanged"
                    )
            else:
                logger.warning(
                    f"Modify MPP Warning: No auth token for Symbol={data['symbol']}; "
                    f"sending {original_type} unchanged"
                )
        except Exception as e:
            logger.error(
                f"Modify MPP Error: Symbol={data['symbol']}, Error={str(e)}. "
                f"Sending {original_type} unchanged"
            )

    result = {
        "exchange": data["exchange"],
        "orderNumber": data["orderid"],
        "priceType": order_type,
        "price": price,
        "quantity": str(data["quantity"]),
        "tradingSymbol": symbol,
        "triggerPrice": str(data.get("trigger_price", "0")),
        "retention": "DAY",
        "mkt_protection": "0",
    }

    # product is optional on modify but included when supplied so V1 accepts
    # product changes (e.g. MIS -> CNC) alongside price/qty edits.
    if data.get("product"):
        result["product"] = map_product_type(data["product"])

    return result


def map_order_type(pricetype):
    """
    Maps the OpenAlgo pricetype to Firstock's order type.
    """
    order_type_mapping = {"MARKET": "MKT", "LIMIT": "LMT", "SL": "SL-LMT", "SL-M": "SL-MKT"}
    return order_type_mapping.get(pricetype, "MKT")  # Default to MKT if not found


def map_product_type(product):
    """
    Maps the OpenAlgo product type to Firstock's product type.
    """
    product_type_mapping = {"CNC": "C", "NRML": "M", "MIS": "I"}
    return product_type_mapping.get(product, "I")  # Default to I (MIS) if not found


def reverse_map_product_type(product):
    """
    Maps Firstock's product type to OpenAlgo product type.
    """
    reverse_product_type_mapping = {"C": "CNC", "M": "NRML", "I": "MIS"}
    return reverse_product_type_mapping.get(product, "MIS")  # Default to MIS if not found
