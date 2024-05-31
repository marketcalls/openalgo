#Mapping OpenAlgo API Request https://openalgo.in/docs
#Mapping Angel Broking Parameters https://smartapi.angelbroking.com/docs/Orders

from database.token_db import get_br_symbol

def transform_data(data,token):
    """
    Transforms the new API request structure to the current expected structure.
    """
    symbol = get_br_symbol(data["symbol"],data["exchange"])
    # Basic mapping
    transformed = {
        "am":"NO",
        "dq":data.get("disclosed_quantity", "0"),
        "bc":"1",
        "es":reverse_map_exchange(data["exchange"]),
        "mp":"0",
        "pc":data.get("product", "MIS"),
        "pf":"N",
        "pr":data.get("price", "0"),
        "pt":map_order_type(data["pricetype"]),
        "qt":data["quantity"],
        "rt":"DAY",
        "tp":data.get("trigger_price", "0"),
        "ts":symbol,
        "tt":'B' if data['action'] == 'BUY' else ('S' if data['action'] == 'SELL' else 'None')
    }
    return transformed


def transform_modify_order_data(data, token):
    symbol = get_br_symbol(data["symbol"],data["exchange"])
    # Basic mapping
    transformed = {
        "tk":token,
        "dq":data.get("disclosed_quantity", "0"),
        "es":reverse_map_exchange(data["exchange"]),
        "mp":"0",
        "dd":"NA",
        "vd":"DAY",
        "pc":data.get("product", "MIS"),
        "pr":data.get("price", "0"),
        "pt":map_order_type(data["pricetype"]),
        "qt":data["quantity"],
        "tp":data.get("trigger_price", "0"),
        "ts":symbol,
        "no":data["orderid"],
        "tt":'B' if data['action'] == 'BUY' else ('S' if data['action'] == 'SELL' else 'None')
    }
    return transformed



def map_order_type(pricetype):
    """
    Maps the new pricetype to the existing order type.
    """
    order_type_mapping = {
        "MARKET": "MKT",
        "LIMIT": "L",
        "SL": "SL",
        "SL-M": "SL-M"
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
    return product_type_mapping.get(product)  # Default to DELIVERY if not found


def map_variety(pricetype):
    """
    Maps the pricetype to the existing order variety.
    """
    variety_mapping = {
        "MARKET": "NORMAL",
        "LIMIT": "NORMAL",
        "SL": "STOPLOSS",
        "SL-M": "STOPLOSS"
    }
    return variety_mapping.get(pricetype, "NORMAL")  # Default to DELIVERY if not found

def map_exchange(brexchange):
    """
    Maps the Broker Exchange to the OpenAlgo Exchange.
    """
    

    exchange_mapping = {
        "nse_cm": "NSE",
        "bse_cm": "BSE",
        "cde_fo": "CDS",
        "nse_fo": "NFO",
        "bse_fo": "BFO",
        "bcs_fo": "BCD",
        "mcx_fo": "MCX"

    }
    return exchange_mapping.get(brexchange)

def reverse_map_exchange(exchange):
    """
    Maps the Broker Exchange to the OpenAlgo Exchange.
    """

    exchange_mapping = {
        "NSE": "nse_cm",
        "BSE": "bse_cm",
        "CDS": "cde_fo",
        "NFO": "nse_fo",
        "BFO": "bse_fo",
        "BCD": "bcs_fo",
        "MCX": "mcx_fo"
    }
    return exchange_mapping.get(exchange)

def reverse_map_product_type(product):
    """
    Maps the new product type to the existing product type.
    """
    reverse_product_type_mapping = {
        "CNC": "CNC",
        "NRML": "NRML",
        "MIS": "MIS",
    }
    return reverse_product_type_mapping.get(product)  

