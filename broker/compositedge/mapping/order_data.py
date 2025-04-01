import json
from turtle import position
from database.token_db import get_symbol, get_oa_symbol 

def map_order_data(order_data):
    """
    Processes and modifies a list of order dictionaries based on specific conditions.
    
    Parameters:
    - order_data: A list of dictionaries, where each dictionary represents an order.
    
    Returns:
    - The modified order_data with updated 'tradingsymbol' and 'product' fields.
    """
    exchange_mapping = {
        "NSECM": "NSE",
        "BSECM": "BSE",
        "NSEFO": "NFO",
        "BSEFO": "BFO",
        "MCXFO": "MCX",
        "NSECD": "CDS"
    }
    
    
        # Check if 'data' is None
    #print(f"order_data: {order_data}")

    if 'result' not in order_data or not order_data['result']:
        print("No data available.")
        return []  # Return an empty list if no orders are available
    
    order_data = order_data['result']

    if order_data:
        for order in order_data:
            # Extract the instrument_token and exchange for the current order
            symboltoken = order['ExchangeInstrumentID']
            exch = order.get("ExchangeSegment", "")
            exchange = exchange_mapping.get(exch, exch)
            
            # Use the get_symbol function to fetch the symbol from the database
            symbol_from_db = get_symbol(symboltoken, exchange)
            
            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol_from_db:
                order['TradingSymbol'] = symbol_from_db

    #print(f"orders: {order_data}")
   
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
            if order['OrderSide'] == 'BUY':
                total_buy_orders += 1
            elif order['OrderSide'] == 'SELL':
                total_sell_orders += 1
            
            # Count orders based on their status
            if order['OrderStatus'] == 'Filled':
                total_completed_orders += 1
            elif order['OrderStatus'] == 'New':
                total_open_orders += 1
            elif order['OrderStatus'] == 'Rejected':
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

     # Define exchange mappings
    exchange_mapping = {
        "NSECM": "NSE",
        "BSECM": "BSE",
        "NSEFO": "NFO",
        "BSEFO": "BFO",
        "MCXFO": "MCX",
        "NSECD": "CDS"
    }
    
    # Define order type mappings
    order_type_mapping = {
            "Limit": "LIMIT",
            "Market": "MARKET",
            "StopLimit": "SL",
            "StopMarket": "SL-M"
        }
    # Define order status mappings
    order_status_mapping = {
        "Filled": "complete",
        "Rejected": "rejected",
        "Cancelled": "cancelled",
        "New": "open",
    }
    for order in orders:
        # Make sure each item is indeed a dictionary
        if not isinstance(order, dict):
            print(f"Warning: Expected a dict, but found a {type(order)}. Skipping this item.")
            continue
        exchange = order.get("ExchangeSegment", "")
        mapped_exchange = exchange_mapping.get(exchange, exchange)

        
        # Get the order type value and map it
        order_type = order.get("OrderType", "")
        mapped_order_type = order_type_mapping.get(order_type, order_type)  # Use mapped value if available

        # Map order status
        order_status = order.get("OrderStatus", "")
        mapped_order_status = order_status_mapping.get(order_status, order_status)

        transformed_order = {
            "symbol": order.get("TradingSymbol", ""),
            "exchange": mapped_exchange,
            "action": order.get("OrderSide", ""),
            "quantity": order.get("OrderQuantity", 0),
            "price": order.get("OrderPrice", 0.0),
            "trigger_price": order.get("OrderStopPrice", 0.0),
            "pricetype": mapped_order_type,
            "product": order.get("ProductType", ""),
            "orderid": order.get("AppOrderID", ""),
            "order_status": mapped_order_status,
            "timestamp": order.get("LastUpdateDateTime", "")
        }

        transformed_orders.append(transformed_order)

    return transformed_orders



