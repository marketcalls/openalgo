from mcp.server.fastmcp import FastMCP
from openalgo import api
from typing import List, Dict, Any, Optional
import json


api_key = 'you-openalgo-apikey'
client = api(api_key=api_key, host='http://127.0.0.1:5000')

# Create MCP server
mcp = FastMCP("openalgo")

# ORDER MANAGEMENT TOOLS

@mcp.tool()
def place_order(
    symbol: str, 
    quantity: int, 
    action: str, 
    exchange: str = "NSE", 
    price_type: str = "MARKET", 
    product: str = "MIS", 
    strategy: str = "Python",
    price: Optional[float] = None,
    trigger_price: Optional[float] = None,
    disclosed_quantity: Optional[int] = None
) -> str:
    """
    Place a new order (market or limit).
    
    Args:
        symbol: Stock symbol (e.g., 'RELIANCE')
        quantity: Number of shares
        action: 'BUY' or 'SELL'
        exchange: 'NSE', 'NFO', 'CDS', 'BSE', 'BFO', 'BCD', 'MCX', 'NCDEX'
        price_type: 'MARKET', 'LIMIT', 'SL', 'SL-M'
        product: 'CNC', 'NRML', 'MIS'
        strategy: Strategy name
        price: Limit price (required for LIMIT orders)
        trigger_price: Trigger price (for stop loss orders)
        disclosed_quantity: Disclosed quantity
    """
    try:
        params = {
            "strategy": strategy,
            "symbol": symbol.upper(),
            "action": action.upper(),
            "exchange": exchange.upper(),
            "price_type": price_type.upper(),
            "product": product.upper(),
            "quantity": quantity
        }
        
        if price is not None:
            params["price"] = price
        if trigger_price is not None:
            params["trigger_price"] = trigger_price
        if disclosed_quantity is not None:
            params["disclosed_quantity"] = disclosed_quantity
            
        response = client.placeorder(**params)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error placing order: {str(e)}"

@mcp.tool()
def place_smart_order(
    symbol: str, 
    quantity: int, 
    action: str, 
    position_size: int,
    exchange: str = "NSE", 
    price_type: str = "MARKET", 
    product: str = "MIS", 
    strategy: str = "Python",
    price: Optional[float] = None
) -> str:
    """
    Place a smart order considering current position size.
    
    Args:
        symbol: Stock symbol
        quantity: Number of shares
        action: 'BUY' or 'SELL'
        position_size: Current position size
        exchange: Exchange name
        price_type: Order type
        product: Product type
        strategy: Strategy name
        price: Limit price (optional)
    """
    try:
        params = {
            "strategy": strategy,
            "symbol": symbol.upper(),
            "action": action.upper(),
            "exchange": exchange.upper(),
            "price_type": price_type.upper(),
            "product": product.upper(),
            "quantity": quantity,
            "position_size": position_size
        }
        
        if price is not None:
            params["price"] = price
            
        response = client.placesmartorder(**params)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error placing smart order: {str(e)}"

@mcp.tool()
def place_basket_order(orders_json: str) -> str:
    """
    Place multiple orders in a basket.
    
    Args:
        orders_json: JSON string containing list of orders
        Example: '[{"symbol": "BHEL", "exchange": "NSE", "action": "BUY", "quantity": 1, "pricetype": "MARKET", "product": "MIS"}]'
    """
    try:
        orders = json.loads(orders_json)
        response = client.basketorder(orders=orders)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error placing basket order: {str(e)}"

@mcp.tool()
def place_split_order(
    symbol: str,
    quantity: int,
    split_size: int,
    action: str,
    exchange: str = "NSE",
    price_type: str = "MARKET",
    product: str = "MIS",
    price: Optional[float] = None
) -> str:
    """
    Place an order split into smaller chunks.
    
    Args:
        symbol: Stock symbol
        quantity: Total quantity to trade
        split_size: Size of each split order
        action: 'BUY' or 'SELL'
        exchange: Exchange name
        price_type: Order type
        product: Product type
        price: Limit price (optional)
    """
    try:
        params = {
            "symbol": symbol.upper(),
            "exchange": exchange.upper(),
            "action": action.upper(),
            "quantity": quantity,
            "splitsize": split_size,
            "price_type": price_type.upper(),
            "product": product.upper()
        }
        
        if price is not None:
            params["price"] = price
            
        response = client.splitorder(**params)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error placing split order: {str(e)}"

