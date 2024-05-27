import json
from database.token_db import get_symbol , get_oa_symbol

def format_strike(strike):
    # Convert strike to string first
    strike_str = str(strike)
    # Check if the string ends with '.0' and remove it
    if strike_str.endswith('.0'):
        # Remove the last two characters '.0'
        return strike_str[:-2]
    # Return the original string if it does not end with '.0'
    return strike_str

def map_order_data(order_data):
    """
    Processes and modifies a list of order dictionaries based on specific conditions.
    
    Parameters:
    - order_data: A list of dictionaries, where each dictionary represents an order.
    
    Returns:
    - The modified order_data with updated 'symbol' and 'product' fields.
    """
        # Check if 'data' is None
    if order_data['data']['order_book'] is None:
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        print("No data available.")
        order_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        order_data = order_data['data']['order_book']
        #print(order_data)
        


    if order_data:
        for order in order_data:
            # Extract the instrument_token and exchange for the current order
            right = ''
            expiry_date = ''

            exchange = order['exchange_code']
            if exchange == "NFO":
                right = order['right'].upper()
                expiry_date = order['expiry_date'].upper()
            
            
            symbol = order['stock_code']

            if exchange == "NFO" and right == "OTHERS":
                symbol = order['stock_code'] + ":::" + expiry_date + ":::" + "FUT"
            elif exchange == "NFO" and (right == "CALL" or right == "PUT"):
                symbol = f"{order['stock_code']}:::{expiry_date}:::{format_strike(order['strike_price'])}:::{right}"

            
            
            # print(symbol)
            # print(exchange)
            # print(right)
            # print(expiry_date)
            
            # Use the get_symbol function to fetch the symbol from the database
            symbol_from_db = get_oa_symbol(symbol=symbol,exchange=exchange)
            
            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol_from_db:
                order['stock_code'] = symbol_from_db
                if (order['exchange_code'] == 'NSE' or order['exchange_code'] == 'BSE') and order['product_type'] == 'Margin':
                    order['product_type'] = 'MIS'

                elif (order['exchange_code'] == 'NSE' or order['exchange_code'] == 'BSE') and order['product_type'] == 'Cash':
                    order['product_type'] = 'CNC'

                elif (order['exchange_code'] == 'NSE' or order['exchange_code'] == 'BSE') and order['product_type'] == 'BTST':
                    order['product_type'] = 'CNC'

                elif (order['exchange_code'] == 'NSE' or order['exchange_code'] == 'BSE') and order['product_type'] == 'EATM':
                    order['product_type'] = 'CNC'
                
                elif order['exchange_code'] in ['NFO', 'MCX', 'BFO', 'CDS'] and order['product_type'] == 'Futures':
                    order['product_type'] = 'NRML'

                elif order['exchange_code'] in ['NFO', 'MCX', 'BFO', 'CDS'] and order['product_type'] == 'Options':
                    order['product_type'] = 'NRML'
                

                elif order['exchange_code'] in ['NFO', 'MCX', 'BFO', 'CDS'] and order['product_type'] == 'FurturePlus':
                    order['product_type'] = 'MIS'

                elif order['exchange_code'] in ['NFO', 'MCX', 'BFO', 'CDS'] and order['product_type'] == 'OptionPlus':
                    order['product_type'] = 'MIS'
            else:
                print(f"Symbol not found for Symbol {symbol} and exchange {exchange}. Keeping original trading symbol.")
                
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
            if order['action'] == 'Buy':
                total_buy_orders += 1
            elif order['action'] == 'Sell':
                total_sell_orders += 1
            
            # Count orders based on their status
            if order['status'] == 'Executed':
                order['status'] = 'completed'
                total_completed_orders += 1
            elif order['status'] == 'Ordered':
                order['status'] = 'open'
                total_open_orders += 1
            elif order['status'] == 'Rejected':
                order['status'] = 'rejected'
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

        def map_order_type(order):
            order_type = order.get("order_type", "")

            if order_type == "Limit":
                return "LIMIT"
            elif order_type == "Market":
                return "MARKET"
            elif order_type == "StopLoss":
                stoploss = order.get("stoploss", "")
                if stoploss in ['0.00', '0', '0.0']:
                    return "SL-MKT"
                else:
                    return "SL"
            else:
                return ""
            
        mapped_order_type = map_order_type(order)

        transformed_order = {
            "symbol": order.get("stock_code", ""),
            "exchange": order.get("exchange_code", ""),
            "action": order.get("action", "").upper(),
            "quantity": order.get("quantity", 0),
            "price": order.get("price", 0.0),
            "trigger_price": order.get("trigger_price", 0.0),
            "pricetype": mapped_order_type,
            "product": order.get("product_type", ""),
            "orderid": order.get("order_id", ""),
            "order_status": order.get("status", ""),
            "timestamp": order.get("order_datetime", "")
        }

        transformed_orders.append(transformed_order)

    return transformed_orders

