import json
from database.token_db import get_symbol , get_oa_symbol

def map_order_data(order_data):
    """
    Processes and modifies a list of order dictionaries based on specific conditions.
    
    Parameters:
    - order_data: A list of dictionaries, where each dictionary represents an order.
    
    Returns:
    - The modified order_data with updated 'tradingsymbol' and 'product' fields.
    """
    if isinstance(order_data, dict):
        if order_data['stat'] == 'Not_Ok' :
            # Handle the case where there is an error in the data
            # For example, you might want to display an error message to the user
            # or pass an empty list or dictionary to the template.
            print(f"Error fetching order data: {order_data['emsg']}")
            order_data = {}
    else:
        order_data = order_data
        
    # print(order_data)

    if order_data:
        for order in order_data:
            # Extract the instrument_token and exchange for the current order
            exchange = order['Exchange']
            symbol = order['Trsym']
       
            
            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol:
                order['Trsym'] = get_oa_symbol(symbol=symbol,exchange=exchange)
            else:
                print(f"{symbol} and exchange {exchange} not found. Keeping original trading symbol.")
                
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
            if order['Trantype'] == 'B':
                total_buy_orders += 1
            elif order['Trantype'] == 'S':
                total_sell_orders += 1
            
            # Count orders based on their status
            if order['Status'] == 'complete':
                total_completed_orders += 1
            elif order['Status'] == 'open':
                total_open_orders += 1
            elif order['Status'] == 'rejected':
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
    print(orders)
    for order in orders:
        # Make sure each item is indeed a dictionary
        if not isinstance(order, dict):
            print(f"Warning: Expected a dict, but found a {type(order)}. Skipping this item.")
            continue
        
        # Check if the necessary keys exist in the order
        if 'Trantype' not in order or 'Prctype' not in order:
            print("Error: Missing required keys in the order. Skipping this item.")
            continue
        
        if order['Trantype'] == 'B':
            trans_type = 'BUY'
        elif order['Trantype'] == 'S':
            trans_type = 'SELL'
        else:
            trans_type = 'UNKNOWN'

        if order['Prctype'] == 'MKT':
            order_type = 'MARKET'
        elif order['Prctype'] == 'L':
            order_type = 'LIMIT'
        elif order['Prctype'] == 'SL':
            order_type = 'SL'
        elif order['Prctype'] == 'SL-M':
            order_type = 'SL-M'
        else:
            order_type = 'UNKNOWN'

        transformed_order = {
            "symbol": order.get("Trsym", ""),
            "exchange": order.get("Exchange", ""),
            "action": trans_type,
            "quantity": order.get("Qty", 0),
            "price": order.get("Prc", 0.0),
            "trigger_price": order.get("Trgprc", 0.0),
            "pricetype": order_type,
            "product": order.get("Pcode", ""),
            "orderid": order.get("Nstordno", ""),
            "order_status": order.get("Status", ""),
            "timestamp": order.get("orderentrytime", "")
        }

        transformed_orders.append(transformed_order)

    return transformed_orders


def map_trade_data(trade_data):
    """
    Processes and modifies a list of order dictionaries based on specific conditions.
    
    Parameters:
    - trade_data: A list of dictionaries, where each dictionary represents an order.
    
    Returns:
    - The modified trade_data with updated 'tradingsymbol' and 'product' fields.
    """
    if isinstance(trade_data, dict):
        if trade_data['stat'] == 'Not_Ok' :
            # Handle the case where there is an error in the data
            # For example, you might want to display an error message to the user
            # or pass an empty list or dictionary to the template.
            print(f"Error fetching order data: {trade_data['emsg']}")
            trade_data = {}
    else:
        trade_data = trade_data
        
    # print(trade_data)

    if trade_data:
        for trade in trade_data:
            # Extract the instrument_token and exchange for the current trade
            exchange = trade['Exchange']
            symbol = trade['Tsym']
            
            # Check if a symbol was found; if so, update the trading_symbol in the current trade
            if symbol:
                trade['Tsym'] = get_oa_symbol(symbol=symbol,exchange=exchange)
            else:
                print(f"{symbol} and exchange {exchange} not found. Keeping original trading symbol.")
                
    return trade_data

