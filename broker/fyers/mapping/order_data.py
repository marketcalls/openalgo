import json
from database.token_db import get_symbol , get_oa_symbol

    # Mapping of (Exchange Code, Segment Code) to Exchange
exchange_map = {
    (10, 10): 'NSE',
    (10, 11): 'NFO',
    (10, 12): 'CDS',
    (12, 10): 'BSE',
    (12, 11): 'BFO',
    (11, 20): 'MCX'
}

def get_exchange(exchange_code, segment_code):
    # Key is a tuple of exchange_code and segment_code
    key = (exchange_code, segment_code)
    
    # Return the exchange name if key exists, else return None or a default value
    return exchange_map.get(key, "Unknown Exchange")


def map_order_data(order_data):
    """
    Processes and modifies a list of order dictionaries based on specific conditions.
    
    Parameters:
    - order_data: A list of dictionaries, where each dictionary represents an order.
    
    Returns:
    - The modified order_data with updated 'tradingsymbol' and 'product' fields.
    """
        # Check if 'data' is None
    if order_data['orderBook'] is None:
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        print("No data available.")
        order_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        order_data = order_data['orderBook']
        
    #print(order_data)



    if order_data:
        for order in order_data:
            # Extract the instrument_token and exchange for the current order
            exchange_code = order['exchange']
            segment_code = order['segment']
            exchange = get_exchange(exchange_code, segment_code)
            symbol = order['symbol']
       
            
            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol:
                order['symbol'] = get_oa_symbol(symbol=symbol,exchange=exchange)
                order['exchange'] = exchange
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
            if order['side'] == 1:
                total_buy_orders += 1
            elif order['side'] == -1:
                total_sell_orders += 1
            
            # Count orders based on their status
            if order['status'] == 2:
                total_completed_orders += 1
            elif order['status'] == 6:
                total_open_orders += 1
            elif order['status'] == 5:
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

        if(order.get("status")==2):
            order_status = "complete"
        if(order.get("status")==5):
            order_status = "rejected"
        if(order.get("status")==4):
            order_status = "trigger pending"
        if(order.get("status")==6):
            order_status = "open"
        if(order.get("status")==1):
            order_status = "cancelled"

        if(order.get("side")==1):
            action = "BUY"
        if(order.get("side")==-1):
            action = "SELL"

        if(order.get("type")==1):
            ordertype = "LIMIT"
        if(order.get("type")==2):
            ordertype = "MARKET"
        if(order.get("type")==3):
            ordertype = "SL-M"
        if(order.get("type")==4):
            ordertype = "SL"

        if(order.get("productType")=="CNC"):
            producttype = "CNC"
        if(order.get("productType")=="INTRADAY"):
            producttype = "MIS"
        if(order.get("productType")=="MARGIN"):
            producttype = "NRML"
        if(order.get("productType")=="CO"):
            producttype = "CO"
        if(order.get("productType")=="BO"):
            producttype = "BO"

        transformed_order = {
            "symbol": order.get("symbol", ""),
            "exchange": order.get("exchange", ""),
            "action": action,
            "quantity": order.get("qty", 0),
            "price": order.get("limitPrice", 0.0),
            "trigger_price": order.get("stopPrice", 0.0),
            "pricetype": ordertype,
            "product": producttype,
            "orderid": order.get("id", ""),
            "order_status": order_status,
            "timestamp": order.get("orderDateTime", "")
        }

        transformed_orders.append(transformed_order)

    return transformed_orders

def map_trade_data(trade_data):
    """
    Processes and modifies a list of order dictionaries based on specific conditions.
    
    Parameters:
    - trade_data: A list of dictionaries, where each dictionary represents an order.
    
    Returns:
    - The modified trade_data with updated 'symbol' and 'product' fields.
    """
        # Check if 'data' is None
    if trade_data['tradeBook'] is None:
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        print("No data available.")
        trade_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        trade_data = trade_data['tradeBook']
        
    #print(trade_data)



    if trade_data:
        for trade in trade_data:
            # Extract the instrument_token and exchange for the current order
            exchange_code = trade['exchange']
            segment_code = trade['segment']
            exchange = get_exchange(exchange_code, segment_code)
            symbol = trade['symbol']
            
       
            
            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol:
                trade['symbol'] = get_oa_symbol(symbol=symbol,exchange=exchange)
                trade['exchange'] = exchange
            else:
                print(f"{symbol} and exchange {exchange} not found. Keeping original trading symbol.")
                
    return trade_data

