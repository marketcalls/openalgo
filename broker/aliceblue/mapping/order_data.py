import json
from database.token_db import get_symbol , get_oa_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


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
            logger.info(f"Error fetching order data: {order_data['emsg']}")
            order_data = {}
    else:
        order_data = order_data
        
    # logger.info(f"{order_data}")

    if order_data:
        for order in order_data:
            # Extract the instrument_token and exchange for the current order
            exchange = order['Exchange']
            symbol = order['Trsym']
       
            
            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol:
                order['Trsym'] = get_oa_symbol(brsymbol=symbol, exchange=exchange)
            else:
                logger.info(f"{symbol} and exchange {exchange} not found. Keeping original trading symbol.")
                
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
    logger.info(f"{orders}")
    for order in orders:
        # Make sure each item is indeed a dictionary
        if not isinstance(order, dict):
            logger.warning(f"Warning: Expected a dict, but found a {type(order)}. Skipping this item.")
            continue
        
        # Check if the necessary keys exist in the order
        if 'Trantype' not in order or 'Prctype' not in order:
            logger.error("Error: Missing required keys in the order. Skipping this item.")
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
    # Log the raw tradebook response
    logger.info(f"Raw tradebook response type: {type(trade_data)}")
    if trade_data:
        if isinstance(trade_data, list) and len(trade_data) > 0:
            logger.info(f"First trade in raw response: {trade_data[0]}")
            # Log all available fields in first trade
            logger.info(f"Available fields in first trade: {list(trade_data[0].keys()) if trade_data[0] else 'No fields'}")
        elif isinstance(trade_data, dict):
            logger.info(f"Raw response is dict: {trade_data}")

    if isinstance(trade_data, dict):
        if trade_data.get('stat') == 'Not_Ok':
            # Handle the case where there is an error in the data
            # For example, you might want to display an error message to the user
            # or pass an empty list or dictionary to the template.
            logger.info(f"Error fetching order data: {trade_data['emsg']}")
            trade_data = {}
    else:
        trade_data = trade_data

    # Log the data being processed
    logger.info(f"Number of trades to process: {len(trade_data) if trade_data else 0}")

    if trade_data:
        for trade in trade_data:
            # Extract the instrument_token and exchange for the current trade
            exchange = trade['Exchange']
            symbol = trade['Tsym']
            
            # Check if a symbol was found; if so, update the trading_symbol in the current trade
            if symbol:
                trade['Tsym'] = get_oa_symbol(brsymbol=symbol, exchange=exchange)
            else:
                logger.info(f"{symbol} and exchange {exchange} not found. Keeping original trading symbol.")
                
    return trade_data

