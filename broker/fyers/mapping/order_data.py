import json
from database.token_db import get_symbol , get_oa_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


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
    if not order_data or order_data.get('orderBook') is None:
        logger.debug("No order data available in 'orderBook'.")
        return []
    
    order_list = order_data['orderBook']

    for order in order_list:
        exchange_code = order.get('exchange')
        segment_code = order.get('segment')
        exchange = get_exchange(exchange_code, segment_code)
        symbol = order.get('symbol')
        
        if symbol:
            oa_symbol = get_oa_symbol(brsymbol=symbol, exchange=exchange)
            if oa_symbol:
                order['symbol'] = oa_symbol
                order['exchange'] = exchange
            else:
                logger.warning(f"Could not map Fyers brsymbol '{symbol}' for exchange '{exchange}'. Keeping original.")
        else:
            logger.warning(f"Symbol not found in order: {order}. Keeping original trading symbol.")
            
    return order_list


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
    if isinstance(orders, dict):
        orders = [orders]

    transformed_orders = []
    
    status_map = {2: "complete", 5: "rejected", 4: "trigger pending", 6: "open", 1: "cancelled"}
    side_map = {1: "BUY", -1: "SELL"}
    type_map = {1: "LIMIT", 2: "MARKET", 3: "SL-M", 4: "SL"}
    product_map = {"CNC": "CNC", "INTRADAY": "MIS", "MARGIN": "NRML", "CO": "CO", "BO": "BO"}

    for order in orders:
        if not isinstance(order, dict):
            logger.warning(f"Expected a dict, but found {type(order)}. Skipping this item.")
            continue

        order_status_code = order.get("status")
        order_status = status_map.get(order_status_code, "unknown")
        if order_status == "unknown":
            logger.warning(f"Unknown order status code '{order_status_code}' for order: {order.get('id')}")

        side_code = order.get("side")
        action = side_map.get(side_code, "unknown")
        if action == "unknown":
            logger.warning(f"Unknown side code '{side_code}' for order: {order.get('id')}")

        type_code = order.get("type")
        ordertype = type_map.get(type_code, "unknown")
        if ordertype == "unknown":
            logger.warning(f"Unknown order type code '{type_code}' for order: {order.get('id')}")
        
        product_code = order.get("productType")
        producttype = product_map.get(product_code, "unknown")
        if producttype == "unknown":
            logger.warning(f"Unknown product type '{product_code}' for order: {order.get('id')}")

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
    if not trade_data or trade_data.get('tradeBook') is None:
        logger.debug("No trade data available in 'tradeBook'.")
        return []
    
    trade_list = trade_data['tradeBook']

    for trade in trade_list:
        exchange_code = trade.get('exchange')
        segment_code = trade.get('segment')
        exchange = get_exchange(exchange_code, segment_code)
        symbol = trade.get('symbol')
        
        if symbol:
            oa_symbol = get_oa_symbol(brsymbol=symbol, exchange=exchange)
            if oa_symbol:
                trade['symbol'] = oa_symbol
                trade['exchange'] = exchange
            else:
                logger.warning(f"Could not map Fyers brsymbol '{symbol}' for exchange '{exchange}'. Keeping original.")
        else:
            logger.warning(f"Symbol not found in trade: {trade}. Keeping original trading symbol.")
            
    return trade_list

def transform_tradebook_data(tradebook_data):
    transformed_data = []
    side_map = {1: "BUY", -1: "SELL"}
    product_map = {"CNC": "CNC", "INTRADAY": "MIS", "MARGIN": "NRML", "CO": "CO", "BO": "BO"}

    for trade in tradebook_data:
        symbol = trade.get('symbol')
        
        side_code = trade.get("side")
        action = side_map.get(side_code, "unknown")
        if action == "unknown":
            logger.warning(f"Unknown side code '{side_code}' for trade: {trade.get('orderNumber')}")

        product_code = trade.get("productType")
        producttype = product_map.get(product_code, "unknown")
        if producttype == "unknown":
            logger.warning(f"Unknown product type '{product_code}' for trade: {trade.get('orderNumber')}")

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
    if not position_data or position_data.get('netPositions') is None:
        logger.debug("No position data available in 'netPositions'.")
        return []
    
    position_list = position_data['netPositions']
    logger.debug(f"Raw Fyers positions: {position_list}")

    for position in position_list:
        exchange_code = position.get('exchange')
        segment_code = position.get('segment')
        exchange = get_exchange(exchange_code, segment_code)
        symbol = position.get('symbol')
        
        if symbol:
            oa_symbol = get_oa_symbol(brsymbol=symbol, exchange=exchange)
            if oa_symbol:
                position['symbol'] = oa_symbol
                position['exchange'] = exchange
            else:
                logger.warning(f"Could not map Fyers brsymbol '{symbol}' for exchange '{exchange}'. Keeping original.")
        else:
            logger.warning(f"Symbol not found in position: {position}. Keeping original trading symbol.")
            
    return position_list
    

def transform_positions_data(positions_data):
    transformed_data = [] 

    for position in positions_data:
        # Ensure average_price is treated as a float, then format to a string with 2 decimal places
        average_price_formatted = "{:.2f}".format(float(position.get('netAvg', 0.0)))
        
        # Get LTP and PNL from Fyers response
        ltp = "{:.2f}".format(float(position.get('ltp', 0.0)))
        pnl = "{:.2f}".format(float(position.get('pl', 0.0)))

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
            "ltp": ltp,
            "pnl": pnl
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
    if not portfolio_data or portfolio_data.get('holdings') is None:
        logger.debug("No portfolio data available in 'holdings'.")
        return []
    
    portfolio_list = portfolio_data['holdings']
    logger.debug(f"Raw Fyers portfolio: {portfolio_list}")

    for portfolio in portfolio_list:
        if portfolio.get('holdingType') in ('HLD', 'T1'):
            portfolio['holdingType'] = 'CNC'
        else:
            logger.warning(f"Fyers Portfolio - Unknown product value for delivery: {portfolio.get('holdingType')}")
        
        exchange_code = portfolio.get('exchange')
        segment_code = portfolio.get('segment')
        exchange = get_exchange(exchange_code, segment_code)
        symbol = portfolio.get('symbol')

        if symbol:
            oa_symbol = get_oa_symbol(brsymbol=symbol, exchange=exchange)
            if oa_symbol:
                portfolio['symbol'] = oa_symbol
                portfolio['exchange'] = exchange
            else:
                logger.warning(f"Could not map Fyers brsymbol '{symbol}' for exchange '{exchange}'. Keeping original.")
        else:
            logger.warning(f"Symbol not found in portfolio holding: {portfolio}. Keeping original trading symbol.")
            
    return portfolio_list


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