@mcp.tool()
def modify_order(
    order_id: str,
    strategy: str,
    symbol: str,
    action: str,
    exchange: str,
    price_type: str,
    product: str,
    quantity: int,
    price: Optional[float] = None
) -> str:
    """
    Modify an existing order.
    
    Args:
        order_id: Order ID to modify
        strategy: Strategy name
        symbol: Stock symbol
        action: 'BUY' or 'SELL'
        exchange: Exchange name
        price_type: Order type
        product: Product type
        quantity: New quantity
        price: New price (optional)
    """
    try:
        params = {
            "order_id": order_id,
            "strategy": strategy,
            "symbol": symbol.upper(),
            "action": action.upper(),
            "exchange": exchange.upper(),
            "price_type": price_type.upper(),
            "product": product.upper(),
            "quantity": quantity
        }
        
        if price is not None:
            params["price"] = price
            
        response = client.modifyorder(**params)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error modifying order: {str(e)}"

@mcp.tool()
def cancel_order(order_id: str, strategy: str) -> str:
    """
    Cancel a specific order.
    
    Args:
        order_id: Order ID to cancel
        strategy: Strategy name
    """
    try:
        response = client.cancelorder(order_id=order_id, strategy=strategy)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error canceling order: {str(e)}"

@mcp.tool()
def cancel_all_orders(strategy: str) -> str:
    """
    Cancel all open orders for a strategy.
    
    Args:
        strategy: Strategy name
    """
    try:
        response = client.cancelallorder(strategy=strategy)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error canceling all orders: {str(e)}"

# POSITION MANAGEMENT TOOLS

@mcp.tool()
def close_all_positions(strategy: str) -> str:
    """
    Close all open positions for a strategy.
    
    Args:
        strategy: Strategy name
    """
    try:
        response = client.closeposition(strategy=strategy)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error closing positions: {str(e)}"

@mcp.tool()
def get_open_position(strategy: str, symbol: str, exchange: str, product: str) -> str:
    """
    Get current open position for a specific instrument.
    
    Args:
        strategy: Strategy name
        symbol: Stock symbol
        exchange: Exchange name
        product: Product type
    """
    try:
        response = client.openposition(
            strategy=strategy,
            symbol=symbol.upper(),
            exchange=exchange.upper(),
            product=product.upper()
        )
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting open position: {str(e)}"

# ORDER STATUS AND TRACKING TOOLS

@mcp.tool()
def get_order_status(order_id: str, strategy: str) -> str:
    """
    Get status of a specific order.
    
    Args:
        order_id: Order ID
        strategy: Strategy name
    """
    try:
        response = client.orderstatus(order_id=order_id, strategy=strategy)
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting order status: {str(e)}"

@mcp.tool()
def get_order_book() -> str:
    """Get all orders from the order book."""
    try:
        response = client.orderbook()
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting order book: {str(e)}"

@mcp.tool()
def get_trade_book() -> str:
    """Get all executed trades."""
    try:
        response = client.tradebook()
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting trade book: {str(e)}"

@mcp.tool()
def get_position_book() -> str:
    """Get all current positions."""
    try:
        response = client.positionbook()
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting position book: {str(e)}"

@mcp.tool()
def get_holdings() -> str:
    """Get all holdings (long-term investments)."""
    try:
        response = client.holdings()
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting holdings: {str(e)}"

@mcp.tool()
def get_funds() -> str:
    """Get account funds and margin information."""
    try:
        response = client.funds()
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting funds: {str(e)}"

# MARKET DATA TOOLS

@mcp.tool()
def get_quote(symbol: str, exchange: str = "NSE") -> str:
    """
    Get current quote for a symbol.
    
    Args:
        symbol: Stock symbol
        exchange: Exchange name
    """
    try:
        response = client.quotes(symbol=symbol.upper(), exchange=exchange.upper())
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting quote: {str(e)}"

