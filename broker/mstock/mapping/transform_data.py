#Mapping OpenAlgo API Request https://openalgo.in/docs
#Mapping MStock Type B Parameters https://tradingapi.mstock.com/docs/v1/typeB/Orders/

from database.token_db import get_br_symbol

def transform_data(data, token):
    """
    Transforms the OpenAlgo API request structure to mStock Type B format.

    Args:
        data: OpenAlgo order data
        token: Symbol token from database

    Returns:
        dict: mStock Type B order parameters
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])

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
        "disclosedquantity": str(data.get("disclosed_quantity", "")),
        "duration": "DAY",
        "ordertag": ""
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
    symbol = get_br_symbol(data["symbol"], data["exchange"])

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
        "disclosedquantity": str(data.get("disclosed_quantity", "")),
        "modqty_remng": "0"
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
        "SL-M": "STOPLOSS_MARKET"
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
    variety_mapping = {
        "MARKET": "NORMAL",
        "LIMIT": "NORMAL",
        "SL": "STOPLOSS",
        "SL-M": "STOPLOSS"
    }
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
