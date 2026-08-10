# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Samco Parameters https://docs-tradeapi.samco.in/

from database.token_db import get_br_symbol, get_symbol_info
from utils.logging import get_logger
from utils.mpp_slab import (
    calculate_protected_price,
    get_instrument_type_from_symbol,
    get_mpp_percentage,
)

logger = get_logger(__name__)


def _protected_price(price, action, symbol, exchange):
    """
    Compute the MPP-protected limit price and slab percentage for a reference price.

    Returns:
        tuple: (protected_price, mpp_percentage)
    """
    instrument_type = get_instrument_type_from_symbol(symbol)
    tick_size = None
    symbol_info = get_symbol_info(symbol, exchange)
    if symbol_info and symbol_info.tick_size:
        tick_size = symbol_info.tick_size

    mpp_percentage = get_mpp_percentage(price, instrument_type)
    protected = calculate_protected_price(
        price=price,
        action=action,
        symbol=symbol,
        instrument_type=instrument_type,
        tick_size=tick_size,
    )
    return protected, mpp_percentage


def resolve_order_type(data, auth_token=None):
    """
    Resolve an OpenAlgo pricetype to the order type Samco accepts, applying
    Market Price Protection where needed.

    Samco's placeOrder and modifyOrder parameter tables document only L (Limit)
    and SL (Stop Loss Limit). MARKET is therefore converted to L at a protected
    price derived from the LTP, and SL-M to SL at a protected price derived from
    the trigger price. The slab percentage is sent as marketProtection.

    Args:
        data: Order data dictionary (symbol, exchange, action, pricetype, ...)
        auth_token: Session token, required to fetch the LTP for MARKET orders

    Returns:
        tuple: (order_type, price, mpp_percentage)

    Raises:
        ValueError: MARKET order whose LTP cannot be determined
    """
    pricetype = data["pricetype"]
    symbol = data["symbol"]
    exchange = data["exchange"]
    action = data["action"].upper()

    price = str(data.get("price", "0"))
    order_type = map_order_type(pricetype)
    mpp_percentage = None

    # Apply Market Price Protection for MARKET orders (Samco only accepts L/SL)
    if pricetype == "MARKET":
        logger.info(
            f"MPP: MARKET order detected for Symbol={symbol}, "
            f"Exchange={exchange}, Action={action}"
        )
        try:
            if not auth_token:
                raise ValueError(f"No auth token for Symbol={symbol}. Cannot fetch quotes for MPP.")

            from broker.samco.api.data import BrokerData

            broker_data = BrokerData(auth_token)
            quote_data = broker_data.get_quotes(symbol, exchange)
            logger.info(
                f"MPP Quote Response: Symbol={symbol}, "
                f"LTP={quote_data.get('ltp') if quote_data else None}"
            )

            if not quote_data:
                raise ValueError(f"No quote data for Symbol={symbol}. Cannot determine market price.")

            ltp = float(quote_data.get("ltp", 0))
            if ltp <= 0:
                raise ValueError(f"LTP is 0 for Symbol={symbol}. Cannot determine market price.")

            protected, mpp_percentage = _protected_price(ltp, action, symbol, exchange)
            price = str(protected)
            order_type = "L"
            logger.info(
                f"MPP Conversion: Symbol={symbol}, MKT->L, "
                f"LTP={ltp}, ProtectedPrice={protected}, MPP={mpp_percentage}%"
            )
        except Exception as e:
            logger.error(f"MPP Error: {str(e)}")
            raise ValueError(f"MARKET order failed: {str(e)}")

    # Apply Market Price Protection for SL-M orders (convert to SL with protected price)
    elif pricetype == "SL-M":
        try:
            trigger_price = float(data.get("trigger_price", 0))
        except (TypeError, ValueError):
            trigger_price = 0.0
        logger.info(
            f"MPP: SL-M order detected for Symbol={symbol}, "
            f"Action={action}, TriggerPrice={trigger_price}"
        )
        order_type = "SL"
        # Samco's SL needs a real limit price. Falling through with price "0"
        # and triggerPrice "0" builds an order the exchange is guaranteed to
        # reject, so fail here instead of sending it - same as the MARKET branch.
        if trigger_price <= 0:
            raise ValueError(
                f"SL-M order failed: trigger price is required for Symbol={symbol}"
            )
        try:
            protected, mpp_percentage = _protected_price(trigger_price, action, symbol, exchange)
            price = str(protected)
            logger.info(
                f"MPP Conversion: Symbol={symbol}, SL-M->SL, "
                f"TriggerPrice={trigger_price}, LimitPrice={protected}, MPP={mpp_percentage}%"
            )
        except Exception as e:
            logger.error(f"MPP Error: Failed for SL-M Symbol={symbol}, Error={str(e)}")
            raise ValueError(f"SL-M order failed: {str(e)}")

    return order_type, price, mpp_percentage