def map_trade_data(trade_data):
    """
    Processes and modifies a list of trade dictionaries based on specific conditions.
    
    Parameters:
    - trade_data: A list of dictionaries, where each dictionary represents an trade.
    
    Returns:
    - The modified trade_data with updated 'symbol' and 'product' fields.
    """
        # Check if 'data' is None
    if trade_data['data']['trade_book'] is None:
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        print("No data available.")
        trade_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        trade_data = trade_data['data']['trade_book']
        #print(trade_data)
        


    if trade_data:
        for trade in trade_data:
            # Extract the instrument_token and exchange for the current trade
            right = ''
            expiry_date = ''

            exchange = trade['exchange_code']
            if exchange == "NFO":
                right = trade['right'].upper()
                expiry_date = trade['expiry_date'].upper()
            
            
            symbol = trade['stock_code']

            if exchange == "NFO" and right == "OTHERS":
                symbol = trade['stock_code'] + ":::" + expiry_date + ":::" + "FUT"
            elif exchange == "NFO" and (right == "CALL" or right == "PUT"):
                symbol = f"{trade['stock_code']}:::{expiry_date}:::{format_strike(trade['strike_price'])}:::{right}"

            
            
            # print(symbol)
            # print(exchange)
            # print(right)
            # print(expiry_date)
            
            # Use the get_symbol function to fetch the symbol from the database
            symbol_from_db = get_oa_symbol(symbol=symbol,exchange=exchange)
            
            # Check if a symbol was found; if so, update the trading_symbol in the current trade
            if symbol_from_db:
                trade['stock_code'] = symbol_from_db
                if (trade['exchange_code'] == 'NSE' or trade['exchange_code'] == 'BSE') and trade['product_type'] == 'Margin':
                    trade['product_type'] = 'MIS'

                elif (trade['exchange_code'] == 'NSE' or trade['exchange_code'] == 'BSE') and trade['product_type'] == 'Cash':
                    trade['product_type'] = 'CNC'

                elif (trade['exchange_code'] == 'NSE' or trade['exchange_code'] == 'BSE') and trade['product_type'] == 'BTST':
                    trade['product_type'] = 'CNC'

                elif (trade['exchange_code'] == 'NSE' or trade['exchange_code'] == 'BSE') and trade['product_type'] == 'EATM':
                    trade['product_type'] = 'CNC'
                
                elif trade['exchange_code'] in ['NFO', 'MCX', 'BFO', 'CDS'] and trade['product_type'] == 'Futures':
                    trade['product_type'] = 'NRML'

                elif trade['exchange_code'] in ['NFO', 'MCX', 'BFO', 'CDS'] and trade['product_type'] == 'Options':
                    trade['product_type'] = 'NRML'
                

                elif trade['exchange_code'] in ['NFO', 'MCX', 'BFO', 'CDS'] and trade['product_type'] == 'FurturePlus':
                    trade['product_type'] = 'MIS'

                elif trade['exchange_code'] in ['NFO', 'MCX', 'BFO', 'CDS'] and trade['product_type'] == 'OptionPlus':
                    trade['product_type'] = 'MIS'
            else:
                print(f"Symbol not found for Symbol {symbol} and exchange {exchange}. Keeping original trading symbol.")
                
    return trade_data



