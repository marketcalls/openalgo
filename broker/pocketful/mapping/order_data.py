import json
from database.token_db import get_symbol , get_oa_symbol

def map_order_data(order_data):
    """
    Processes and modifies a list of order dictionaries based on specific conditions.
    Handles different field names in Pocketful API response.
    
    Parameters:
    - order_data: A list of dictionaries, where each dictionary represents an order.
    
    Returns:
    - The modified order_data with updated 'tradingsymbol' and 'product' fields.
    """
    # Check if we have any data
    if not order_data or 'data' not in order_data:
        print("No data available or invalid format.")
        return {}
        
    # Handle Pocketful's response format which might have nested orders
    if isinstance(order_data['data'], dict) and 'orders' in order_data['data']:
        orders = order_data['data']['orders']
    else:
        orders = order_data['data']
    
    if not orders:
        print("No orders found in data.")
        return orders
    
    # Process each order
    for order in orders:
        # Safely extract exchange
        if 'exchange' in order:
            exchange = order['exchange']
        else:
            print(f"Warning: Order missing 'exchange' field: {order}")
            continue
            
        # Safely extract symbol (handle both possible field names)
        symbol = None
        if 'trading_symbol' in order:
            symbol = order['trading_symbol']
            # Add 'tradingsymbol' field for consistency with rest of the system
            order['tradingsymbol'] = symbol
        elif 'tradingsymbol' in order:
            symbol = order['tradingsymbol']
        else:
            print(f"Warning: Order missing symbol fields (tried 'trading_symbol' and 'tradingsymbol'): {order}")
            continue
        
        # Check if symbol was found; if so, update with OpenAlgo format
        if symbol:
            # Convert to OpenAlgo symbol format
            oa_symbol = get_oa_symbol(symbol=symbol, exchange=exchange)
            order['tradingsymbol'] = oa_symbol
            # Also update trading_symbol if it exists to maintain consistency
            if 'trading_symbol' in order:
                order['trading_symbol'] = oa_symbol
        else:
            print(f"Symbol is empty for exchange {exchange}. Keeping original symbol.")
    
    # Return processed orders
    return orders


def calculate_order_statistics(order_data):
    """
    Calculates statistics from order data, including totals for buy orders, sell orders,
    completed orders, open orders, and rejected orders.
    Handles different field names in Pocketful API response.

    Parameters:
    - order_data: A list of dictionaries, where each dictionary represents an order.

    Returns:
    - A dictionary containing counts of different types of orders.
    """
    # Initialize counters
    total_buy_orders = total_sell_orders = 0
    total_completed_orders = total_open_orders = total_rejected_orders = 0

    if order_data:
        for order in order_data:
            # Get transaction type - check different possible field names
            transaction_type = None
            if 'transaction_type' in order:
                transaction_type = order['transaction_type']
            elif 'order_side' in order:
                transaction_type = order['order_side']
                
            # Count buy and sell orders
            if transaction_type:
                if transaction_type.upper() == 'BUY':
                    total_buy_orders += 1
                elif transaction_type.upper() == 'SELL':
                    total_sell_orders += 1
            
            # Get status and mode for classification
            status = None
            if 'status' in order:
                status = order['status'].upper() if order['status'] else ''
            elif 'order_status' in order:
                status = order['order_status'].upper() if order['order_status'] else ''
            
            mode = order.get('mode', '').upper()
            
            # Flag to track if order has been counted
            counted = False
            
            # Classify order based on status
            if status:
                if 'COMPLETE' in status:
                    total_completed_orders += 1
                    counted = True
                elif 'REJECTED' in status:
                    total_rejected_orders += 1
                    counted = True
            
            # Count as open if either status or mode indicates it's open and hasn't been counted yet
            if not counted and (('OPEN' in (status or '') or 
                              'NEW' in (status or '') or 
                              'PENDING' in (status or '') or 
                              'SUBMIT' in (status or '') or 
                              'MODIFY' in (status or '') or 
                              mode == 'NEW')):
                total_open_orders += 1

    # Compile and return the statistics
    return {
        'total_buy_orders': total_buy_orders,
        'total_sell_orders': total_sell_orders,
        'total_completed_orders': total_completed_orders,
        'total_open_orders': total_open_orders,
        'total_rejected_orders': total_rejected_orders
    }