def _format_market_protection(mpp_percentage):
    """
    Render the MPP slab as Samco's marketProtection percentage.

    Must not be int()-truncated: the EQ/FUT slab above Rs 500 is 0.5%, so
    int() sends "0" - no protection at all - for most large-cap equities and
    futures. %g keeps 0.5 as "0.5" and 3.0 as "3".
    """
    return f"{mpp_percentage:g}"


def transform_data(data, token, auth_token=None):
    """
    Transforms the OpenAlgo API request structure to Samco expected structure.

    Args:
        data: Order data dictionary
        token: Instrument token
        auth_token: Authentication token for fetching quotes
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])
    action = data["action"].upper()

    order_type, price, mpp_percentage = resolve_order_type(data, auth_token)

    # Basic mapping for Samco placeOrder API
    transformed = {
        "symbolName": symbol,
        "exchange": data["exchange"],
        "transactionType": action,
        "orderType": order_type,
        "quantity": str(data["quantity"]),
        "disclosedQuantity": str(data.get("disclosed_quantity", "0")),
        "orderValidity": "DAY",
        "productType": map_product_type(data["product"]),
        "afterMarketOrderFlag": "NO",
    }

    # Add price for LIMIT and SL orders (and MPP-converted orders)
    if order_type in ["L", "SL"]:
        # resolve_order_type() already set price from data["price"] for LIMIT/SL
        # and to the MPP-protected price for converted MARKET/SL-M orders.
        transformed["price"] = price

    # Add trigger price for SL orders
    if order_type == "SL" or data["pricetype"] in ["SL", "SL-M"]:
        transformed["triggerPrice"] = str(data.get("trigger_price", "0"))

    # Add marketProtection for MPP-converted orders (dynamic slab percentage)
    if data["pricetype"] in ["MARKET", "SL-M"] and mpp_percentage is not None:
        transformed["marketProtection"] = _format_market_protection(mpp_percentage)

    return transformed


def transform_modify_order_data(data, auth_token=None):
    """
    Transforms the OpenAlgo modify order request to Samco expected structure.
    Only includes fields that can be modified (orderNumber goes in URL).

    modifyOrder accepts the same L / SL order types as placeOrder, so MARKET and
    SL-M are put through the same Market Price Protection conversion rather than
    being sent through as the undocumented MKT / SL-M values.
    """
    order_type, price, mpp_percentage = resolve_order_type(data, auth_token)

    transformed = {
        "orderType": order_type,
        "quantity": str(data["quantity"]),
        "orderValidity": "DAY",
    }

    # Only add disclosedQuantity if provided and > 0 (must be min 10% of quantity)
    disclosed_qty = data.get("disclosed_quantity")
    if disclosed_qty and int(disclosed_qty) > 0:
        transformed["disclosedQuantity"] = str(disclosed_qty)

    # Add price for LIMIT and SL orders (and MPP-converted orders)
    if order_type in ["L", "SL"]:
        # resolve_order_type() already set price from data["price"] for LIMIT/SL
        # and to the MPP-protected price for converted MARKET/SL-M orders.
        transformed["price"] = price

    # Add trigger price for SL and SL-M orders
    if order_type == "SL" or data["pricetype"] in ["SL", "SL-M"]:
        transformed["triggerPrice"] = str(data.get("trigger_price", "0"))

    # Add marketProtection for MPP-converted orders (dynamic slab percentage)
    if data["pricetype"] in ["MARKET", "SL-M"] and mpp_percentage is not None:
        transformed["marketProtection"] = _format_market_protection(mpp_percentage)

    return transformed


def map_order_type(pricetype):
    """
    Maps OpenAlgo pricetype to Samco order type.

    MARKET and SL-M are placeholders here - resolve_order_type() converts them to
    L / SL with Market Price Protection, which is all Samco's order APIs document.
    """
    order_type_mapping = {"MARKET": "MKT", "LIMIT": "L", "SL": "SL", "SL-M": "SL-M"}
    return order_type_mapping.get(pricetype, "MKT")


def map_product_type(product):
    """
    Maps OpenAlgo product type to Samco product type.
    """
    product_type_mapping = {
        "CNC": "CNC",
        "NRML": "NRML",
        "MIS": "MIS",
    }
    return product_type_mapping.get(product, "MIS")


def reverse_map_product_type(product):
    """
    Maps Samco product type back to OpenAlgo product type.
    """
    reverse_product_type_mapping = {
        "CNC": "CNC",
        "NRML": "NRML",
        "MIS": "MIS",
    }
    return reverse_product_type_mapping.get(product, "MIS")
