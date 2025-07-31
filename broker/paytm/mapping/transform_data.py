# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Paytm Broking Parameters https://developer.paytmmoney.com/docs/api/login

from database.token_db import get_token


def transform_data(data):
    """
    Transforms the OpenAlgo API request structure to Paytm v2 API structure.
    """
    symbol = get_token(data['symbol'], data['exchange'])
    txn_type = "B" if data['action'].upper() == "BUY" else "S"
    # Source from which the order is placed
    # Website - W, mWeb - M, Android - N, iOS - I, Exe - R, OperatorWorkStation - O
    source = "M"
    # This describes, to which segment the transaction belongs. (E→ Equity Cash / D→ Equity Derivative)
    segment = "E" if data['exchange'] in ['NSE', 'BSE'] else "D"

    # Basic mapping
    transformed = {
        "security_id": symbol,
        "exchange": map_exchange(data['exchange']),
        "txn_type": txn_type,
        "order_type": reverse_map_order_type(data["pricetype"]),
        "quantity": data["quantity"],
        "product": reverse_map_product_type(data["product"]),
        "price": data.get("price", "0"),
        # "trigger_price": data.get("trigger_price", "0"),
        # "disclosed_quantity": data.get("disclosed_quantity", "0"),
        "validity": "DAY",
        "segment": segment,
        "source": source,
    }

    # Extended mapping for fields that might need conditional logic or additional processing
    # transformed["trigger_price"] = data.get("trigger_price", "0")

    return transformed

# As long as an order is pending in the system, certain attributes of it can be modified. 
# Price, quantity, validity, product are some of the variables that can be modified by the user.
# You have to pass "order_no", "serial_no" "group_id" as compulsory to modify the order.


def transform_modify_order_data(data):
    return {
        "product": reverse_map_product_type(data["product"]),
        "quantity": data["quantity"],
        "price": data["price"],
        "validity": "DAY"
    }


def map_order_type(pricetype):
    """
    Maps the new pricetype to the existing order type.
    """
    order_type_mapping = {
        "MKT": "MARKET",
        "LMT": "LIMIT",
        "SL": "STOP_LOSS",
        "SLM": "STOP_LOSS_MARKET"
    }
    # Default to MARKET if not found
    return order_type_mapping.get(pricetype, "MARKET")


def map_product_type(product):
    """
    Maps the new product type to the existing product type.
    """
    product_type_mapping = {
        "C": "CNC",
        "M": "MARGIN",
        "I": "MIS",
    }
    # Default to INTRADAY if not found
    return product_type_mapping.get(product, "MIS")


def reverse_map_product_type(product):
    """
    Reverse maps the broker product type to the OpenAlgo product type, considering the exchange.
    """
    # Exchange to OpenAlgo product type mapping for 'D'
    exchange_mapping = {
        "CNC": "C",
        "MARGIN": "M",
        "MIS": "I"
    }

    return exchange_mapping.get(product)


def reverse_map_order_type(order_type):
    """
    Reverse maps the Paytm order type to the OpenAlgo order type.
    """
    reverse_order_type_mapping = {
        "MARKET": "MKT",
        "LIMIT": "LMT",
        "STOP_LOSS": "SL",
        "STOP_LOSS_MARKET": "SLM"
    }
    # Default to MKT if not found
    return reverse_order_type_mapping.get(order_type, "MKT")

def map_exchange(exchange):
    """
    Maps the new exchange to the existing exchange.
    """
    exchange_mapping = {
        "NSE": "NSE",
        "BSE": "BSE",
        "NFO": "NSE",
        "BFO": "BSE",
        "EXCHANGE": "EXCHANGE"
    }
    return exchange_mapping.get(exchange, "EXCHANGE")
