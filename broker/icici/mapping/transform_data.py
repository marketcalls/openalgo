from utils.logging import get_logger

logger = get_logger(__name__)


def map_order_type(pricetype):
    """
    Maps OpenAlgo price types to Breeze order types.
    """
    pricetype = pricetype.upper()
    mapping = {
        "MARKET": "market",
        "LIMIT": "limit",
        "SL": "sl",
        "SL-M": "sl-m"
    }
    return mapping.get(pricetype, "market")


def map_exchange_type(exchange):
    """
    Maps OpenAlgo exchange to ICICI Breeze exchange.
    """
    mapping = {
        "NSE": "NSE",
        "BSE": "BSE",
        "NFO": "NSE",  # Futures also use NSE/BSE in Breeze
        "BFO": "BSE"
    }
    return mapping.get(exchange, exchange)


def map_exchange(brexchange):
    """
    Maps Breeze exchange code to OpenAlgo exchange.
    """
    mapping = {
        "NSE": "NSE",
        "BSE": "BSE"
    }
    return mapping.get(brexchange, brexchange)


def map_product_type(product):
    """
    Maps OpenAlgo product types to Breeze ones.
    """
    mapping = {
        "CNC": "cash",
        "NRML": "margin",
        "MIS": "margin"
    }
    return mapping.get(product.upper(), "cash")


def reverse_map_product_type(product):
    """
    Reverse maps Breeze product types to OpenAlgo.
    """
    mapping = {
        "cash": "CNC",
        "margin": "NRML"
    }
    return mapping.get(product.lower(), "NRML")


def transform_data(data, token):
    """
    Transforms OpenAlgo request into Breeze API structure.
    """
    try:
        order_type = map_order_type(data["pricetype"])
        transformed = {
            "stock_code": data["symbol"],
            "exchange_code": map_exchange_type(data["exchange"]),
            "product_type": map_product_type(data["product"]),
            "order_type": order_type,
            "quantity": int(data["quantity"]),
            "price": float(data.get("price", 0)) if order_type == "limit" else 0,
            "action": data["action"].upper(),
            "validity": "day",
            "stock_token": token
        }

        # Required for SL/SL-M
        if order_type in ["sl", "sl-m"]:
            trigger_price = float(data.get("trigger_price", 0))
            if not trigger_price:
                raise ValueError("Trigger price is required for Stop Loss orders")
            transformed["stoploss"] = trigger_price

        return transformed

    except Exception as e:
        logger.error(f"Error transforming order data: {e}")
        raise


def transform_modify_order_data(data):
    """
    Breeze does not support order modification; stub only.
    """
    logger.warning("Breeze does not support modify order.")
    return {}
