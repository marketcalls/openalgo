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
    """
    Process Pocketful's trade data to map any broker-specific fields.
    
    Args:
        trade_data: Trade data response from Pocketful API
        
    Returns:
        Processed trade data with standardized fields
    """
    # Check if we have any data - now handling direct trades array
    if not trade_data:
        print("No trade data available.")
        return []
    
    # Handle different possible structures:
    trades = []
    
    # Case 1: data is already the trades array (when coming from get_trade_book)
    if isinstance(trade_data, dict) and 'data' in trade_data and isinstance(trade_data['data'], list):
        trades = trade_data['data']
    # Case 2: nested structure (when directly handling API response)
    elif isinstance(trade_data, dict) and 'data' in trade_data and isinstance(trade_data['data'], dict) and 'trades' in trade_data['data']:
        trades = trade_data['data']['trades']
    # Case 3: direct array of trades
    elif isinstance(trade_data, list):
        trades = trade_data
    else:
        print(f"Unexpected trade data format: {type(trade_data)}")
        return []
    
    if not trades:
        print("No trades found in data.")
        return []
    
    print(f"Processing {len(trades)} trades")
    
    # Process each trade
    processed_trades = []
    for trade in trades:
        # Create a copy to avoid modifying the original data
        processed_trade = dict(trade)
        
        # Safely extract exchange
        exchange = processed_trade.get('exchange', '')
            
        # Safely extract symbol
        symbol = processed_trade.get('trading_symbol', '')
        if symbol:
            # Add 'tradingsymbol' field for consistency with rest of the system
            processed_trade['tradingsymbol'] = symbol
            
            # Convert to OpenAlgo symbol format if exchange is available
            if exchange:
                oa_symbol = get_oa_symbol(symbol=symbol, exchange=exchange)
                processed_trade['tradingsymbol'] = oa_symbol
        
        # Map transaction_type/order_side to a standard format
        if 'order_side' in processed_trade and not processed_trade.get('transaction_type'):
            processed_trade['transaction_type'] = processed_trade['order_side']
            
        # Map trade-specific fields to standard names expected by transform function
        if 'trade_quantity' in processed_trade and not processed_trade.get('fill_quantity'):
            processed_trade['fill_quantity'] = processed_trade['trade_quantity']
            
        if 'trade_price' in processed_trade and not processed_trade.get('avg_price'):
            processed_trade['avg_price'] = processed_trade['trade_price']
            
        if 'trade_time' in processed_trade and not processed_trade.get('fill_timestamp'):
            processed_trade['fill_timestamp'] = processed_trade['trade_time']
            
        if 'oms_order_id' in processed_trade and not processed_trade.get('order_id'):
            processed_trade['order_id'] = processed_trade['oms_order_id']
            
        if 'trade_number' in processed_trade and not processed_trade.get('trade_id'):
            processed_trade['trade_id'] = processed_trade['trade_number']
        
        processed_trades.append(processed_trade)
    
    # Return processed trades
    return processed_trades

def transform_tradebook_data(tradebook_data):
    """
    Transform tradebook data from Pocketful API format to OpenAlgo standard format.
    
    Args:
        tradebook_data: Response from Pocketful's trade book API
        
    Returns:
        List of transformed trades in standard format
    """
    # First map the trade data to standardize fields
    trades = map_trade_data(tradebook_data)
    
    transformed_data = []
    for trade in trades:
        # Map fields from Pocketful's format to our standard format
        transformed_trade = {
            "symbol": trade.get('tradingsymbol', ''),
            "exchange": trade.get('exchange', ''),
            "product": trade.get('product', ''),  # Pocketful uses 'product' as is
            "action": trade.get('transaction_type', '').upper(),  # BUY/SELL
            "quantity": int(trade.get('fill_quantity', 0)),  # Executed quantity
            "average_price": float(trade.get('avg_price', 0.0)), # Trade price
            "trade_id": trade.get('trade_id', ''),  # Unique trade identifier
            "orderid": trade.get('order_id', ''),    # Parent order identifier
            "timestamp": trade.get('fill_timestamp', ''),  # Trade execution time
            "trade_value": 0.0  # Will calculate below
        }
        
        # Calculate trade value
        if transformed_trade["quantity"] > 0 and transformed_trade["average_price"] > 0:
            transformed_trade["trade_value"] = transformed_trade["quantity"] * transformed_trade["average_price"]
        
        transformed_data.append(transformed_trade)
    
    return transformed_data

