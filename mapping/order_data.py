from database.token_db import get_symbol 

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
        


    if order_data:
        for order in order_data:
            # Extract the instrument_token and exchange for the current order
            instrument_token = order['instrument_token']
            exchange = order['exchange']
            
            # Use the get_symbol function to fetch the symbol from the database
            symbol_from_db = get_symbol(instrument_token, exchange)
            
            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol_from_db:
                order['tradingsymbol'] = symbol_from_db
                if (order['exchange'] == 'NSE' or order['exchange'] == 'BSE') and order['product'] == 'D':
                    order['product'] = 'CNC'
                               
                elif order['product'] == 'I':
                    order['product'] = 'MIS'
                
                elif order['exchange'] in ['NFO', 'MCX', 'BFO', 'CDS'] and order['product'] == 'D':
                    order['product'] = 'NRML'
            else:
                print(f"Symbol not found for token {instrument_token} and exchange {exchange}. Keeping original trading symbol.")
                
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
            if order['transaction_type'] == 'BUY':
                total_buy_orders += 1
            elif order['transaction_type'] == 'SELL':
                total_sell_orders += 1
            
            # Count orders based on their status
            if order['status'] == 'complete':
                total_completed_orders += 1
            elif order['status'] == 'open':
                total_open_orders += 1
            elif order['status'] == 'rejected':
                total_rejected_orders += 1

    # Compile and return the statistics
    return {
        'total_buy_orders': total_buy_orders,
        'total_sell_orders': total_sell_orders,
        'total_completed_orders': total_completed_orders,
        'total_open_orders': total_open_orders,
        'total_rejected_orders': total_rejected_orders
    }


    