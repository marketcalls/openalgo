#Mapping OpenAlgo API Request https://openalgo.in/docs
#Mapping Upstox Broking Parameters https://dhanhq.co/docs/v2/orders/

def transform_data(data,token):
    """
    Transforms the OpenAlgo API request structure to Dhan v2 API structure.
    
    Parameters required by Dhan v2:
    - dhanClientId (required): string
    - correlationId: string
    - transactionType (required): BUY/SELL
    - exchangeSegment (required): Exchange segment enum
    - productType (required): Product type enum
    - orderType (required): Order type enum
    - validity (required): DAY/IOC
    - securityId (required): string
    - quantity (required): int
    - disclosedQuantity: int
    - price (required): float
    - triggerPrice: float (required for SL orders)
    - afterMarketOrder: boolean
    - amoTime: string (OPEN/OPEN_30/OPEN_60)
    - boProfitValue: float
    - boStopLossValue: float
    """
    # Basic mapping
    transformed = {
        "dhanClientId": data["apikey"],
        "transactionType": data["action"].upper(),
        "exchangeSegment": map_exchange_type(data["exchange"]),
        "productType": map_product_type(data["product"]),
        "orderType": map_order_type(data["pricetype"]),
        "validity": "DAY",  # Default to DAY, can be overridden if IOC is needed
        "securityId": token,
        "quantity": int(data["quantity"]),
        "disclosedQuantity": int(data.get("disclosed_quantity", 0)),
        "price": float(data.get("price", 0)),
        "triggerPrice": float(data.get("trigger_price", 0)),
        "afterMarketOrder": data.get("after_market_order", False)
    }
    
    # Add correlationId - Dhan API seems to require this field even if optional in docs
    correlation_id = data.get("correlation_id")
    if correlation_id is not None and correlation_id != "":
        transformed["correlationId"] = correlation_id
    else:
        # Use a default correlation ID if not provided
        import uuid
        transformed["correlationId"] = str(uuid.uuid4())[:8]  # Short UUID for tracking
    
    # Handle amoTime - required for after market orders, default for regular orders
    if data.get("after_market_order", False):
        amo_time = data.get("amo_time")
        if amo_time and amo_time in ["OPEN", "OPEN_30", "OPEN_60"]:
            transformed["amoTime"] = amo_time
        else:
            transformed["amoTime"] = "OPEN"  # Default for after market orders
    else:
        # Even for regular orders, Dhan API seems to require amoTime field
        transformed["amoTime"] = "OPEN"
    
    # Add bracket order fields only if they have valid values
    bo_profit = data.get("bo_profit_value")
    if bo_profit is not None and bo_profit != 0:
        transformed["boProfitValue"] = float(bo_profit)
    
    bo_stop_loss = data.get("bo_stop_loss_value")
    if bo_stop_loss is not None and bo_stop_loss != 0:
        transformed["boStopLossValue"] = float(bo_stop_loss)

    # Handle validity for IOC orders if specified
    if data.get("validity") == "IOC":
        transformed["validity"] = "IOC"

    # For SL and SL-M orders, trigger price is required
    if data["pricetype"] in ["SL", "SL-M"] and not transformed["triggerPrice"]:
        raise ValueError("Trigger price is required for Stop Loss orders")


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