def transform_tradebook_data(tradebook_data):
    transformed_data = []
    for trade in tradebook_data:

        # Check if the necessary keys exist in the order
        # if 'Qty' not in trade or 'Average price' not in trade:
        #     print("Error: Missing required keys in the order. Skipping this item.")
        #     continue

        # Ensure quantity and average price are converted to the correct types
        quantity = int(trade.get('Qty', 0))
        average_price = float(trade.get('Average price', 0.0))
        
        transformed_trade = {
            "symbol": trade.get('Tsym'),
            "exchange": trade.get('Exchange', ''),
            "product": trade.get('Pcode', ''),
            "action": trade.get('Trantype', ''),
            "quantity": quantity,
            "average_price": average_price,
            "trade_value": quantity * average_price,
            "orderid": trade.get('Nstordno', ''),
            "timestamp": trade.get('Time', '')
        }
        transformed_data.append(transformed_trade)
    return transformed_data


def map_position_data(position_data):
    """
    Processes and modifies a list of order dictionaries based on specific conditions.
    
    Parameters:
    - position_data: A list of dictionaries, where each dictionary represents an order.
    
    Returns:
    - The modified position_data with updated 'tradingsymbol' and 'product' fields.
    """
    if isinstance(position_data, dict):
        if position_data['stat'] == 'Not_Ok' :
            # Handle the case where there is an error in the data
            # For example, you might want to display an error message to the user
            # or pass an empty list or dictionary to the template.
            print(f"Error fetching order data: {position_data['emsg']}")
            position_data = {}
    else:
        position_data = position_data
        
    # print(order_data)

    if position_data:
        for position in position_data:
            # Extract the instrument_token and exchange for the current order
            exchange = position['Exchange']
            symbol = position['Tsym']
       
            
            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol:
                position['Tsym'] = get_oa_symbol(symbol=symbol,exchange=exchange)
            else:
                print(f"{symbol} and exchange {exchange} not found. Keeping original trading symbol.")
                
    return position_data
    

def transform_positions_data(positions_data):
    transformed_data = [] 

    for position in positions_data:
        netqty = float(position.get('Netqty', 0))
        if netqty > 0 :
            net_amount = float(position.get('NetBuyavgprc', 0))
        elif netqty < 0:
            net_amount = float(position.get('NetSellavgprc', 0))
        else:
            net_amount = 0
        
        average_price = net_amount    
        # Ensure average_price is treated as a float, then format to a string with 2 decimal places
        average_price_formatted = "{:.2f}".format(average_price)

        transformed_position = {
            "symbol": position.get('Tsym', ''),
            "exchange": position.get('Exchange', ''),
            "product": position.get('Pcode', ''),
            "quantity": position.get('Netqty', '0'),
            "average_price": average_price_formatted,
        }
        transformed_data.append(transformed_position)
    return transformed_data

def transform_holdings_data(holdings_data):
    transformed_data = []
    for holdings in holdings_data:
        ltp = float(holdings.get('Ltp', 0))
        price = float(holdings.get('Price', 0.0))
        quantity = int(holdings.get('Holdqty', 0))

        pnl = round(ltp - price, 2)
        pnlpercent = round(((ltp - price) / price * 100), 2) if price else 0

        transformed_position = {
            "symbol": holdings.get('Bsetsym', ''),
            "exchange": holdings.get('ExchSeg1', ''),
            "quantity": quantity,
            "product": holdings.get('Pcode', ''),
            "pnl": pnl,  # Rounded to two decimals
            "pnlpercent": pnlpercent  # Rounded to two decimals
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
    if isinstance(portfolio_data, dict):
        if portfolio_data['stat'] == 'Not_Ok' :
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
            print("No data available.")
            portfolio_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        portfolio_data = portfolio_data['HoldingVal']
        
    print(portfolio_data)

    if portfolio_data:
        for portfolio in portfolio_data:
            if portfolio['Pcode'] == 'CNC':
                portfolio['Pcode'] = 'CNC'

            else:
                print(f"AliceBlue Portfolio - Product Value for Delivery Not Found or Changed.")
                
    return portfolio_data

def calculate_portfolio_statistics(holdings_data):
    
    totalholdingvalue = sum(float(item['Ltp']) * int(item['HUqty']) for item in holdings_data)
    totalinvvalue = sum(float(item['Price']) * int(item['HUqty']) for item in holdings_data)
    totalprofitandloss = sum((float(item['Ltp']) - float(item['Price'])) * int(item['HUqty']) for item in holdings_data)
    
    for item in holdings_data:
        print((item['Ltp'],item['Price'],item['HUqty']))
    # To avoid division by zero in the case when totalinvvalue is 0
    totalpnlpercentage = (totalprofitandloss / totalinvvalue * 100) if totalinvvalue else 0

    return {
        'totalholdingvalue': totalholdingvalue,
        'totalinvvalue': totalinvvalue,
        'totalprofitandloss': totalprofitandloss,
        'totalpnlpercentage': totalpnlpercentage
    }