def map_trade_data(trade_data):
    """
    Processes and modifies a list of order dictionaries based on specific conditions.
    
    Parameters:
    - order_data: A list of dictionaries, where each dictionary represents an order.
    
    Returns:
    - The modified order_data with updated 'tradingsymbol' and 'product' fields.
    """
    exchange_mapping = {
        "NSECM": "NSE",
        "BSECM": "BSE",
        "NSEFO": "NFO",
        "BSEFO": "BFO",
        "MCXFO": "MCX",
        "NSECD": "CDS"
    }
    
        # Check if 'data' is None
    if 'result' not in trade_data or not trade_data['result']:
        print("No data available.")
        return []  # Return an empty list if no orders are available
    
    trade_data = trade_data['result']

    if trade_data:

        for trade in trade_data:
            # Extract the instrument_token and exchange for the current order
            symboltoken = trade['ExchangeInstrumentID']
            exch = trade.get("ExchangeSegment", "")
            exchange = exchange_mapping.get(exch, exch)
            
            # Use the get_symbol function to fetch the symbol from the database
            symbol_from_db = get_symbol(symboltoken, exchange)
            
            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol_from_db:
                trade['TradingSymbol'] = symbol_from_db


    print(f"trade_data: {trade_data}")
   
    return trade_data




def transform_tradebook_data(tradebook_data):
    transformed_data = []

    # Define exchange mappings
    exchange_mapping = {
        "NSECM": "NSE",
        "BSECM": "BSE",
        "NSEFO": "NFO",
        "BSEFO": "BFO",
        "MCXFO": "MCX",
        "NSECD": "CDS"
    }
    
   
    for trade in tradebook_data:

        exchange = trade.get("ExchangeSegment", "")
        mapped_exchange = exchange_mapping.get(exchange, exchange)
        
        # Ensure quantity and average price are converted to the correct types
        quantity = int(trade.get('OrderQuantity', 0))
        average_price = float(trade.get('OrderAverageTradedPrice', 0.0))

        transformed_trade = {
            "symbol": trade.get('TradingSymbol', ''),
            "exchange": mapped_exchange,
            "product": trade.get('ProductType', ''),
            "action": trade.get('OrderSide', ''),
            "quantity": quantity,
            "average_price": average_price,
            "trade_value": quantity * average_price,
            "orderid": trade.get('AppOrderID', ''),
            "timestamp": trade.get('OrderGeneratedDateTime', '')
        }
        transformed_data.append(transformed_trade)
    return transformed_data


def map_position_data(position_data):
    """
     Processes and modifies a list of order dictionaries based on specific conditions.
     
     Parameters:
     - order_data: A list of dictionaries, where each dictionary represents an order.
     
     Returns:
     - The modified order_data with updated 'tradingsymbol' and 'product' fields.
    """
    # Check if 'data' is None
    #print(f"order_data: {order_data}")
    if 'result' not in position_data or not position_data['result']:
        print("No data available.")
        return []  # Return an empty list if no orders are available
    
    position_data = position_data['result']
 
    #print(f"position_data: {position_data}")
    
 
    return position_data


def transform_positions_data(positions_data):
    #print(f"positions_data: {positions_data}")
    positions_data = positions_data.get("positionList", [])
    transformed_data = []
    
    # Define exchange mappings
    exchange_mapping = {
        "NSECM": "NSE",
        "BSECM": "BSE",
        "NSEFO": "NFO",
        "BSEFO": "BFO",
        "MCXFO": "MCX",
        "NSECD": "CDS"
    }
    if not isinstance(positions_data, list):
        print(f"Error: positions_data is not a list. Received: {type(positions_data)} - {positions_data}")
        return transformed_data

    for position in positions_data:

        if not isinstance(position, dict):  # Ensure it's a dictionary
            print(f"Skipping invalid position: {position}")
            continue
        symboltoken = position.get('ExchangeInstrumentID')
        exchange = position.get("ExchangeSegment", "")
        mapped_exchange = exchange_mapping.get(exchange, exchange)

        symbol_from_db = get_symbol(symboltoken, mapped_exchange)

        if symbol_from_db:
            position['TradingSymbol'] = symbol_from_db
        
        netqty = float(position.get('Quantity', 0))
        if netqty > 0 :
            net_amount = float(position.get('BuyAveragePrice', 0))
        elif netqty < 0:
            net_amount = float(position.get('SellAveragePrice', 0))
        else:
            net_amount = 0
        
        average_price = net_amount    
        # Ensure average_price is treated as a float, then format to a string with 2 decimal places
        average_price_formatted = "{:.2f}".format(average_price)

        transformed_position = {
            "symbol": position.get("TradingSymbol", ""),
            "exchange": mapped_exchange,
            "product": position.get('ProductType', ''),
            "quantity": position.get('Quantity', 0),
            "average_price": average_price_formatted,
            "ltp": position.get('ltp', 0.0),  
            "pnl": position.get('pnl', 0.0),  
        }
        #print(f"Transformed Position: {transformed_position}") 
        transformed_data.append(transformed_position)
    return transformed_data

