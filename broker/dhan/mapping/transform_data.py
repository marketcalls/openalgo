#Mapping OpenAlgo API Request https://openalgo.in/docs
#Mapping Upstox Broking Parameters https://dhanhq.co/docs/v2/orders/

def transform_data(data,token):
    """
    Transforms the OpenAlgo API request structure to Dhan v2 API structure.
    Based on the exact structure from Dhan documentation.
    """
    # Build payload exactly as shown in Dhan documentation
    transformed = {
        "dhanClientId": data.get("dhan_client_id", data["apikey"]),
        "correlationId": "",  # Empty as shown in docs
        "transactionType": data["action"].upper(),
        "exchangeSegment": map_exchange_type(data["exchange"]),
        "productType": map_product_type(data["product"]),
        "orderType": map_order_type(data["pricetype"]),
        "validity": "DAY",
        "securityId": token,
        "quantity": str(int(data["quantity"])),
        "disclosedQuantity": "",
        "price": "",
        "triggerPrice": "",
        "afterMarketOrder": False,
        "amoTime": "",
        "boProfitValue": "",
        "boStopLossValue": ""
    }

    # Set price for non-market orders
    if data["pricetype"] != "MARKET":
        price = float(data.get("price", 0))
        transformed["price"] = str(price)

    # Set disclosed quantity if provided
    disclosed_qty = int(data.get("disclosed_quantity", 0))
    if disclosed_qty > 0:
        transformed["disclosedQuantity"] = str(disclosed_qty)

    # Set trigger price for SL orders
    if data["pricetype"] in ["SL", "SL-M"]:
        trigger_price = float(data.get("trigger_price", 0))
        if trigger_price > 0:
            transformed["triggerPrice"] = str(trigger_price)
        else:
            raise ValueError("Trigger price is required for Stop Loss orders")

    # Set correlation ID if provided
    correlation_id = data.get("correlation_id")
    if correlation_id:
        transformed["correlationId"] = correlation_id

    # Handle after market orders
    if data.get("after_market_order", False):
        transformed["afterMarketOrder"] = True
        amo_time = data.get("amo_time", "")
        if amo_time in ["PRE_OPEN", "OPEN", "OPEN_30", "OPEN_60"]:
            transformed["amoTime"] = amo_time

    # Handle bracket order values
    if data.get("product") == "BO":
        bo_profit = data.get("bo_profit_value")
        bo_stop_loss = data.get("bo_stop_loss_value")
        if bo_profit:
            transformed["boProfitValue"] = str(bo_profit)
        if bo_stop_loss:
            transformed["boStopLossValue"] = str(bo_stop_loss)

    # Handle IOC validity
    if data.get("validity") == "IOC":
        transformed["validity"] = "IOC"


    return transformed


def transform_modify_order_data(data):
    modified = {
        "dhanClientId": data.get("dhan_client_id", data["apikey"]),  # Use provided client_id or fallback to apikey
        "orderId": data["orderid"],
        "orderType": map_order_type(data["pricetype"]),
        "legName":"ENTRY_LEG",
        "quantity": str(data["quantity"]),
        "price": str(data["price"]) if data.get("pricetype") != "MARKET" else "",
        "validity": "DAY"
    }

    # Only add optional fields if they have values
    disclosed_qty = int(data.get("disclosed_quantity", 0))
    if disclosed_qty > 0:
        modified["disclosedQuantity"] = str(disclosed_qty)
    else:
        modified["disclosedQuantity"] = ""

    # Handle trigger price for SL orders
    if data["pricetype"] in ["SL", "SL-M"]:
        trigger_price = float(data.get("trigger_price", 0))
        if trigger_price > 0:
            modified["triggerPrice"] = str(trigger_price)
        else:
            modified["triggerPrice"] = ""
    else:
        modified["triggerPrice"] = ""

    return modified


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