def transform_tradebook_data(tradebook_data):
    transformed_data = []
    for trade in tradebook_data:

        symbol = trade.get('symbol')
        exchange = trade.get('exchange')

        if(trade.get("side")==1):
            action = "BUY"
        if(trade.get("side")==-1):
            action = "SELL"


        if(trade.get("productType")=="CNC"):
            producttype = "CNC"
        if(trade.get("productType")=="INTRADAY"):
            producttype = "MIS"
        if(trade.get("productType")=="MARGIN"):
            producttype = "NRML"
        if(trade.get("productType")=="CO"):
            producttype = "CO"
        if(trade.get("productType")=="BO"):
            producttype = "BO"


        transformed_trade = {
            "symbol": symbol,
            "exchange": trade.get('exchange', ''),
            "product": producttype,
            "action": action,
            "quantity": trade.get('tradedQty', 0),
            "average_price": trade.get('tradePrice', 0.0),
            "trade_value": trade.get('tradeValue', 0),
            "orderid": trade.get('orderNumber', ''),
            "timestamp": trade.get('orderDateTime', '')
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
    if position_data['netPositions'] is None:
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        print("No data available.")
        position_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        position_data = position_data['netPositions']
        
    print(position_data)

    if position_data:
        for position in position_data:
            # Extract the instrument_token and exchange for the current order
            exchange_code = position['exchange']
            segment_code = position['segment']
            exchange = get_exchange(exchange_code, segment_code)
            symbol = position['symbol']
       
            
            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol:
                position['symbol'] = get_oa_symbol(symbol=symbol,exchange=exchange)
                position['exchange'] = exchange
            else:
                print(f"{symbol} and exchange {exchange} not found. Keeping original trading symbol.")
                
    return position_data
    

def transform_positions_data(positions_data):
    transformed_data = [] 

    for position in positions_data:
        # Ensure average_price is treated as a float, then format to a string with 2 decimal places
        average_price_formatted = "{:.2f}".format(float(position.get('avgPrice', 0.0)))


        if(position.get("productType")=="CNC"):
            producttype = "CNC"
        if(position.get("productType")=="INTRADAY"):
            producttype = "MIS"
        if(position.get("productType")=="MARGIN"):
            producttype = "NRML"
        if(position.get("productType")=="CO"):
            producttype = "CO"
        if(position.get("productType")=="BO"):
            producttype = "BO"

        transformed_position = {
            "symbol": position.get('symbol', ''),
            "exchange": position.get('exchange', ''),
            "product": producttype,
            "quantity": position.get('netQty', '0'),
            "average_price": average_price_formatted,
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
        # Check if 'holdings' is None
    if portfolio_data['holdings'] is None:
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        print("No data available.")
        portfolio_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        portfolio_data = portfolio_data['holdings']
        
    print(portfolio_data)

    if portfolio_data:
        for portfolio in portfolio_data:
            if portfolio['holdingType'] == 'HLD' or portfolio['holdingType'] == 'T1':
                portfolio['holdingType'] = 'CNC'

            else:
                print(f"Fyers Portfolio - Product Value for Delivery Not Found or Changed.")
            
            exchange_code = portfolio['exchange']
            segment_code = portfolio['segment']
            exchange = get_exchange(exchange_code, segment_code)
            symbol = portfolio['symbol']

            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol:
                portfolio['symbol'] = get_oa_symbol(symbol=symbol,exchange=exchange)
                portfolio['exchange'] = exchange
            else:
                print(f"{symbol} and exchange {exchange} not found. Keeping original trading symbol.")
                
    return portfolio_data


def transform_holdings_data(holdings_data):
    transformed_data = []
    for holdings in holdings_data:
        
        pnl = round(holdings.get('pl', 0.0),2)

        transformed_position = {
            "symbol": holdings.get('symbol', ''),
            "exchange": holdings.get('exchange', ''),
            "quantity": holdings.get('quantity', 0),
            "product": holdings.get('holdingType', ''),
            "pnl": pnl,
            "pnlpercent": (holdings.get('ltp', 0) - holdings.get('costPrice', 0.0)) /holdings.get('costPrice', 0.0) *100
            
        }
        transformed_data.append(transformed_position)
    return transformed_data


def calculate_portfolio_statistics(holdings_data):
    totalholdingvalue = sum(item['ltp'] * item['quantity'] for item in holdings_data)
    totalinvvalue = sum(item['costPrice'] * item['quantity'] for item in holdings_data)
    totalprofitandloss = sum(item['pl'] for item in holdings_data)
    
    # To avoid division by zero in the case when total_investment_value is 0
    totalpnlpercentage = (totalprofitandloss / totalinvvalue * 100) if totalinvvalue else 0
    totalpnlpercentage = round(totalpnlpercentage, 2)


    return {
        'totalholdingvalue': totalholdingvalue,
        'totalinvvalue': totalinvvalue,
        'totalprofitandloss': totalprofitandloss,
        'totalpnlpercentage': totalpnlpercentage
    }


