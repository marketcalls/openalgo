#Mapping OpenAlgo API Request https://openalgo.in/docs
#Mapping Indmoney API Parameters https://api.indstocks.com/

from database.token_db import get_br_symbol,get_token
from utils.logging import get_logger
from broker.indmoney.api.data import BrokerData
from flask import session
from database.auth_db import get_auth_token, get_feed_token

logger = get_logger(__name__)

def transform_data(data, token):
    """
    Transforms the OpenAlgo API request structure to Indmoney API structure.
    For market orders, fetches quotes and adjusts price accordingly:
    - BUY: Uses bid price + 0.1%
    - SELL: Uses ask price - 0.1%
    
    Parameters required by Indmoney API:
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
    symbol = get_br_symbol(data['symbol'], data['exchange'])
    
    # Check if market order and convert to limit order with adjusted price
    order_type = map_order_type(data["pricetype"])
    price = data.get("price", "0")
    action = data['action'].upper()
    
    if data["pricetype"] == "MARKET":
        # Get username from Flask session
        username = None
        if session and hasattr(session, 'get'):
            username = session.get('username')
        
        # Get auth token for market data using username
        auth_token = get_auth_token(username if username else "kalaivani")
        
        logger.info(f"Using auth token for user: {username if username else 'kalaivani'}")
        
        # Create BrokerData instance to use get_quotes - only need auth_token
        broker_data = BrokerData(auth_token)
        
        # Fetch quotes for the symbol
        quote_data = broker_data.get_quotes(data['symbol'], data['exchange'])
        logger.info(f"Quote data for market order adjustment: {quote_data}")
        
        # Adjust price based on action (BUY or SELL) using LTP
        ltp = float(quote_data.get('ltp', 0))
        if action == "BUY":
            # Add 0.1% to LTP for BUY orders
            adjusted_price = ltp * 1.001
            price = str(round(adjusted_price, 2))
            logger.info(f"Adjusted BUY price: LTP {ltp} + 0.1% = {price}")
            # Change order type to LIMIT
            order_type = "limit"
        elif action == "SELL":
            # Subtract 0.1% from LTP for SELL orders
            adjusted_price = ltp * 0.999
            price = str(round(adjusted_price, 2))
            logger.info(f"Adjusted SELL price: LTP {ltp} - 0.1% = {price}")
            # Change order type to LIMIT
            order_type = "limit"
    
    # Basic mapping from OpenAlgo to Indmoney
    segment = map_segment(data["exchange"])
    transformed = {
        "txn_type": action,  # BUY/SELL
        "exchange": data["exchange"].upper(),  # NSE/BSE
        "segment": segment,  # DERIVATIVE/EQUITY
        "product": map_product_type(data["product"]),  # MARGIN/INTRADAY/CNC
        "order_type": order_type,  # LIMIT/MARKET
        "validity": "DAY",  # Default to DAY
        "security_id": token,  # Security ID from token
        "qty": int(data["quantity"]),  # Order quantity
        "is_amo": data.get("is_amo", False)  # After market order flag
    }
    
    # Log the segment mapping for debugging
    logger.info(f"Exchange: {data['exchange']}, Mapped Segment: {segment}")
    logger.info(f"Order Type: {data.get('pricetype')} -> {transformed['order_type']}")
    
    # Add limit_price for LIMIT orders
    if data.get("pricetype") == "LIMIT" and data.get("price"):
        transformed["limit_price"] = float(data["price"])
    elif transformed["order_type"] == "limit":
        # For LIMIT orders, price is required
        transformed["limit_price"] = float(price if price != "0" else data.get("price", 0))
    
    # Handle validity if specified
    if data.get("validity") == "IOC":
        transformed["validity"] = "IOC"
    
    # For equity orders, ensure we have all required fields
    if transformed["segment"] == "EQUITY":
        # Ensure limit_price is set for LIMIT orders
        if transformed["order_type"] == "limit" and "limit_price" not in transformed:
            transformed["limit_price"] = float(price if price != "0" else data.get("price", 0))
    
    logger.info(f"transformed data: {transformed}")
    return transformed


def transform_modify_order_data(data):
    """
    Transforms OpenAlgo modify order data to Indmoney format.
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
    Maps OpenAlgo pricetype to Indmoney order_type.
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
    Maps OpenAlgo exchange to Indmoney segment.
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
    Maps OpenAlgo exchange to Indmoney exchange format.
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
    Maps Indmoney exchange back to OpenAlgo exchange.
    """
    exchange_mapping = {
        "NSE": "NSE",
        "BSE": "BSE",
        "MCX": "MCX"
    }
    return exchange_mapping.get(br_exchange, "NSE")


def map_product_type(product):
    """
    Maps OpenAlgo product type to Indmoney product type.
    """
    product_type_mapping = {
        "CNC": "CNC",
        "NRML": "MARGIN",
        "MIS": "INTRADAY",
    }
    return product_type_mapping.get(product, "INTRADAY")


def reverse_map_product_type(product):
    """
    Maps Indmoney product type back to OpenAlgo product type.
    """
    product_mapping = {
        "CNC": "CNC",
        "MARGIN": "NRML",
        "INTRADAY": "MIS"
    }
    return product_mapping.get(product, "MIS")
