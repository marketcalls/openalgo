import json
from database.token_db import get_symbol 
from broker.dhan.mapping.transform_data import map_exchange
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
        # Check if 'data' is None
    if order_data is None:
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        logger.info("No data available.")
        order_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        order_data = order_data
        


    if order_data:
        for order in order_data:
            # Extract the instrument_token and exchange for the current order
            instrument_token = order['securityId']
            exchange = map_exchange(order['exchangeSegment'])
            order['exchangeSegment'] = exchange
            
            # Use the get_symbol function to fetch the symbol from the database
            symbol_from_db = get_symbol(instrument_token, exchange)
            
            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol_from_db:
                order['tradingSymbol'] = symbol_from_db
                if (order['exchangeSegment'] == 'NSE' or order['exchangeSegment'] == 'BSE') and order['productType'] == 'CNC':
                    order['productType'] = 'CNC'
                               
                elif order['productType'] == 'INTRADAY':
                    order['productType'] = 'MIS'
                
                elif order['exchangeSegment'] in ['NFO', 'MCX', 'BFO', 'CDS'] and order['productType'] == 'MARGIN':
                    order['productType'] = 'NRML'
            else:
                logger.warning(f"Symbol not found for token {instrument_token} and exchange {exchange}. Keeping original trading symbol.")
                
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
            if order['transactionType'] == 'BUY':
                total_buy_orders += 1
            elif order['transactionType'] == 'SELL':
                total_sell_orders += 1
            
            # Count orders based on their status
            if order['orderStatus'] == 'TRADED':
                total_completed_orders += 1
                order['orderStatus'] = 'complete'
            elif order['orderStatus'] == 'PENDING':
                total_open_orders += 1
                order['orderStatus'] = 'open'
            elif order['orderStatus'] == 'REJECTED':
                total_rejected_orders += 1
                order['orderStatus'] = 'rejected'
            elif order['orderStatus'] == 'CANCELLED':
                order['orderStatus'] = 'cancelled'

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
            logger.warning(f"Warning: Expected a dict, but found a {type(order)}. Skipping this item.")
            continue

        if order['orderType'] == 'MARKET':
                order['orderType'] = 'MARKET'
        if order['orderType'] == 'LIMIT':
                order['orderType'] = 'LIMIT'
        if order['orderType'] == 'STOP_LOSS':
                order['orderType'] = 'SL'
        if order['orderType'] == 'STOP_LOSS_MARKET':
                order['orderType'] = 'SL-M'


        transformed_order = {
            "symbol": order.get("tradingSymbol", ""),
            "exchange": order.get("exchangeSegment", ""),
            "action": order.get("transactionType", ""),
            "quantity": order.get("quantity", 0),
            "price": order.get("price", 0.0),
            "trigger_price": order.get("triggerPrice", 0.0),
            "pricetype": order.get("orderType", ""),
            "product": order.get("productType", ""),
            "orderid": order.get("orderId", ""),
            "order_status": order.get("orderStatus", ""),
            "timestamp": order.get("updateTime", "")
        }

        transformed_orders.append(transformed_order)

    return transformed_orders

def map_trade_data(trade_data):
    return map_order_data(trade_data)

def transform_tradebook_data(tradebook_data):
    transformed_data = []
    for trade in tradebook_data:
        transformed_trade = {
            "symbol": trade.get('tradingSymbol', ''),
            "exchange": trade.get('exchangeSegment', ''),
            "product": trade.get('productType', ''),
            "action": trade.get('transactionType', ''),
            "quantity": trade.get('tradedQuantity', 0),
            "average_price": trade.get('tradedPrice', 0.0),
            "trade_value": trade.get('tradedQuantity', 0) * trade.get('tradedPrice', 0.0),
            "orderid": trade.get('orderId', ''),
            "timestamp": trade.get('updateTime', '')
        }
        transformed_data.append(transformed_trade)
    return transformed_data

def map_position_data(position_data):
    return map_order_data(position_data)


def transform_positions_data(positions_data):
    transformed_data = []
    for position in positions_data:
        transformed_position = {
            "symbol": position.get('tradingSymbol', ''),
            "exchange": position.get('exchangeSegment', ''),
            "product": position.get('productType', ''),
            "quantity": position.get('netQty', 0),
            "average_price": position.get('costPrice', 0.0),
        }
        transformed_data.append(transformed_position)
    return transformed_data

def transform_holdings_data(holdings_data):
    transformed_data = []
    for holdings in holdings_data:
        transformed_position = {
            "symbol": holdings.get('tradingSymbol', ''),
            "exchange": holdings.get('exchange', ''),
            "quantity": holdings.get('totalQty', 0),
            "product": 'CNC',
            "pnl": 0.0,
            "pnlpercent": 0.0
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
    # Check if 'portfolio_data' is empty
    if portfolio_data is None or isinstance(portfolio_data,dict) and (
        portfolio_data.get('errorCode') == "DHOLDING_ERROR" or
        portfolio_data.get('internalErrorCode') == "DH-1111" or
        portfolio_data.get('internalErrorMessage') == "No holdings available"):
        # Handle the case where there is no data or specific error message about no holdings
        logger.info("No data or no holdings available.")
        portfolio_data = {}  # This resets portfolio_data to an empty dictionary if conditions are met

    return portfolio_data


def calculate_portfolio_statistics(holdings_data):
    totalholdingvalue = sum(item['avgCostPrice'] * item['totalQty'] for item in holdings_data)
    totalinvvalue = sum(item['avgCostPrice'] * item['totalQty'] for item in holdings_data)
    totalprofitandloss = 0
    
    # To avoid division by zero in the case when total_investment_value is 0
    totalpnlpercentage = (totalprofitandloss / totalinvvalue * 100) if totalinvvalue else 0

    return {
        'totalholdingvalue': totalholdingvalue,
        'totalinvvalue': totalinvvalue,
        'totalprofitandloss': totalprofitandloss,
        'totalpnlpercentage': totalpnlpercentage
    }


