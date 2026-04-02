# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Samco Parameters https://www.samco.in/stocknote-api-documentation

from database.token_db import get_br_symbol, get_symbol_info
from utils.logging import get_logger
from utils.mpp_slab import (
    calculate_protected_price,
    get_instrument_type_from_symbol,
    get_mpp_percentage,
)

logger = get_logger(__name__)


def transform_data(data, token, auth_token=None):
    """
    Transforms the OpenAlgo API request structure to Samco expected structure.

    For MARKET orders, fetches LTP and converts to LIMIT with MPP (Market Price Protection).
    For SL-M orders, converts to SL with protected limit price based on trigger price.
    Samco no longer accepts MKT or SL-M order types.

    Args:
        data: Order data dictionary
        token: Instrument token
        auth_token: Authentication token for fetching quotes
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])

    # Default values
    price = str(data.get("price", "0"))
    order_type = map_order_type(data["pricetype"])
    action = data["action"].upper()
    mpp_percentage = None

    # Apply Market Price Protection for MARKET orders (Samco only accepts L/SL)
    if data["pricetype"] == "MARKET":
        logger.info(
            f"MPP: MARKET order detected for Symbol={data['symbol']}, "
            f"Exchange={data['exchange']}, Action={action}"
        )
        try:
            if auth_token:
                from broker.samco.api.data import BrokerData

                broker_data = BrokerData(auth_token)
                quote_data = broker_data.get_quotes(data["symbol"], data["exchange"])
                logger.info(
                    f"MPP Quote Response: Symbol={data['symbol']}, "
                    f"LTP={quote_data.get('ltp') if quote_data else None}"
                )

                if quote_data:
                    instrument_type = get_instrument_type_from_symbol(data["symbol"])
                    tick_size = None
                    symbol_info = get_symbol_info(data["symbol"], data["exchange"])
                    if symbol_info and symbol_info.tick_size:
                        tick_size = symbol_info.tick_size

                    ltp = float(quote_data.get("ltp", 0))

                    if ltp > 0:
                        mpp_percentage = get_mpp_percentage(ltp, instrument_type)
                        protected_price = calculate_protected_price(
                            price=ltp,
                            action=action,
                            symbol=data["symbol"],
                            instrument_type=instrument_type,
                            tick_size=tick_size,
                        )
                        price = str(protected_price)
                        order_type = "L"
                        logger.info(
                            f"MPP Conversion: Symbol={data['symbol']}, MKT->L, "
                            f"LTP={ltp}, ProtectedPrice={protected_price}, MPP={mpp_percentage}%"
                        )
                    else:
                        raise ValueError(
                            f"LTP is 0 for Symbol={data['symbol']}. Cannot determine market price."
                        )
                else:
                    raise ValueError(
                        f"No quote data for Symbol={data['symbol']}. Cannot determine market price."
                    )
            else:
                raise ValueError(
                    f"No auth token for Symbol={data['symbol']}. Cannot fetch quotes for MPP."
                )
        except Exception as e:
            logger.error(f"MPP Error: {str(e)}")
            raise ValueError(f"MARKET order failed: {str(e)}")

    # Apply Market Price Protection for SL-M orders (convert to SL with protected price)
    elif data["pricetype"] == "SL-M":
        try:
            trigger_price = float(data.get("trigger_price", 0))
        except (TypeError, ValueError):
            trigger_price = 0.0
        logger.info(
            f"MPP: SL-M order detected for Symbol={data['symbol']}, "
            f"Action={action}, TriggerPrice={trigger_price}"
        )
        if trigger_price > 0:
            try:
                instrument_type = get_instrument_type_from_symbol(data["symbol"])
                tick_size = None
                symbol_info = get_symbol_info(data["symbol"], data["exchange"])
                if symbol_info and symbol_info.tick_size:
                    tick_size = symbol_info.tick_size

                mpp_percentage = get_mpp_percentage(trigger_price, instrument_type)
                protected_price = calculate_protected_price(
                    price=trigger_price,
                    action=action,
                    symbol=data["symbol"],
                    instrument_type=instrument_type,
                    tick_size=tick_size,
                )
                price = str(protected_price)
                order_type = "SL"
                logger.info(
                    f"MPP Conversion: Symbol={data['symbol']}, SL-M->SL, "
                    f"TriggerPrice={trigger_price}, LimitPrice={protected_price}, MPP={mpp_percentage}%"
                )
            except Exception as e:
                logger.error(
                    f"MPP Error: Failed for SL-M Symbol={data['symbol']}, Error={str(e)}. "
                    f"Falling back to SL order type"
                )
                order_type = "SL"
        else:
            logger.warning(
                f"MPP Warning: Trigger price is 0 for SL-M Symbol={data['symbol']}. "
                f"Falling back to SL order type"
            )
            order_type = "SL"

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
        if price == "0" and data["pricetype"] in ["LIMIT", "SL"]:
            price = str(data.get("price", "0"))
        transformed["price"] = price

    # Add trigger price for SL orders
    if order_type == "SL" or data["pricetype"] in ["SL", "SL-M"]:
        transformed["triggerPrice"] = str(data.get("trigger_price", "0"))

    # Add marketProtection for MPP-converted orders (dynamic slab percentage)
    if data["pricetype"] in ["MARKET", "SL-M"] and mpp_percentage is not None:
        transformed["marketProtection"] = str(int(mpp_percentage))

    return transformed


def transform_modify_order_data(data):
    """
    Transforms the OpenAlgo modify order request to Samco expected structure.
    Only includes fields that can be modified (orderNumber goes in URL).
    """
    transformed = {
        "orderType": map_order_type(data["pricetype"]),
        "quantity": str(data["quantity"]),
        "orderValidity": "DAY",
    }

    # Only add disclosedQuantity if provided and > 0 (must be min 10% of quantity)
    disclosed_qty = data.get("disclosed_quantity")
    if disclosed_qty and int(disclosed_qty) > 0:
        transformed["disclosedQuantity"] = str(disclosed_qty)

    # Add price for LIMIT and SL orders
    if data["pricetype"] in ["LIMIT", "SL"]:
        transformed["price"] = str(data.get("price", "0"))

    # Add trigger price for SL and SL-M orders
    if data["pricetype"] in ["SL", "SL-M"]:
        transformed["triggerPrice"] = str(data.get("trigger_price", "0"))

    return transformed


def map_order_type(pricetype):
    """
    Maps OpenAlgo pricetype to Samco order type.
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
