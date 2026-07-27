# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Pocketful API Parameters https://api.pocketful.in/docs/

from broker.pocketful.api.data import BrokerData
from database.token_db import get_br_symbol, get_symbol_info, get_token
from utils.logging import get_logger
from utils.mpp_slab import calculate_protected_price, get_instrument_type_from_symbol

logger = get_logger(__name__)


def transform_data(data, client_id=None, auth_token=None):
    """
    Transforms OpenAlgo order format to Pocketful order format.
    For market orders, fetches quotes and adjusts price using MPP (Market Price Protection):
    - EQ/FUT: Price < 100: 2%, 100-500: 1%, > 500: 0.5%
    - OPT (CE/PE): Price < 10: 5%, 10-100: 3%, 100-500: 2%, > 500: 1%

    Args:
        data: OpenAlgo order data dictionary
        client_id: Client ID to use for the order, if available
        auth_token: Authentication token for fetching quotes (passed from order_api)
    """
    # Get broker symbol for the order
    symbol = get_br_symbol(data["symbol"], data["exchange"])

    # Get the numeric token for the symbol
    token = get_token(data["symbol"], data["exchange"])

    # Map order type
    order_type = map_order_type(data["pricetype"])

    # Map order side (BUY/SELL)
    order_side = data["action"].upper()

    # Map product type
    product = map_product_type(data["product"])

    # Default price
    price = float(data.get("price", "0"))

    # Apply Market Price Protection for MARKET orders (case-insensitive check)
    if str(data.get("pricetype") or "").upper() == "MARKET":
        logger.info(
            f"MPP: MARKET order detected for Symbol={data['symbol']}, Exchange={data['exchange']}, Action={order_side}"
        )
        try:
            if auth_token:
                # Create BrokerData instance to fetch quotes
                broker_data = BrokerData(auth_token)

                # Fetch quotes for the symbol
                quote_data = broker_data.get_quotes(data["symbol"], data["exchange"])
                logger.info(
                    f"MPP Quote Response: Symbol={data['symbol']}, Exchange={data['exchange']}, "
                    f"LTP={quote_data.get('ltp')}, Bid={quote_data.get('bid')}, Ask={quote_data.get('ask')}"
                )

                # Get instrument type from symbol
                instrument_type = get_instrument_type_from_symbol(data["symbol"])

                # Get tick_size from database
                tick_size = None
                symbol_info = get_symbol_info(data["symbol"], data["exchange"])
                if symbol_info and symbol_info.tick_size:
                    tick_size = symbol_info.tick_size
                logger.info(
                    f"MPP Symbol Info: InstrumentType={instrument_type}, TickSize={tick_size}"
                )

                # Get LTP for price calculation
                ltp = float(quote_data.get("ltp", 0))

                if ltp > 0:
                    # Calculate protected price using centralized MPP slab with tick size from database
                    protected_price = calculate_protected_price(
                        price=ltp,
                        action=order_side,
                        symbol=data["symbol"],
                        instrument_type=instrument_type,
                        tick_size=tick_size,
                    )
                    price = protected_price

                    # Convert order type from MARKET to LIMIT
                    order_type = "LIMIT"
                    logger.info(
                        f"MPP Conversion Complete: Symbol={data['symbol']}, OrderType=MARKET->LIMIT, "
                        f"FinalPrice={protected_price}"
                    )
                else:
                    logger.warning(
                        f"MPP Warning: LTP is 0 or invalid for Symbol={data['symbol']}, "
                        f"Exchange={data['exchange']}. Proceeding with regular market order"
                    )
            else:
                logger.warning(
                    f"MPP Warning: No auth token available for Symbol={data['symbol']}. "
                    f"Cannot fetch quotes for MPP adjustment"
                )
        except Exception as e:
            logger.error(
                f"MPP Error: Failed to apply MPP for Symbol={data['symbol']}, "
                f"Exchange={data['exchange']}, Error={str(e)}. Proceeding with regular market order."
            )

    # Basic mapping
    transformed = {
        "exchange": data["exchange"],
        "instrument_token": token,  # Pocketful uses numeric instrument_token
        "client_id": client_id,  # Use the provided client_id
        "order_type": order_type,
        "amo": False,  # Default to regular order
        "price": price,
        "quantity": int(data["quantity"]),
        "disclosed_quantity": int(data.get("disclosed_quantity", "0")),
        "validity": "DAY",
        "product": product,
        "order_side": order_side,
        "device": "WEB",  # Default to WEB
        "user_order_id": 1,  # Default value
        "trigger_price": float(data.get("trigger_price", "0")),
        "execution_type": "REGULAR",  # Default to regular order
    }

    # Log order data for debugging
    logger.info(
        f"Transformed order data: exchange={transformed['exchange']}, "
        f"order_type={transformed['order_type']}, price={transformed['price']}, "
        f"quantity={transformed['quantity']}, order_side={transformed['order_side']}"
    )

    # Extended mapping for fields that might need conditional logic or additional processing
    transformed["disclosed_quantity"] = int(data.get("disclosed_quantity", "0"))
    transformed["trigger_price"] = float(data.get("trigger_price", "0"))

    return transformed


def transform_modify_order_data(data, client_id=None):
    """
    Transforms OpenAlgo order modification format to Pocketful order format.

    Args:
        data: OpenAlgo order data dictionary
        client_id: Client ID to use for the order, if available
    """
    # Get broker symbol for the order
    symbol = get_br_symbol(data["symbol"], data["exchange"])

    # Get the numeric token for the symbol
    token = get_token(data["symbol"], data["exchange"])

    # Map order type
    order_type = map_order_type(data["pricetype"])

    # Map order side (BUY/SELL)
    order_side = data["action"].upper()

    # Map product type
    product = map_product_type(data["product"])

    # Create the transformed data dictionary with all required fields for Pocketful API
    return {
        "exchange": data["exchange"],
        "instrument_token": token,
        "client_id": client_id,
        "order_type": order_type,
        "price": float(data.get("price", "0")),
        "quantity": int(data["quantity"]),
        "disclosed_quantity": int(data.get("disclosed_quantity", "0")),
        "validity": "DAY",
        "product": product,
        "order_side": order_side,
        "device": "WEB",
        "user_order_id": 1,
        "trigger_price": float(data.get("trigger_price", "0")),
        "oms_order_id": data.get(
            "orderid", ""
        ),  # This is the ID needed to identify which order to modify
        "execution_type": "REGULAR",
    }


def map_order_type(pricetype):
    """
    Maps OpenAlgo pricetype to Pocketful order type.
    """
    order_type_mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "SL",
        "SL-M": "SLM",  # Pocketful uses SLM instead of SL-M
    }
    return order_type_mapping.get(pricetype.upper(), "MARKET")  # Default to MARKET if not found


def map_product_type(product):
    """
    Maps OpenAlgo product type to Pocketful product type.
    """
    product_type_mapping = {"CNC": "CNC", "NRML": "NRML", "MIS": "MIS"}
    return product_type_mapping.get(product.upper(), "MIS")  # Default to MIS if not found


def reverse_map_product_type(exchange, product):
    """
    Reverse maps the broker product type to the OpenAlgo product type, considering the exchange.
    """
    # Exchange to OpenAlgo product type mapping for 'D'
    exchange_mapping = {
        "CNC": "CNC",
        "NRML": "NRML",
        "MIS": "MIS",
    }

    return exchange_mapping.get(product)
