#Mapping OpenAlgo API Request https://openalgo.in/docs
#Mapping Upstox Broking Parameters https://dhanhq.co/docs/v1/orders/

def transform_data(data,token):
    """
    Transforms the new API request structure to the current expected structure.
    """
    drv_expiry_date = None
    drv_options_type = None
    drv_strike_price = None



    # Basic mapping
    transformed = {
        "dhanClientId": data["apikey"],
        "correlationId":None,
        "transactionType": data['action'].upper(),
        "exchangeSegment": map_exchange_type(data["exchange"]),
        "productType": map_product_type(data["product"]),
        "orderType": map_order_type(data["pricetype"]),
        "validity":"DAY",
        "securityId": token,
        "quantity": int(data["quantity"]),
        "disclosedQuantity": int(data.get("disclosed_quantity", 0)),

        "price": float(data.get("price", 0)),
        "afterMarketOrder": False,
        "boProfitValue": None,
        "boStopLossValue": None,
        "drvExpiryDate": drv_expiry_date,  
        "drvOptionType": drv_options_type,
        "drvStrikePrice": drv_strike_price  # Assuming false as default; you might need logic to handle this if it can vary
    }


    # Extended mapping for fields that might need conditional logic or additional processing
    transformed["disclosed_quantity"] = data.get("disclosed_quantity", "0")
    transformed["trigger_price"] = data.get("trigger_price", "0")
    
    return transformed


def transform_modify_order_data(data):
    return {
        "dhanClientId": data["apikey"],
        "orderId": data["orderid"],
        "orderType": map_order_type(data["pricetype"]),
        "legName":"ENTRY_LEG",
        "quantity": data["quantity"],
        "price": data["price"],
        "disclosedQuantity": data.get("disclosed_quantity", "0"),
        "triggerPrice": data.get("trigger_price", "0"),
        "validity": "DAY"

    }



def map_order_type(pricetype):
    """
    Maps the new pricetype to the existing order type.
    """
    order_type_mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "STOP_LOSS",
        "SL-M": "STOP_LOSS_MARKET"
    }
    return order_type_mapping.get(pricetype, "MARKET")  # Default to MARKET if not found



def map_exchange_type(exchange):
    """
    Maps the Broker Exchange to the OpenAlgo Exchange.
    """
    exchange_mapping = {
        "NSE": "NSE_EQ",
        "BSE": "BSE_EQ",
        "CDS": "NSE_CURRENCY",
        "NFO": "NSE_FNO",
        "BFO": "BSE_FNO",
        "BCD": "BSE_CURRENCY",
        "MCX": "MCX_COMM"

    }
    return exchange_mapping.get(exchange)  # Default to MARKET if not found



def map_exchange(brexchange):
    """
    Maps the Broker Exchange to the OpenAlgo Exchange.
    """
    exchange_mapping = {
        "NSE_EQ": "NSE",
        "BSE_EQ": "BSE",
        "NSE_CURRENCY": "CDS",
        "NSE_FNO": "NFO",
        "BSE_FNO": "BFO",
        "BSE_CURRENCY": "BCD",
        "MCX_COMM": "MCX"

    }
    return exchange_mapping.get(brexchange)  # Default to MARKET if not found



def map_product_type(product):
    """
    Maps the new product type to the existing product type.
    """
    product_type_mapping = {
        "CNC": "CNC",
        "NRML": "MARGIN",
        "MIS": "INTRADAY",
    }
    return product_type_mapping.get(product, "INTRADAY")  # Default to INTRADAY if not found

def reverse_map_product_type(product):
    """
    Reverse maps the broker product type to the OpenAlgo product type, considering the exchange.
    """
    # Exchange to OpenAlgo product type mapping for 'D'
    product_mapping = {
        "CNC": "CNC",
        "MARGIN": "NRML",
        "MIS": "INTRADAY"
    }
    
    return product_mapping.get(product)  # Removed default; will return None if not found
