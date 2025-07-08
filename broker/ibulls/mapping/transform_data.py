#Mapping OpenAlgo API Request https://openalgo.in/docs
#Mapping ibullssecurities Broking Parameters https://symphonyfintech.com/xts-trading-front-end-api/

from database.token_db import get_br_symbol,get_token
from utils.logging import get_logger
from broker.ibulls.api.data import BrokerData
from flask import session
from database.auth_db import get_auth_token, get_feed_token

logger = get_logger(__name__)


def transform_data(data, token):
    """
    Transforms the new API request structure to the current expected structure.
    For market orders, fetches quotes and adjusts price accordingly:
    - BUY: Uses bid price + 0.1%
    - SELL: Uses ask price + 0.1%
    """
    symbol = get_br_symbol(data['symbol'], data['exchange'])
    
    # Check if market order and convert to limit order with adjusted price
    order_type = map_order_type(data["pricetype"])
    price = data.get("price", "0")
    action = data['action'].upper()
    
    if data["pricetype"] == "MARKET":
        try:
            # Get username from Flask session
            username = None
            if session and hasattr(session, 'get'):
                username = session.get('username')
            
            # Get feed token for market data using username (not broker name)
            feed_token = get_feed_token(username if username else "kalaivani")
            
            logger.info(f"Using feed token for user: {username if username else 'kalaivani'}")
            
            if feed_token:
                # Create BrokerData instance to use get_quotes - only need feed_token for market data
                broker_data = BrokerData(feed_token, feed_token)
                
                # Fetch quotes for the symbol
                quote_data = broker_data.get_quotes(data['symbol'], data['exchange'])
                logger.info(f"Quote data for market order adjustment: {quote_data}")
                
                # Adjust price based on action (BUY or SELL)
                if action == "BUY":
                    bid_price = float(quote_data.get('bid', 0))
                    if bid_price > 0:
                        # Add 0.1% to bid price for BUY orders
                        adjusted_price = bid_price * 1.001
                        price = str(round(adjusted_price, 2))
                        logger.info(f"Adjusted BUY price: bid {bid_price} + 0.1% = {price}")
                        # Change order type to LIMIT
                        order_type = "LIMIT"
                elif action == "SELL":
                    ask_price = float(quote_data.get('ask', 0))
                    if ask_price > 0:
                        # Subtract 0.1% from ask price for SELL orders
                        adjusted_price = ask_price * 0.999
                        price = str(round(adjusted_price, 2))
                        logger.info(f"Adjusted SELL price: ask {ask_price} - 0.1% = {price}")
                        # Change order type to LIMIT
                        order_type = "LIMIT"
            else:
                logger.warning("No feed token available, cannot fetch quotes for market order price adjustment")
        except Exception as e:
            logger.error(f"Error adjusting market order price: {str(e)}. Proceeding with regular market order.")
    
    # Basic mapping
    transformed = {
        "exchangeSegment": map_exchange(data['exchange']),
        "exchangeInstrumentID": token,
        "productType": map_product_type(data["product"]),
        "orderType": order_type,
        "orderSide": action,
        "timeInForce": "DAY",
        "disclosedQuantity": data.get("disclosed_quantity", "0"),
        "orderQuantity": data["quantity"],
        "limitPrice": price,
        "stopPrice": data.get("trigger_price", "0"),
        "orderUniqueIdentifier": "openalgo"
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
        "orderUniqueIdentifier": "openalgo"
    }

def map_exchange(exchange):
    """
    Maps the new exchange to the existing exchange.
    """
    exchange_mapping = {
        "NSE": "NSECM",
        "BSE": "BSECM",
        "MCX": "MCXFO",
        "NFO": "NSEFO",
        "BFO": "BSEFO",
        "CDS": "NSECD",
        "EXCHANGE": "EXCHANGE"
    }
    return exchange_mapping.get(exchange, "EXCHANGE")



def map_order_type(pricetype):
    """
    Maps the new pricetype to the existing order type.
    """
    order_type_mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "SL-L",
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
    return product_type_mapping.get(product, "MIS")  # Default to INTRADAY if not found

def reverse_map_product_type(exchange,product):
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