def transform_tradebook_data(tradebook_data):
    transformed_data = []

    def calculate_trade_value(trade):
        quantity = float(trade.get('quantity', 0))
        average_cost = float(trade.get('average_cost', 0.0))
        trade_value = quantity * average_cost
        return round(trade_value, 2)

    for trade in tradebook_data:
        transformed_trade = {
            "symbol": trade.get('stock_code', ''),
            "exchange": trade.get('exchange_code', ''),
            "product": trade.get('product_type', ''),
            "action": trade.get('action', '').upper(),
            "quantity": trade.get('quantity', 0),
            "average_price": trade.get('average_cost', "0.0"),
            "trade_value": calculate_trade_value(trade),
            "orderid": trade.get('order_id', ''),
            "timestamp": trade.get('trade_date', '')
        }
        transformed_data.append(transformed_trade)
    return transformed_data

def map_position_data(position_data):
    """
    Processes and modifies a list of position dictionaries based on specific conditions.
    
    Parameters:
    - position_data: A list of dictionaries, where each dictionary represents an position.
    
    Returns:
    - The modified position_data with updated 'symbol' and 'product' fields.
    """
        # Check if 'data' is None
    if position_data['Success'] is None:
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        print("No data available.")
        position_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        position_data = position_data['Success']
        #print(position_data)
        
  

    if position_data:
        for position in position_data:
            # Extract the instrument_token and exchange for the current position
            right = ''
            expiry_date = ''

            exchange = position['exchange_code']
            if exchange == "NFO":
                right = position['right'].upper()
                expiry_date = position['expiry_date'].upper()
            
            
            symbol = position['stock_code']



            if exchange == "NFO" and right == "OTHERS":
                symbol = position['stock_code'] + ":::" + expiry_date + ":::" + "FUT"
            elif exchange == "NFO" and (right == "CALL" or right == "PUT"):
                symbol = f"{position['stock_code']}:::{expiry_date}:::{position['strike_price']}:::{right}"

            
            
            # print(symbol)
            # print(exchange)
            # print(right)
            # print(expiry_date)
            
            # Use the get_symbol function to fetch the symbol from the database
            symbol_from_db = get_oa_symbol(symbol=symbol,exchange=exchange)
            print(symbol_from_db)
            
            # Check if a symbol was found; if so, update the trading_symbol in the current position
            if symbol_from_db:
                position['stock_code'] = symbol_from_db
                if (position['exchange_code'] == 'NSE' or position['exchange_code'] == 'BSE') and position['product_type'] == 'Margin':
                    position['product_type'] = 'MIS'

                elif (position['exchange_code'] == 'NSE' or position['exchange_code'] == 'BSE') and position['product_type'] == 'Cash':
                    position['product_type'] = 'CNC'

                elif (position['exchange_code'] == 'NSE' or position['exchange_code'] == 'BSE') and position['product_type'] == 'BTST':
                    position['product_type'] = 'CNC'

                elif (position['exchange_code'] == 'NSE' or position['exchange_code'] == 'BSE') and position['product_type'] == 'EATM':
                    position['product_type'] = 'CNC'
                
                elif position['exchange_code'] in ['NFO', 'MCX', 'BFO', 'CDS'] and position['product_type'] == 'Futures':
                    position['product_type'] = 'NRML'

                elif position['exchange_code'] in ['NFO', 'MCX', 'BFO', 'CDS'] and position['product_type'] == 'Options':
                    position['product_type'] = 'NRML'
                

                elif position['exchange_code'] in ['NFO', 'MCX', 'BFO', 'CDS'] and position['product_type'] == 'FurturePlus':
                    position['product_type'] = 'MIS'

                elif position['exchange_code'] in ['NFO', 'MCX', 'BFO', 'CDS'] and position['product_type'] == 'OptionPlus':
                    position['product_type'] = 'MIS'
            else:
                print(f"Symbol not found for Symbol {symbol} and exchange {exchange}. Keeping original trading symbol.")
                
    return position_data



