#Mapping OpenAlgo API Request https://openalgo.in/docs
#Mapping Firstock API Parameters https://connect.thefirstock.com/api/V4/placeOrder

from database.token_db import get_br_symbol
import html

def transform_data(data,token):
    """
    Transforms the OpenAlgo API request structure to Firstock's expected structure.
    
    OpenAlgo format:
    {
        "apikey": "...",
        "strategy": "...",
        "exchange": "NSE",
        "symbol": "M&M",
        "action": "buy",
        "product": "MIS",
        "pricetype": "MARKET",
        "quantity": "100",
        "price": "0",
        "trigger_price": "0"
    }
    
    Firstock format:
    {
        "userId": "...",
        "exchange": "NSE",
        "tradingSymbol": "ITC-EQ",
        "quantity": "250",
        "price": "413",
        "product": "C",
        "transactionType": "B",
        "priceType": "LMT",
        "retention": "DAY",
        "triggerPrice": "0",
        "remarks": "Place Order"
    }
    """
    userid = data["apikey"]
    userid = userid[:-4]  # Remove last 4 characters
    
    # Get broker symbol and handle special characters
    symbol = get_br_symbol(data["symbol"], data["exchange"])
    if symbol and '&' in symbol:
        symbol = symbol.replace('&', '%26')
    
    # Convert action to transactionType (case insensitive)
    transaction_type = 'B' if data["action"].upper() == "BUY" else 'S'
    
    # Basic mapping
    transformed = {
        "userId": userid,
        "exchange": data["exchange"],
        "tradingSymbol": symbol,
        "quantity": str(data["quantity"]),
        "price": str(data.get("price", "0")),
        "triggerPrice": str(data.get("trigger_price", "0")),
        "product": map_product_type(data["product"]),
        "transactionType": transaction_type,
        "priceType": map_order_type(data["pricetype"]),
        "retention": "DAY",
        "remarks": data.get("strategy", "Place Order")  # Use strategy name as remarks if available
    }
    
    return transformed


def transform_modify_order_data(data, token):
    """
    Transform modify order data to Firstock's format
    
    Firstock format:
    {
        "userId": "AA0013",
        "orderNumber": "1234567890111",
        "price": "240",
        "quantity": "1",
        "triggerPrice": "235",
        "exchange": "NSE",
        "tradingSymbol": "ITC-EQ",
        "priceType": "LMT"
    }
    """
    # Handle special characters in symbol
    symbol = data["symbol"]
    if '&' in symbol:
        symbol = symbol.replace('&', '%26')
        
    return {
        "exchange": data["exchange"],
        "orderNumber": data["orderid"],
        "priceType": map_order_type(data["pricetype"]),
        "price": str(data["price"]),
        "quantity": str(data["quantity"]),
        "tradingSymbol": symbol,
        "triggerPrice": str(data.get("trigger_price", "0"))
    }



def map_order_type(pricetype):
    """
    Maps the OpenAlgo pricetype to Firstock's order type.
    """
    order_type_mapping = {
        "MARKET": "MKT",
        "LIMIT": "LMT",
        "SL": "SL-LMT",
        "SL-M": "SL-MKT"
    }
    return order_type_mapping.get(pricetype, "MKT")  # Default to MKT if not found

def map_product_type(product):
    """
    Maps the OpenAlgo product type to Firstock's product type.
    """
    product_type_mapping = {
        "CNC": "C",
        "NRML": "M",
        "MIS": "I"
    }
    return product_type_mapping.get(product, "I")  # Default to I (MIS) if not found



def reverse_map_product_type(product):
    """
    Maps Firstock's product type to OpenAlgo product type.
    """
    reverse_product_type_mapping = {
        "C": "CNC",
        "M": "NRML",
        "I": "MIS"
    }
    return reverse_product_type_mapping.get(product, "MIS")  # Default to MIS if not found
