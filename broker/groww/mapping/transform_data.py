#Mapping OpenAlgo API Request https://openalgo.in/docs
#Mapping Groww API Parameters based on SDK documentation

# Groww API constants based on the SDK documentation

# Validity types
VALIDITY_DAY = "DAY"
VALIDITY_IOC = "IOC"

# Exchange types
EXCHANGE_NSE = "NSE"
EXCHANGE_BSE = "BSE"

# Segment types
SEGMENT_CASH = "CASH"
SEGMENT_FNO = "FNO"


# Product types
PRODUCT_CNC = "CNC"
PRODUCT_MIS = "MIS"
PRODUCT_NRML = "NRML"

# Order types
ORDER_TYPE_MARKET = "MARKET"
ORDER_TYPE_LIMIT = "LIMIT"
ORDER_TYPE_SL = "STOP_LOSS_LIMIT"
ORDER_TYPE_SLM = "STOP_LOSS_MARKET"

# Transaction types
TRANSACTION_TYPE_BUY = "BUY"
TRANSACTION_TYPE_SELL = "SELL"

# Order status
ORDER_STATUS_NEW = "NEW"
ORDER_STATUS_ACKED = "ACKED"
ORDER_STATUS_TRIGGER_PENDING = "TRIGGER_PENDING"
ORDER_STATUS_APPROVED = "APPROVED"
ORDER_STATUS_FAILED = "FAILED"
ORDER_STATUS_EXECUTED = "EXECUTED"
ORDER_STATUS_DELIVERY_AWAITED = "DELIVERY_AWAITED"
ORDER_STATUS_CANCELLED = "CANCELLED"
ORDER_STATUS_CANCELLATION_REQUESTED = "CANCELLATION_REQUESTED"
ORDER_STATUS_MODIFICATION_REQUESTED = "MODIFICATION_REQUESTED"
ORDER_STATUS_COMPLETED = "COMPLETED"
ORDER_STATUS_REJECTED = "REJECTED"

def transform_data(data, token):
    """
    Transforms the OpenAlgo API request structure to Groww API structure.
    
    Parameters required by Groww:
    - trading_symbol (required): string - Trading Symbol of the instrument as defined by the exchange
    - quantity (required): int - Quantity of stocks to order
    - price: float - Price of the stock in rupees case of Limit order
    - trigger_price: float - Trigger price in rupees for the order
    - validity (required): string - Validity of the order
    - exchange (required): string - Stock exchange
    - segment (required): string - Segment
    - product (required): string - Product type
    - order_type (required): string - Enumeration of order types
    - transaction_type (required): string - Type of the trade
    - order_reference_id: string - User provided 8 digit reference id
    """
    # Get the symbol (may need to use broker format if the token mapping is used)
    trading_symbol = data.get("symbol", "")
    
    # Basic mapping to Groww API format
    transformed = {
        "trading_symbol": trading_symbol,
        "quantity": int(data["quantity"]),
        "validity": map_validity(data.get("validity", "DAY")),
        "exchange": map_exchange_type(data["exchange"]),
        "segment": map_segment_type(data["exchange"]),
        "product": map_product_type(data["product"]),
        "order_type": map_order_type(data["pricetype"]),
        "transaction_type": map_transaction_type(data["action"]),
    }
    
    # Add price for LIMIT orders
    if data["pricetype"] == "LIMIT":
        transformed["price"] = float(data.get("price", 0))
    
    # Add trigger price for SL and SL-M orders
    if data["pricetype"] in ["SL", "SL-M"]:
        trigger_price = float(data.get("trigger_price", 0))
        if trigger_price <= 0:
            raise ValueError("Trigger price is required for Stop Loss orders")
        transformed["trigger_price"] = trigger_price
    
    # Add order reference id if provided
    if data.get("order_reference_id"):
        transformed["order_reference_id"] = data["order_reference_id"]
    elif data.get("strategy"):
        # Use strategy as reference ID if provided, truncating to 8 chars if needed
        reference_id = data["strategy"][:8].ljust(8, '0')
        transformed["order_reference_id"] = reference_id
    
    return transformed