@mcp.tool()
def get_market_depth(symbol: str, exchange: str = "NSE") -> str:
    """
    Get market depth (order book) for a symbol.
    
    Args:
        symbol: Stock symbol
        exchange: Exchange name
    """
    try:
        response = client.depth(symbol=symbol.upper(), exchange=exchange.upper())
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting market depth: {str(e)}"

@mcp.tool()
def get_historical_data(
    symbol: str,
    exchange: str,
    interval: str,
    start_date: str,
    end_date: str
) -> str:
    """
    Get historical price data.
    
    Args:
        symbol: Stock symbol
        exchange: Exchange name
        interval: Time interval ('1m', '3m', '5m', '10m', '15m', '30m', '1h', 'D')
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
    """
    try:
        response = client.history(
            symbol=symbol.upper(),
            exchange=exchange.upper(),
            interval=interval,
            start_date=start_date,
            end_date=end_date
        )
        return str(response)  # DataFrame converted to string
    except Exception as e:
        return f"Error getting historical data: {str(e)}"

# INSTRUMENT SEARCH AND INFO TOOLS

@mcp.tool()
def search_instruments(query: str, exchange: str = "NSE") -> str:
    """
    Search for instruments by name or symbol.
    
    Args:
        query: Search query
        exchange: Exchange to search in
    """
    try:
        response = client.search(query=query, exchange=exchange.upper())
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error searching instruments: {str(e)}"

@mcp.tool()
def get_symbol_info(symbol: str, exchange: str = "NSE") -> str:
    """
    Get detailed information about a symbol.
    
    Args:
        symbol: Stock symbol
        exchange: Exchange name
    """
    try:
        response = client.symbol(symbol=symbol.upper(), exchange=exchange.upper())
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting symbol info: {str(e)}"

@mcp.tool()
def get_expiry_dates(symbol: str, exchange: str = "NFO", instrument_type: str = "options") -> str:
    """
    Get expiry dates for derivatives.
    
    Args:
        symbol: Underlying symbol
        exchange: Exchange name (typically NFO for F&O)
        instrument_type: 'options' or 'futures'
    """
    try:
        response = client.expiry(
            symbol=symbol.upper(),
            exchange=exchange.upper(),
            instrumenttype=instrument_type.lower()
        )
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting expiry dates: {str(e)}"

@mcp.tool()
def get_available_intervals() -> str:
    """Get all available time intervals for historical data."""
    try:
        response = client.intervals()
        return json.dumps(response, indent=2)
    except Exception as e:
        return f"Error getting intervals: {str(e)}"

# UTILITY TOOLS

@mcp.tool()
def get_openalgo_version() -> str:
    """Get the OpenAlgo library version."""
    try:
        import openalgo
        return f"OpenAlgo version: {openalgo.__version__}"
    except Exception as e:
        return f"Error getting version: {str(e)}"

@mcp.tool()
def validate_order_constants() -> str:
    """Display all valid order constants for reference."""
    constants = {
        "exchanges": {
            "NSE": "NSE Equity",
            "NFO": "NSE Futures & Options", 
            "CDS": "NSE Currency",
            "BSE": "BSE Equity",
            "BFO": "BSE Futures & Options",
            "BCD": "BSE Currency", 
            "MCX": "MCX Commodity",
            "NCDEX": "NCDEX Commodity"
        },
        "product_types": {
            "CNC": "Cash & Carry for equity",
            "NRML": "Normal for futures and options", 
            "MIS": "Intraday Square off"
        },
        "price_types": {
            "MARKET": "Market Order",
            "LIMIT": "Limit Order",
            "SL": "Stop Loss Limit Order",
            "SL-M": "Stop Loss Market Order"
        },
        "actions": {
            "BUY": "Buy",
            "SELL": "Sell"
        },
        "intervals": ["1m", "3m", "5m", "10m", "15m", "30m", "1h", "D"]
    }
    return json.dumps(constants, indent=2)

if __name__ == "__main__":
    mcp.run(transport='stdio')