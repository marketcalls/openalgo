#Mapping OpenAlgo API Request https://openalgo.in/docs
#Mapping IndStocks API Parameters https://api.indstocks.com/

def transform_data(data, token):
    """
    Transforms the OpenAlgo API request structure to IndStocks API structure.
    
    Parameters required by IndStocks API:
    - txn_type (required): BUY/SELL
    - exchange (required): NSE/BSE
    - segment (required): DERIVATIVE/EQUITY
    - product (required): MARGIN/INTRADAY/CNC
    - order_type (required): LIMIT/MARKET
    - validity (required): DAY/IOC
    - security_id (required): string
    - qty (required): integer
    - is_amo: boolean (for after market orders)
    - limit_price: float (required for LIMIT orders)
    """
    # Basic mapping from OpenAlgo to IndStocks
    segment = map_segment(data["exchange"])
    transformed = {
        "txn_type": data["action"].upper(),  # BUY/SELL
        "exchange": data["exchange"].upper(),  # NSE/BSE
        "segment": segment,  # DERIVATIVE/EQUITY
        "product": map_product_type(data["product"]),  # MARGIN/INTRADAY/CNC
        "order_type": map_order_type(data["pricetype"]),  # LIMIT/MARKET
        "validity": "DAY",  # Default to DAY
        "security_id": token,  # Security ID from token
        "qty": int(data["quantity"]),  # Order quantity
        "is_amo": data.get("is_amo", False)  # After market order flag
    }
    
    # Log the segment mapping for debugging
    print(f"Exchange: {data['exchange']}, Mapped Segment: {segment}")
    print(f"Order Type: {data.get('pricetype')} -> {transformed['order_type']}")
    
    # Add limit_price for LIMIT orders
    if data.get("pricetype") == "LIMIT" and data.get("price"):
        transformed["limit_price"] = float(data["price"])
    elif transformed["order_type"] == "limit":
        # For LIMIT orders, price is required
        transformed["limit_price"] = float(data.get("price", 0))
    
    # Handle validity if specified
    if data.get("validity") == "IOC":
        transformed["validity"] = "IOC"
    
    # For equity orders, ensure we have all required fields
    if transformed["segment"] == "EQUITY":
        # Ensure limit_price is set for LIMIT orders
        if transformed["order_type"] == "limit" and "limit_price" not in transformed:
            transformed["limit_price"] = float(data.get("price", 0))
    
    return transformed


def transform_modify_order_data(data):
    """
    Transforms OpenAlgo modify order data to IndStocks format.
    """
    transformed = {
        "segment": map_segment_from_orderid(data.get("orderid", "")),  # Derive from order ID
        "order_id": data["orderid"],
        "qty": int(data["quantity"]),
        "limit_price": float(data.get("price", 0))
    }
    
    return transformed


def map_order_type(pricetype):
    """
    Maps OpenAlgo pricetype to IndStocks order_type.
    """
    order_type_mapping = {
        "MARKET": "MARKET",
        "LIMIT": "limit",
        "SL": "limit",  # Stop loss as limit order
        "SL-M": "MARKET"  # Stop loss market as market order
    }
    return order_type_mapping.get(pricetype, "MARKET")


def map_segment(exchange):
    """
    Maps OpenAlgo exchange to IndStocks segment.
    """
    segment_mapping = {
        "NSE": "EQUITY",
        "BSE": "EQUITY", 
        "NFO": "DERIVATIVE",
        "BFO": "DERIVATIVE",
        "CDS": "DERIVATIVE",
        "BCD": "DERIVATIVE",
        "MCX": "DERIVATIVE"
    }
    result = segment_mapping.get(exchange, "EQUITY")
    print(f"map_segment: {exchange} -> {result}")
    return result


def map_segment_from_orderid(orderid):
    """
    Maps order ID prefix to segment for modify/cancel operations.
    """
    if orderid.startswith("DRV-"):
        return "DERIVATIVE"
    else:
        return "EQUITY"


def map_exchange_type(exchange):
    """
    Maps OpenAlgo exchange to IndStocks exchange format.
    """
    exchange_mapping = {
        "NSE": "NSE",
        "BSE": "BSE",
        "NFO": "NSE",
        "BFO": "BSE",
        "CDS": "NSE",
        "BCD": "BSE",
        "MCX": "MCX"
    }
    return exchange_mapping.get(exchange, "NSE")


def map_exchange(br_exchange):
    """
    Maps IndStocks exchange back to OpenAlgo exchange.
    """
    exchange_mapping = {
        "NSE": "NSE",
        "BSE": "BSE",
        "MCX": "MCX"
    }
    return exchange_mapping.get(br_exchange, "NSE")


def map_product_type(product):
    """
    Maps OpenAlgo product type to IndStocks product type.
    """
    product_type_mapping = {
        "CNC": "CNC",
        "NRML": "MARGIN",
        "MIS": "INTRADAY",
    }
    return product_type_mapping.get(product, "INTRADAY")


def reverse_map_product_type(product):
    """
    Maps IndStocks product type back to OpenAlgo product type.
    """
    product_mapping = {
        "CNC": "CNC",
        "MARGIN": "NRML",
        "INTRADAY": "MIS"
    }
    return product_mapping.get(product, "MIS")