def transform_order_data(orders):
    """
    Transform order data from Pocketful API format to OpenAlgo standard format.
    Handles both completed and pending orders from the combined order book.
    
    Args:
        orders: Order data from Pocketful API. Can be a single order dict, a list of orders,
               or a response dict containing orders in data field.
    
    Returns:
        List of transformed orders in standard format
    """
    # Extract orders from data if it's a response object
    if isinstance(orders, dict) and 'data' in orders:
        # Handle both possible formats from our API functions
        if isinstance(orders['data'], list):
            orders = orders['data']
        elif isinstance(orders['data'], dict) and 'orders' in orders['data']:
            orders = orders['data']['orders']
        else:
            print(f"Warning: Unexpected data structure. Expected orders in data field.")
            orders = []
    
    # If we have a single order dict, convert it to a list
    if isinstance(orders, dict):
        orders = [orders]
    
    # Initialize result list
    transformed_orders = []
    
    for order in orders:
        # Skip non-dict items
        if not isinstance(order, dict):
            print(f"Warning: Expected a dict, but found a {type(order)}. Skipping this item.")
            continue
        
        # Map order status
        order_status = "unknown"
        status = order.get("order_status", "").upper()
        mode = order.get("mode", "").upper()
        
        # Handle different status mappings
        if "COMPLETE" in status:
            order_status = "complete"
        elif "REJECTED" in status:
            order_status = "rejected"
        elif "TRIGGER PENDING" in status:
            order_status = "trigger pending"
        elif "OPEN" in status or "PENDING" in status or "AMO_SUBMIT" in status or "MODIFY" in status or mode == "NEW":
            order_status = "open"
        elif "CANCEL" in status:
            order_status = "cancelled"
        
        # Get symbol from trading_symbol or tradingsymbol (handling different formats)
        symbol = order.get("trading_symbol", order.get("tradingsymbol", ""))
        
        # Get transaction type from order_side or transaction_type
        action = order.get("order_side", order.get("transaction_type", ""))
        if action.upper() == "BUY":
            action = "BUY"
        elif action.upper() == "SELL":
            action = "SELL"
        
        # Get order type
        price_type = order.get("order_type", "")
        
        # Create transformed order
        transformed_order = {
            "symbol": symbol,
            "exchange": order.get("exchange", ""),
            "action": action,
            "quantity": order.get("quantity", 0),
            "price": order.get("price", 0.0),
            "trigger_price": order.get("trigger_price", 0.0),
            "pricetype": price_type,
            "product": order.get("product", ""),
            "orderid": order.get("oms_order_id", order.get("order_id", "")),
            "order_status": order_status,
            "timestamp": order.get("order_entry_time", order.get("order_timestamp", "")),
            "filled_quantity": order.get("filled_quantity", 0),
            "pending_quantity": order.get("remaining_quantity", 0),
            "average_price": order.get("average_price", 0.0) or order.get("average_trade_price", 0.0)
        }
        
        transformed_orders.append(transformed_order)
    
    return transformed_orders

def map_trade_data(trade_data):
    return map_order_data(trade_data)

def transform_tradebook_data(tradebook_data):
    transformed_data = []
    for trade in tradebook_data:
     
        transformed_trade = {
            "symbol": trade.get('tradingsymbol'),
            "exchange": trade.get('exchange', ''),
            "product": trade.get('product', ''),
            "action": trade.get('transaction_type', ''),
            "quantity": trade.get('quantity', 0),
            "average_price": trade.get('average_price', 0.0),
            "trade_value": trade.get('quantity', 0) * trade.get('average_price', 0.0),
            "orderid": trade.get('order_id', ''),
            "timestamp": trade.get('order_timestamp', '')
        }
        transformed_data.append(transformed_trade)
    return transformed_data