def transform_positions_data(positions_data):
    transformed_data = []
    quantity = 0

    

    for position in positions_data:
        if(position.get('action', '')=='Buy'):
            quantity = int(position.get('quantity', 0))
        if(position.get('action', '')=='Sell'):
            quantity = int(position.get('quantity', 0))*-1
        transformed_position = {
            "symbol": position.get('stock_code', ''),
            "exchange": position.get('exchange_code', ''),
            "product": position.get('product_type', ''),
            "quantity": str(quantity),
            "average_price": position.get('average_price', 0.0),
        }
        transformed_data.append(transformed_position)
    return transformed_data

def transform_holdings_data(holdings_data):
    transformed_data = []
    for holdings in holdings_data:
        pnlpercent = ((float(holdings.get('current_market_price', 0.0)) - float(holdings.get('average_price', 0.0))) / float(holdings.get('average_price', 1.0))) * 100 if float(holdings.get('average_price', 0.0)) != 0 else 0

        transformed_position = {
            "symbol": holdings.get('stock_code', ''),
            "exchange": holdings.get('exchange_code', ''),
            "quantity": holdings.get('quantity', 0),
            "product": holdings.get('product_type', 'CNC'),
            "pnl": holdings.get('unrealized_profit', 0.0),
            "pnlpercent": pnlpercent
        }
        transformed_data.append(transformed_position)
    return transformed_data

    
def map_portfolio_data(portfolio_data):
    """
    Processes and modifies a list of Portfolio dictionaries based on specific conditions.
    
    Parameters:
    - portfolio_data: A list of dictionaries, where each dictionary represents an portfolio information.
    
    Returns:
    - The modified portfolio_data 
    """
        # Check if 'data' is None
    if portfolio_data['data']['holdings'] is None:
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        print("No data available.")
        portfolio_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        portfolio_data = portfolio_data['data']['holdings']
        print(portfolio_data)
        


    if portfolio_data:
        for portfolio in portfolio_data:
            portfolio['product_type'] = 'CNC'
            # Extract the instrument_token and exchange for the current position
            stock_code = portfolio['stock_code']
            exchange = portfolio['exchange_code']
            
            # Use the get_symbol function to fetch the symbol from the database
            symbol_from_db = get_oa_symbol(symbol=stock_code,exchange=exchange)
            
            # Check if a symbol was found; if so, update the trading_symbol in the current position
            if symbol_from_db:
                portfolio['stock_code'] = symbol_from_db
                totalholdingvalue = float(portfolio['current_market_price']) * float(portfolio['quantity'])
                totalinvvalue = float(portfolio['average_price']) * float(portfolio['quantity'])
                totalprofitandloss = totalholdingvalue - totalinvvalue
                portfolio['unrealized_profit'] = round(totalprofitandloss,2)
                
    return portfolio_data


def calculate_portfolio_statistics(holdings_data):
    totalholdingvalue = sum(float(item['current_market_price']) * float(item['quantity']) for item in holdings_data)
    totalinvvalue = sum(float(item['average_price']) * float(item['quantity']) for item in holdings_data)
    totalprofitandloss = totalholdingvalue - totalinvvalue
    
    # To avoid division by zero in the case when total_investment_value is 0
    totalpnlpercentage = (totalprofitandloss / totalinvvalue * 100) if totalinvvalue else 0

    return {
        'totalholdingvalue': totalholdingvalue,
        'totalinvvalue': totalinvvalue,
        'totalprofitandloss': totalprofitandloss,
        'totalpnlpercentage': totalpnlpercentage
    }


