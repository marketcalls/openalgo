# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Zerodha Broking Parameters https://kite.trade/docs/connect/v3/

from broker.zerodha.mapping.mcx_contract_size import to_kite_quantity
from database.token_db import get_br_symbol


def _kite_qty(value, symbol, exchange, default="0"):
    """Convert an outbound quantity field from OpenAlgo units to Kite contracts.

    A no-op off MCX. Blank and missing values fall back to the default rather
    than raising, since disclosed_quantity is routinely absent.
    """
    if value in (None, ""):
        value = default
    return to_kite_quantity(value, symbol, exchange)


def transform_data(data):
    """
    Transforms the new API request structure to the current expected structure.
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])

    # Basic mapping
    transformed = {
        "tradingsymbol": symbol,
        "exchange": data["exchange"],
        "transaction_type": data["action"].upper(),
        "order_type": data["pricetype"],
        # MCX only: OpenAlgo counts units like every other broker, Kite counts
        # contracts, so one lot of crude leaves here as 1 rather than 100.
        # See mapping/mcx_contract_size.py.
        "quantity": _kite_qty(data["quantity"], data["symbol"], data["exchange"]),
        "product": data["product"],
        "price": data.get("price", "0"),
        "trigger_price": data.get("trigger_price", "0"),
        "disclosed_quantity": _kite_qty(
            data.get("disclosed_quantity"), data["symbol"], data["exchange"]
        ),
        "validity": "DAY",
        "market_protection": "-1",
        "tag": "openalgo",
    }

    # Extended mapping for fields that might need conditional logic or additional processing
    transformed["trigger_price"] = data.get("trigger_price", "0")

    return transformed


def transform_modify_order_data(data):
    symbol, exchange = data.get("symbol"), data.get("exchange")
    return {
        "order_type": map_order_type(data["pricetype"]),
        "quantity": _kite_qty(data["quantity"], symbol, exchange),
        "price": data["price"],
        "trigger_price": data.get("trigger_price", "0"),
        "disclosed_quantity": _kite_qty(data.get("disclosed_quantity"), symbol, exchange),
        "validity": "DAY",
    }


def map_order_type(pricetype):
    """
    Maps the new pricetype to the existing order type.
    """
    order_type_mapping = {"MARKET": "MARKET", "LIMIT": "LIMIT", "SL": "SL", "SL-M": "SL-M"}
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
