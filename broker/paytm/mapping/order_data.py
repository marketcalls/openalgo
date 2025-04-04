import json
from database.token_db import get_symbol
from broker.paytm.mapping.transform_data import map_product_type

def map_order_data(order_data):
    """
    Processes and modifies a list of order dictionaries based on specific conditions.
    
    Parameters:
    - order_data: A list of dictionaries, where each dictionary represents an order.
    
    Returns:
    - The modified order_data with updated 'tradingsymbol' and 'product' fields.
    """
        # Check if 'data' is None
    if order_data['data'] is None:
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        print("No data available.")
        order_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        order_data = order_data['data']
        
    #print(order_data)

    if order_data:
        for order in order_data:
            # Extract the instrument_token and exchange for the current order
            exchange = order['exchange']
            if exchange == "NSE" and ("OPT" in order['instrument'] or "FUT" in order['instrument']):
                exchange = "NFO"
            if exchange == "BSE" and ("OPT" in order['instrument'] or "FUT" in order['instrument']):
                exchange = "BFO"
            symbol = order['security_id']
       
            
            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol:
                order['symbol'] = get_symbol(token=symbol,exchange=exchange)
                if (order['exchange'] == 'NSE' or order['exchange'] == 'BSE') and order['product'] == 'C':
                    order['product'] = 'CNC'
                               
                elif order['product'] == 'I' or order['product'] == 'M':
                    order['product'] = 'MIS'
                
                elif order['exchange'] in ['NFO', 'MCX', 'BFO', 'CDS']:
                    order['product'] = 'NRML'
            else:
                print(f"{symbol} and exchange {exchange} not found. Keeping original trading symbol.")
                
    print(order_data)
    return order_data


def calculate_order_statistics(order_data):
    """
    Calculates statistics from order data, including totals for buy orders, sell orders,
    completed orders, open orders, and rejected orders.

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
            # Count buy and sell orders
            if order['txn_type'] == 'B':
                order['txn_type'] = 'BUY'
                total_buy_orders += 1
            elif order['txn_type'] == 'S':
                order['txn_type'] = 'SELL'
                total_sell_orders += 1
            
            # Count orders based on their status
            if order['display_status'] == 'Successful':
                total_completed_orders += 1
            elif order['display_status'] == 'Pending':
                total_open_orders += 1
            elif order['display_status'] == 'Rejected':
                total_rejected_orders += 1

    # Compile and return the statistics
    return {
        'total_buy_orders': total_buy_orders,
        'total_sell_orders': total_sell_orders,
        'total_completed_orders': total_completed_orders,
        'total_open_orders': total_open_orders,
        'total_rejected_orders': total_rejected_orders
    }


def transform_order_data(orders):
    # Directly handling a dictionary assuming it's the structure we expect
    if isinstance(orders, dict):
        # Convert the single dictionary into a list of one dictionary
        orders = [orders]

    transformed_orders = []
    
    for order in orders:
        # Make sure each item is indeed a dictionary
        if not isinstance(order, dict):
            print(f"Warning: Expected a dict, but found a {type(order)}. Skipping this item.")
            continue

        if(order.get("display_status", "")=="Successful"):
            order_status = "complete"
        if(order.get("display_status", "")=="Rejected"):
            order_status = "rejected"
        if(order.get("display_status", "")=="Pending"):
            order_status = "trigger pending"
        if(order.get("display_status", "")=="Open"):
            order_status = "open"
        if(order.get("display_status", "")=="Cancelled"):
            order_status = "cancelled"

        transformed_order = {
            "symbol": order.get("symbol", ""),
            "exchange": order.get("exchange", ""),
            "action": order.get("txn_type", ""),
            "quantity": order.get("quantity", 0),
            "price": order.get("price", 0.0),
            "trigger_price": order.get("trigger_price", 0.0),
            "pricetype": order.get("display_order_type", "").upper(),
            "product": order.get("product", ""),
            "orderid": order.get("order_no", ""),
            "order_status": order_status,
            "timestamp": order.get("order_date_time", "")
        }

        transformed_orders.append(transformed_order)

    return transformed_orders

def map_trade_data(trade_data):
    return map_order_data(trade_data)

def transform_tradebook_data(tradebook_data):
    transformed_data = []
    tnx_type_mapping = {
        "B": "BUY",
        "S": "SELL"
    }
    for trade in tradebook_data:
        mapped_tnx = tnx_type_mapping.get(trade.get('txn_type', ''), trade.get('txn_type', ''))
        transformed_trade = {
            "symbol": trade.get('symbol'),
            "exchange": trade.get('exchange', ''),
            "product": trade.get('product', ''),
            "action": mapped_tnx,
            "quantity": trade.get('quantity', 0),
            "average_price": trade.get('avg_traded_price', 0.0),
            "trade_value": trade.get('remaining_quantity', 0) * trade.get('avg_traded_price', 0.0),
            "orderid": trade.get('order_no', ''),
            "timestamp": trade.get('order_date_time', '')
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
    if position_data['data'] is None:
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        print("No data available.")
        position_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        position_data = position_data['data']
        
    #print(order_data)

    if position_data:
        for position in position_data:
            # Extract the instrument_token and exchange for the current order
            print(position)
            exchange = position['exchange']
            symbol = position['security_id']
            
            if exchange == "NSE" and ("OPT" in position['instrument'] or "FUT" in position['instrument']):
                exchange = "NFO"

            if exchange == "BSE" and ("OPT" in position['instrument'] or "FUT" in position['instrument']):
                exchange = "BFO"
            
            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol:
                position['security_id'] = get_symbol(token=symbol,exchange=exchange)
            else:
                print(f"{symbol} and exchange {exchange} not found. Keeping original trading symbol.")
        
    print(position_data)
    return position_data
    

def transform_positions_data(positions_data):
    transformed_data = [] 

    for position in positions_data:
        # Ensure average_price is treated as a float, then format to a string with 2 decimal places
        if position.get('display_pos_type') is not None:
            if position.get('display_pos_type') == "B":
                average_price_formatted = "{:.2f}".format(float(position.get('buy_avg', 0.0)))
            elif position.get('display_pos_type') == "S":
                average_price_formatted = "{:.2f}".format(float(position.get('sell_avg', 0.0)))
            else:
                average_price_formatted = "{:.2f}".format(float(position.get('net_avg', 0.0)))
        else:
            average_price_formatted = "{:.2f}".format(float(position.get('net_avg', 0.0)))

        transformed_position = {
            "symbol": position.get('security_id', ''),
            "exchange": position.get('exchange', ''),
            "product": map_product_type(position.get('product', '')),
            "quantity": position.get('net_qty', '0'),
            "average_price": average_price_formatted,
            "ltp": position.get('last_traded_price', '0.00'),
            "pnl": position.get('net_val', '0.00'),
        }
        transformed_data.append(transformed_position)
    return transformed_data

def transform_holdings_data(holdings_data):
    transformed_data = []
    for holdings in holdings_data:
        transformed_position = {
            "symbol": holdings.get('security_id', ''),
            "exchange": holdings.get('exchange', ''),
            "quantity": holdings.get('quantity', 0),
            "product": holdings.get('product', ''),
            "pnl": round(holdings.get('pnl', 0.0), 2),  # Rounded to two decimals
            "pnlpercent": round((holdings.get('last_traded_price', 0) - holdings.get('cost_price', 0.0)) / holdings.get('cost_price', 0.0) * 100, 2)  # Rounded to two decimals
        
        }
        transformed_data.append(transformed_position)
    return transformed_data


