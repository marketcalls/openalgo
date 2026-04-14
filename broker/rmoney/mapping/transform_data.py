# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping RMoney XTS Broking Parameters

from database.token_db import get_br_symbol, get_token
from utils.logging import get_logger

logger = get_logger(__name__)


def transform_data(data, token):
    """
    Transforms the new API request structure to the current expected structure.
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])
    # token = get_token(data['symbol'], data['exchange'])
    # logger.info(f"token: {token}")
    # Basic mapping - ensure correct data types per XTS API spec
    transformed = {
        "exchangeSegment": map_exchange(data["exchange"]),
        "exchangeInstrumentID": int(token),
        "productType": map_product_type(data["product"]),
        "orderType": map_order_type(data["pricetype"]),
        "orderSide": data["action"].upper(),
        "timeInForce": "DAY",
        "disclosedQuantity": int(data.get("disclosed_quantity", "0")),
        "orderQuantity": int(data["quantity"]),
        "limitPrice": float(data.get("price", "0")),
        "stopPrice": float(data.get("trigger_price", "0")),
        "orderUniqueIdentifier": "openalgo",
    }
    logger.info(f"transformed data: {transformed}")
    return transformed


def transform_modify_order_data(data, token):
    return {
        "appOrderID": data["orderid"],
        "modifiedProductType": map_product_type(data["product"]),
        "modifiedOrderType": map_order_type(data["pricetype"]),
        "modifiedOrderQuantity": data["quantity"],
        "modifiedDisclosedQuantity": data.get("disclosed_quantity", "0"),
        "modifiedLimitPrice": data["price"],
        "modifiedStopPrice": data.get("trigger_price", "0"),
        "modifiedTimeInForce": "DAY",
        "orderUniqueIdentifier": "openalgo",
    }


def map_exchange(exchange):
    """
    Maps the OpenAlgo exchange to the broker exchange string format.
    Used for order placement API.

    Per XTS Interactive API docs, exchangeSegment must be a string:
    "NSECM", "NSEFO", "NSECD", "BSECM", "BSEFO", "MCXFO"
    """
    exchange_mapping = {
        "NSE": "NSECM",
        "BSE": "BSECM",
        "MCX": "MCXFO",
        "NFO": "NSEFO",
        "BFO": "BSEFO",
        "CDS": "NSECD",
    }
    if exchange not in exchange_mapping:
        raise ValueError(f"Unsupported exchange: {exchange}")
    return exchange_mapping[exchange]


def map_exchange_numeric(exchange):
    """
    Maps the OpenAlgo exchange to the broker's numeric exchange code.
    Used for margin calculator API which requires numeric exchange segments.

    Reference: XTS API Documentation - ExchangeSegments Enum
    - NSECM = 1 (NSE Cash Market)
    - NSEFO = 2 (NSE Futures & Options)
    - NSECD = 3 (NSE Currency Derivatives)
    - BSECM = 11 (BSE Cash Market)
    - BSEFO = 12 (BSE Futures & Options)
    - BSECD = 13 (BSE Currency Derivatives)
    - MCXFO = 51 (MCX Futures & Options)
    - NCDEX = 21 (NCDEX Commodity)
    """
    exchange_numeric_mapping = {
        "NSE": 1,      # NSECM
        "NFO": 2,      # NSEFO
        "CDS": 3,      # NSECD
        "BSE": 11,     # BSECM
        "BFO": 12,     # BSEFO
        "MCX": 51,     # MCXFO
    }
    if exchange not in exchange_numeric_mapping:
        raise ValueError(f"Unsupported exchange: {exchange}")
    return exchange_numeric_mapping[exchange]


def map_order_type(pricetype):
    """
    Maps the new pricetype to the existing order type.
    """
    order_type_mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "STOPLIMIT",
        "SL-M": "STOPMARKET",
    }
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
    return product_type_mapping.get(product, "MIS")  # Default to INTRADAY if not found


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
