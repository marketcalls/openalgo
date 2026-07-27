# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping MStock Type B Parameters https://tradingapi.mstock.com/docs/v1/typeB/Orders/

from database.symbol import SymToken
from database.token_db import get_br_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


def get_mstock_symbol(symbol: str, exchange: str) -> str:
    """
    Get mStock broker symbol with priority for -EQ (regular equity) over -BE (book entry).

    Args:
        symbol: OpenAlgo format symbol (e.g., "NHPC")
        exchange: Exchange code (e.g., "NSE")

    Returns:
        str: Broker symbol with -EQ preferred (e.g., "NHPC-EQ" instead of "NHPC-BE")
    """
    try:
        # Query all matching symbols from database
        matches = SymToken.query.filter_by(symbol=symbol, exchange=exchange).all()

        if not matches:
            logger.warning(f"No symbol found for {symbol} on {exchange}")
            return get_br_symbol(symbol, exchange)  # Fallback to default

        # If only one match, return it
        if len(matches) == 1:
            return matches[0].brsymbol

        # Multiple matches - prioritize -EQ over -BE and other suffixes
        # Priority order: -EQ > -BZ > -BE > others
        priority_order = {
            "EQ": 1,  # Regular equity - highest priority
            "BZ": 2,  # Z category
            "BE": 3,  # Book entry - lower priority
        }

        def get_priority(brsymbol):
            """Extract suffix and return priority (lower number = higher priority)"""
            if "-" in brsymbol:
                suffix = brsymbol.split("-")[-1]
                return priority_order.get(suffix, 999)  # Unknown suffixes get lowest priority
            return 999  # No suffix gets lowest priority

        # Sort by priority and return the highest priority match
        sorted_matches = sorted(matches, key=lambda x: get_priority(x.brsymbol))
        selected = sorted_matches[0].brsymbol

        logger.debug(f"Selected {selected} from {len(matches)} matches for {symbol}-{exchange}")
        return selected

    except Exception as e:
        logger.error(f"Error in get_mstock_symbol for {symbol}-{exchange}: {e}")
        # Fallback to default behavior
        return get_br_symbol(symbol, exchange)


def transform_data(data, token):
    """
    Transforms the OpenAlgo API request structure to mStock Type B format.

    Args:
        data: OpenAlgo order data
        token: Symbol token from database

    Returns:
        dict: mStock Type B order parameters
    """
    symbol = get_mstock_symbol(data["symbol"], data["exchange"])

    # Get disclosed quantity, default to "0" if not provided or empty
    disclosed_qty = data.get("disclosed_quantity", "")
    if not disclosed_qty or disclosed_qty == "":
        disclosed_qty = "0"

    transformed = {
        "variety": map_variety(data["pricetype"]),
        "tradingsymbol": symbol,
        "symboltoken": token,
        "exchange": data["exchange"],
        "transactiontype": data["action"].upper(),
        "ordertype": map_order_type(data["pricetype"]),
        "quantity": str(data["quantity"]),
        "producttype": map_product_type(data["product"]),
        "price": str(data.get("price", "0")),
        "triggerprice": str(data.get("trigger_price", "0")),
        "squareoff": "0",
        "stoploss": "0",
        "trailingStopLoss": "",
        "disclosedquantity": str(disclosed_qty),
        "duration": "DAY",
        "ordertag": "",
    }

    return transformed


def transform_modify_order_data(data, token):
    """
    Transforms the OpenAlgo modify order request to mStock Type B format.

    Args:
        data: OpenAlgo modify order data
        token: Symbol token from database

    Returns:
        dict: mStock Type B modify order parameters
    """
    symbol = get_mstock_symbol(data["symbol"], data["exchange"])

    # Get disclosed quantity, default to "0" if not provided or empty
    disclosed_qty = data.get("disclosed_quantity", "")
    if not disclosed_qty or disclosed_qty == "":
        disclosed_qty = "0"

    return {
        "variety": map_variety(data["pricetype"]),
        "tradingsymbol": symbol,
        "symboltoken": token,
        "exchange": data["exchange"],
        "transactiontype": data["action"].upper(),
        "orderid": data["orderid"],
        "ordertype": map_order_type(data["pricetype"]),
        "quantity": str(data["quantity"]),
        "producttype": map_product_type(data["product"]),
        "duration": "DAY",
        "price": str(data.get("price", "0")),
        "triggerprice": str(data.get("trigger_price", "0")),
        "disclosedquantity": str(disclosed_qty),
        "modqty_remng": "0",
    }


def map_order_type(pricetype):
    """
    Maps OpenAlgo pricetype to mStock Type B order type.

    mStock Type B order types: MARKET, LIMIT, STOP_LOSS, STOPLOSS_MARKET
    """
    order_type_mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "STOP_LOSS",
        "SL-M": "STOPLOSS_MARKET",
    }
    return order_type_mapping.get(pricetype, "MARKET")


def map_product_type(product):
    """
    Maps OpenAlgo product type to mStock Type B product type.

    mStock Type B product types: DELIVERY, INTRADAY, MARGIN, CARRYFORWARD
    """
    product_type_mapping = {
        "CNC": "DELIVERY",
        "NRML": "CARRYFORWARD",
        "MIS": "INTRADAY",
    }
    return product_type_mapping.get(product, "INTRADAY")


def map_variety(pricetype):
    """
    Maps OpenAlgo pricetype to mStock Type B variety.

    mStock Type B varieties: NORMAL, AMO, ROBO, STOPLOSS
    """
    variety_mapping = {"MARKET": "NORMAL", "LIMIT": "NORMAL", "SL": "STOPLOSS", "SL-M": "STOPLOSS"}
    return variety_mapping.get(pricetype, "NORMAL")


def reverse_map_product_type(product):
    """
    Reverse maps mStock Type B product type to OpenAlgo product type.
    """
    reverse_product_type_mapping = {
        "DELIVERY": "CNC",
        "CARRYFORWARD": "NRML",
        "INTRADAY": "MIS",
        "MARGIN": "MIS",
    }
    return reverse_product_type_mapping.get(product)