def transform_holdings_data(holdings_data):
    print(f"holdings_data: {holdings_data}")
    transformed_data = []
    for holdings in holdings_data['holdings']:
        transformed_position = {
            "symbol": holdings.get('tradingsymbol', ''),
            "exchange": holdings.get('exchange', ''),
            "quantity": holdings.get('quantity', 0),
            "product": holdings.get('product', ''),
            "pnl": holdings.get('profitandloss', 0.0),
            "pnlpercent": holdings.get('pnlpercentage', 0.0)
        }
        transformed_data.append(transformed_position)
    return transformed_data

def map_portfolio_data(portfolio_data):
    print(f"portfolio_data: {portfolio_data}")
    """
    Processes and modifies a list of Portfolio dictionaries based on specific conditions and
    ensures both holdings and totalholding parts are transmitted in a single response.
    
    Parameters:
    - portfolio_data: A dictionary, where keys are 'holdings' and 'totalholding',
                      and values are lists/dictionaries representing the portfolio information.
    
    Returns:
    - The modified portfolio_data with 'product' fields changed for 'holdings' and 'totalholding' included.
    """
    # Check if 'data' is None or doesn't contain 'holdings'
    if portfolio_data.get('data') is None or 'holdings' not in portfolio_data['data']:
        print("No data available.")
        # Return an empty structure or handle this scenario as needed
        return {}

    # Directly work with 'data' for clarity and simplicity
    data = portfolio_data['data']

    # Modify 'product' field for each holding if applicable
    if data.get('holdings'):
        for portfolio in data['holdings']:
            symbol = portfolio['tradingsymbol']
            exchange = portfolio['exchange']
            symbol_from_db = get_oa_symbol(symbol, exchange)
            
            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol_from_db:
                portfolio['tradingsymbol'] = symbol_from_db
            if portfolio['product'] == 'DELIVERY':
                portfolio['product'] = 'CNC'  # Modify 'product' field
            else:
                print("AngelOne Portfolio - Product Value for Delivery Not Found or Changed.")
    
    # The function already works with 'data', which includes 'holdings' and 'totalholding',
    # so we can return 'data' directly without additional modifications.
    return data


def calculate_portfolio_statistics(holdings_data):

    if holdings_data['totalholding'] is None:
        totalholdingvalue = 0
        totalinvvalue = 0
        totalprofitandloss = 0
        totalpnlpercentage = 0
    else:

        totalholdingvalue = holdings_data['totalholding']['totalholdingvalue']
        totalinvvalue = holdings_data['totalholding']['totalinvvalue']
        totalprofitandloss = holdings_data['totalholding']['totalprofitandloss']
        
        # To avoid division by zero in the case when total_investment_value is 0
        totalpnlpercentage = holdings_data['totalholding']['totalpnlpercentage']

    return {
        'totalholdingvalue': totalholdingvalue,
        'totalinvvalue': totalinvvalue,
        'totalprofitandloss': totalprofitandloss,
        'totalpnlpercentage': totalpnlpercentage
    }