def transform_modify_order_data(data):
    """
    Transforms the OpenAlgo order modification data to Groww API structure
    
    Args:
        data (dict): Order data in OpenAlgo format
        
    Returns:
        dict: Order data in Groww format
    """
    # Create modification payload
    transformed = {}
    
    # Add fields that can be modified
    if "quantity" in data:
        transformed["quantity"] = int(data["quantity"])
        
    if "pricetype" in data:
        transformed["order_type"] = map_order_type(data["pricetype"])
        
    if "price" in data and data.get("pricetype", "").upper() == "LIMIT":
        transformed["price"] = float(data["price"])
        
    if "trigger_price" in data and data.get("pricetype", "").upper() in ["SL", "SL-M"]:
        transformed["trigger_price"] = float(data["trigger_price"])
        
    if "validity" in data:
        transformed["validity"] = map_validity(data["validity"])
        
    # Order reference ID if present
    if "order_reference_id" in data:
        transformed["order_reference_id"] = data["order_reference_id"]
    
    return transformed


def map_order_type(pricetype):
    """
    Maps the OpenAlgo pricetype to Groww order_type values.
    """
    order_type_mapping = {
        "MARKET": ORDER_TYPE_MARKET,
        "LIMIT": ORDER_TYPE_LIMIT,
        "SL": ORDER_TYPE_SL,
        "SL-M": ORDER_TYPE_SLM
    }
    return order_type_mapping.get(pricetype.upper(), ORDER_TYPE_MARKET)  # Default to MARKET if not found



def map_exchange_type(exchange):
    """
    Maps the OpenAlgo Exchange to Groww Exchange values.
    """
    exchange_mapping = {
        "NSE": EXCHANGE_NSE,
        "BSE": EXCHANGE_BSE,
        "NFO": EXCHANGE_NSE,  # NFO is part of NSE for Groww
        "BFO": EXCHANGE_BSE  # BSE futures & options
    }
    return exchange_mapping.get(exchange.upper(), EXCHANGE_NSE)  # Default to NSE if not found



def map_exchange(brexchange):
    """
    Maps the Groww Exchange to OpenAlgo Exchange format.
    """
    exchange_mapping = {
        EXCHANGE_NSE: "NSE",
        EXCHANGE_BSE: "BSE",
        "NSE_FNO": "NFO",
        "BSE_FNO": "BFO"
    }
    return exchange_mapping.get(brexchange, "NSE")  # Default to NSE if not found



def map_product_type(product):
    """
    Maps the OpenAlgo product type to Groww product type.
    """
    product_type_mapping = {
        "CNC": PRODUCT_CNC,    # Cash and Carry
        "NRML": PRODUCT_NRML,  # Normal delivery
        "MIS": PRODUCT_MIS,    # Intraday
    }
    return product_type_mapping.get(product.upper(), PRODUCT_CNC)  # Default to CNC if not found

def reverse_map_product_type(product):
    """
    Maps the Groww product type to the OpenAlgo product type.
    """
    product_mapping = {
        PRODUCT_CNC: "CNC",
        PRODUCT_NRML: "NRML",
        PRODUCT_MIS: "MIS"
    }
    return product_mapping.get(product)  # Return None if not found

def get_segment(exchange):
    """
    Map exchange to segment type for Groww
    """
    segment_mapping = {
        "NSE": SEGMENT_CASH,
        "BSE": SEGMENT_CASH,
        "NFO": SEGMENT_FNO,
        "BFO": SEGMENT_FNO
    }
    return segment_mapping.get(exchange.upper(), SEGMENT_CASH)  # Default to CASH if not found

def map_segment_type(exchange):
    """
    Maps the OpenAlgo exchange to Groww segment type.
    """
    segment_mapping = {
        "NSE": SEGMENT_CASH,
        "BSE": SEGMENT_CASH,
        "NFO": SEGMENT_FNO,
        "BFO": SEGMENT_FNO
    }
    return segment_mapping.get(exchange.upper(), SEGMENT_CASH)  # Default to CASH if not found

def map_validity(validity):
    """
    Maps OpenAlgo validity to Groww validity type.
    """
    validity_mapping = {
        "DAY": VALIDITY_DAY,
        "IOC": VALIDITY_IOC,
        "GTC": VALIDITY_DAY  # Groww doesn't support GTC, defaulting to DAY
    }
    return validity_mapping.get(validity.upper(), VALIDITY_DAY)  # Default to DAY if not found

def map_transaction_type(action):
    """
    Maps OpenAlgo action to Groww transaction_type.
    """
    transaction_type_mapping = {
        "BUY": TRANSACTION_TYPE_BUY,
        "SELL": TRANSACTION_TYPE_SELL
    }
    return transaction_type_mapping.get(action.upper(), TRANSACTION_TYPE_BUY)  # Default to BUY if not found