def map_position_data(position_data):
    """
    Processes and modifies a list of OpenPosition dictionaries based on specific conditions.
    
    Parameters:
    - position_data: A list of dictionaries, where each dictionary represents an Open Position.
    
    Returns:
    - The modified order_data with updated 'tradingsymbol'
    """
        # Check if 'data' is None
    if position_data['data']['net'] is None:
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        print("No data available.")
        position_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        position_data = position_data['data']['net']
        
    #print(order_data)

    if position_data:
        for position in position_data:
            # Extract the instrument_token and exchange for the current order
            exchange = position['exchange']
            symbol = position['tradingsymbol']
       
            
            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol:
                position['tradingsymbol'] = get_oa_symbol(symbol=symbol,exchange=exchange)
            else:
                print(f"{symbol} and exchange {exchange} not found. Keeping original trading symbol.")
                
    return position_data
    

def transform_positions_data(positions_data):
    transformed_data = [] 

    for position in positions_data:
        # Ensure average_price is treated as a float, then format to a string with 2 decimal places
        average_price_formatted = "{:.2f}".format(float(position.get('average_price', 0.0)))

        transformed_position = {
            "symbol": position.get('tradingsymbol', ''),
            "exchange": position.get('exchange', ''),
            "product": position.get('product', ''),
            "quantity": position.get('quantity', '0'),
            "average_price": average_price_formatted,
        }
        transformed_data.append(transformed_position)
    return transformed_data

def transform_holdings_data(holdings_data):
    transformed_data = []
    for holdings in holdings_data:
        transformed_position = {
            "symbol": holdings.get('tradingsymbol', ''),
            "exchange": holdings.get('exchange', ''),
            "quantity": holdings.get('quantity', 0),
            "product": holdings.get('product', ''),
            "pnl": round(holdings.get('pnl', 0.0), 2),  # Rounded to two decimals
            "pnlpercent": round((holdings.get('last_price', 0) - holdings.get('average_price', 0.0)) / holdings.get('average_price', 0.0) * 100, 2)  # Rounded to two decimals
        
        }
        transformed_data.append(transformed_position)
    return transformed_data

    
def map_portfolio_data(portfolio_data):
    """
    Processes and modifies a list of Portfolio dictionaries based on specific conditions.
    
    Parameters:
    - portfolio_data: A list of dictionaries, where each dictionary represents an portfolio information.
    
    Returns:
    - The modified portfolio_data with  'product' fields.
    """
        # Check if 'data' is None
    if portfolio_data['data'] is None:
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        print("No data available.")
        portfolio_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        portfolio_data = portfolio_data['data']
        


    if portfolio_data:
        for portfolio in portfolio_data:
            if portfolio['product'] == 'CNC':
                portfolio['product'] = 'CNC'

            else:
                print(f"Pocketful Portfolio - Product Value for Delivery Not Found or Changed.")
                
    return portfolio_data


def calculate_portfolio_statistics(holdings_data):
    totalholdingvalue = sum(item['last_price'] * item['quantity'] for item in holdings_data)
    totalinvvalue = sum(item['average_price'] * item['quantity'] for item in holdings_data)
    totalprofitandloss = sum(item['pnl'] for item in holdings_data)
    
    # To avoid division by zero in the case when total_investment_value is 0
    totalpnlpercentage = (totalprofitandloss / totalinvvalue * 100) if totalinvvalue else 0

    return {
        'totalholdingvalue': totalholdingvalue,
        'totalinvvalue': totalinvvalue,
        'totalprofitandloss': totalprofitandloss,
        'totalpnlpercentage': totalpnlpercentage
    }