def map_position_data(position_data):
    """
    Processes and modifies a list of position dictionaries based on specific conditions.
    Handles Pocketful's position API response format.
    
    Parameters:
    - position_data: Response from Pocketful's position API
    
    Returns:
    - The modified position data with updated 'tradingsymbol' field
    """
    # Check if we have any data - now handling direct positions array
    if not position_data:
        print("No position data available.")
        return []
    
    # Handle different possible structures:
    positions = []
    print(f"DEBUG - Position data type: {type(position_data)}")
    
    # Case 1: data is already the positions array (when coming from get_positions)
    if isinstance(position_data, dict) and 'data' in position_data and isinstance(position_data['data'], list):
        print(f"DEBUG - Using Case 1: data is a list with {len(position_data['data'])} positions")
        positions = position_data['data']
    # Case 2: nested structure (when directly handling API response)
    elif isinstance(position_data, dict) and 'data' in position_data and isinstance(position_data['data'], dict) and 'positions' in position_data['data']:
        print(f"DEBUG - Using Case 2: data.positions structure")
        positions = position_data['data']['positions']
    # Case 3: direct array of positions
    elif isinstance(position_data, list):
        print(f"DEBUG - Using Case 3: direct array with {len(position_data)} positions")
        positions = position_data
    # Case 4: Legacy structure with 'net' key
    elif isinstance(position_data, dict) and 'data' in position_data and isinstance(position_data['data'], dict) and 'net' in position_data['data']:
        print(f"DEBUG - Using Case 4: data.net structure")
        positions = position_data['data']['net'] if position_data['data']['net'] is not None else []
    else:
        print(f"DEBUG - Unexpected position data format: {type(position_data)}")
        # For debugging, try to print more details about the structure
        if isinstance(position_data, dict):
            print(f"DEBUG - Dict keys: {position_data.keys()}")
            if 'data' in position_data:
                print(f"DEBUG - Data type: {type(position_data['data'])}")
                if isinstance(position_data['data'], dict):
                    print(f"DEBUG - Data dict keys: {position_data['data'].keys()}")
        return []
    
    if not positions:
        print("No positions found in data.")
        return []
    
    print(f"Processing {len(positions)} positions")
    
    # Process each position
    processed_positions = []
    for position in positions:
        # Create a copy to avoid modifying the original data
        processed_position = dict(position)
        
        # Safely extract exchange
        exchange = processed_position.get('exchange', '')
            
        # Safely extract symbol (handle both trading_symbol and tradingsymbol fields)
        symbol = processed_position.get('trading_symbol', processed_position.get('tradingsymbol', ''))
        if symbol:
            # Add 'tradingsymbol' field for consistency with rest of the system
            processed_position['tradingsymbol'] = symbol
            
            # Convert to OpenAlgo symbol format if exchange is available
            if exchange:
                oa_symbol = get_oa_symbol(symbol=symbol, exchange=exchange)
                if oa_symbol:
                    processed_position['tradingsymbol'] = oa_symbol
                else:
                    print(f"Symbol {symbol} not found in database for exchange {exchange}. Keeping original symbol.")
        
        # Map Pocketful-specific fields to standard format
        
        # Ensure quantity field exists - prioritize net_quantity since that's what we need
        if 'net_quantity' in processed_position:
            processed_position['quantity'] = processed_position['net_quantity']
        
        # Handle average price
        if 'average_buy_price' in processed_position and float(processed_position.get('average_buy_price', 0)) > 0:
            processed_position['average_price'] = processed_position['average_buy_price']
        elif 'average_sell_price' in processed_position and float(processed_position.get('average_sell_price', 0)) > 0:
            processed_position['average_price'] = processed_position['average_sell_price']
        
        # Handle last price
        if 'ltp' in processed_position:
            processed_position['last_price'] = processed_position['ltp']
        
        # Handle buy/sell quantity
        if 'buy_quantity' in processed_position:
            processed_position['buy_quantity'] = processed_position['buy_quantity']
        if 'sell_quantity' in processed_position:
            processed_position['sell_quantity'] = processed_position['sell_quantity']
            
        # Handle pnl calculation
        if ('ltp' in processed_position and 
            'net_quantity' in processed_position and 
            'average_buy_price' in processed_position and 
            processed_position.get('net_quantity', 0) > 0):
            # Calculate PnL for long positions
            qty = float(processed_position['net_quantity'])
            avg = float(processed_position['average_buy_price'])
            ltp = float(processed_position['ltp'])
            processed_position['pnl'] = (ltp - avg) * qty
        elif ('ltp' in processed_position and 
              'net_quantity' in processed_position and 
              'average_sell_price' in processed_position and 
              processed_position.get('net_quantity', 0) < 0):
            # Calculate PnL for short positions
            qty = abs(float(processed_position['net_quantity']))
            avg = float(processed_position['average_sell_price'])
            ltp = float(processed_position['ltp'])
            processed_position['pnl'] = (avg - ltp) * qty
            
        processed_positions.append(processed_position)
    
    # Return processed positions
    return processed_positions

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
                print(f"Zerodha Portfolio - Product Value for Delivery Not Found or Changed.")
                
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