def transform_tradebook_data(tradebook_data):
    transformed_data = []
    for trade in tradebook_data:

        # Ensure quantity and average price are converted to the correct types
        quantity = int(trade.get('Qty', 0))
        # AliceBlue uses 'AvgPrice' field (no space) for average price in tradebook
        average_price = float(trade.get('AvgPrice', 0.0))

        # Log if we got the price
        if average_price > 0:
            logger.debug(f"Got average price: {average_price} for qty: {quantity}")
        else:
            logger.warning(f"Zero or missing AvgPrice. Raw value: {trade.get('AvgPrice')}")
        
        # Map transaction type from 'B'/'S' to 'BUY'/'SELL'
        trantype = trade.get('Trantype', '')
        if trantype == 'B':
            action = 'BUY'
        elif trantype == 'S':
            action = 'SELL'
        else:
            action = trantype
        
        transformed_trade = {
            "symbol": trade.get('Tsym'),
            "exchange": trade.get('Exchange', ''),
            "product": trade.get('Pcode', ''),
            "action": action,
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
            logger.info(f"Error fetching order data: {position_data['emsg']}")
            position_data = {}
    else:
        position_data = position_data
        
    # logger.info(f"{order_data}")

    if position_data:
        for position in position_data:
            # Extract the instrument_token and exchange for the current order
            exchange = position['Exchange']
            symbol = position['Tsym']
       
            
            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol:
                position['Tsym'] = get_oa_symbol(brsymbol=symbol, exchange=exchange)
            else:
                logger.info(f"{symbol} and exchange {exchange} not found. Keeping original trading symbol.")
                
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
    
    # Return empty list if holdings_data is not a list
    if not isinstance(holdings_data, list):
        logger.warning(f"Holdings data is not a list: {type(holdings_data)}")
        return []
    
    for holdings in holdings_data:
        # Skip if holdings is not a dictionary
        if not isinstance(holdings, dict):
            logger.warning(f"Skipping invalid holdings item: {holdings}")
            continue
            
        try:
            ltp = float(holdings.get('Ltp', 0))
            price = float(holdings.get('Price', 0.0))
            quantity = int(holdings.get('Holdqty', holdings.get('HUqty', 0)))

            pnl = round((ltp - price) * quantity, 2) if quantity else 0
            pnlpercent = round(((ltp - price) / price * 100), 2) if price else 0

            transformed_position = {
                "symbol": holdings.get('Bsetsym', holdings.get('Symbol', '')),
                "exchange": holdings.get('ExchSeg1', holdings.get('Exchange', '')),
                "quantity": quantity,
                "product": holdings.get('Pcode', 'CNC'),
                "pnl": pnl,  # Rounded to two decimals
                "pnlpercent": pnlpercent  # Rounded to two decimals
            }
            transformed_data.append(transformed_position)
        except (KeyError, TypeError, ValueError) as e:
            logger.error(f"Error transforming holdings item: {e}, Item: {holdings}")
            continue
            
    return transformed_data


    
def map_portfolio_data(portfolio_data):
    """
    Processes and modifies a list of Portfolio dictionaries based on specific conditions.
    
    Parameters:
    - portfolio_data: A list of dictionaries, where each dictionary represents an portfolio information.
    
    Returns:
    - The modified portfolio_data with  'product' fields.
    """
    
    # Check if portfolio_data is a string (might be JSON string)
    if isinstance(portfolio_data, str):
        try:
            import json
            portfolio_data = json.loads(portfolio_data)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse portfolio_data as JSON: {portfolio_data}")
            return []
    
    # Check if 'data' is None
    if isinstance(portfolio_data, dict):
        if portfolio_data.get('stat') == 'Not_Ok':
            # Handle the case where there is no data
            logger.info("No data available or error in response.")
            return []
        elif 'HoldingVal' in portfolio_data:
            portfolio_data = portfolio_data['HoldingVal']
        # If it's a dict but doesn't have 'HoldingVal', assume it's the holdings data itself
    elif isinstance(portfolio_data, list):
        # If it's already a list, use it as is
        pass
    else:
        logger.error(f"Unexpected portfolio_data type: {type(portfolio_data)}")
        return []
        
    logger.info(f"Processing portfolio data: {portfolio_data}")

    if portfolio_data and isinstance(portfolio_data, list):
        for portfolio in portfolio_data:
            if isinstance(portfolio, dict) and portfolio.get('Pcode') == 'CNC':
                portfolio['Pcode'] = 'CNC'
            else:
                logger.info("AliceBlue Portfolio - Product Value for Delivery Not Found or Changed.")
                
    return portfolio_data if isinstance(portfolio_data, list) else []

def calculate_portfolio_statistics(holdings_data):
    # Return empty statistics if holdings_data is empty or not a list
    if not holdings_data or not isinstance(holdings_data, list):
        return {
            'totalholdingvalue': 0,
            'totalinvvalue': 0,
            'totalprofitandloss': 0,
            'totalpnlpercentage': 0
        }
    
    try:
        totalholdingvalue = sum(float(item.get('Ltp', 0)) * int(item.get('HUqty', item.get('Holdqty', 0))) for item in holdings_data)
        totalinvvalue = sum(float(item.get('Price', 0)) * int(item.get('HUqty', item.get('Holdqty', 0))) for item in holdings_data)
        totalprofitandloss = sum((float(item.get('Ltp', 0)) - float(item.get('Price', 0))) * int(item.get('HUqty', item.get('Holdqty', 0))) for item in holdings_data)
        
        for item in holdings_data:
            logger.info(f"Holdings item: LTP={item.get('Ltp')}, Price={item.get('Price')}, Qty={item.get('HUqty', item.get('Holdqty'))}")
        # To avoid division by zero in the case when totalinvvalue is 0
        totalpnlpercentage = (totalprofitandloss / totalinvvalue * 100) if totalinvvalue else 0
    except (KeyError, TypeError, ValueError) as e:
        logger.error(f"Error calculating portfolio statistics: {e}")
        return {
            'totalholdingvalue': 0,
            'totalinvvalue': 0,
            'totalprofitandloss': 0,
            'totalpnlpercentage': 0
        }

    return {
        'totalholdingvalue': totalholdingvalue,
        'totalinvvalue': totalinvvalue,
        'totalprofitandloss': totalprofitandloss,
        'totalpnlpercentage': totalpnlpercentage
    }



