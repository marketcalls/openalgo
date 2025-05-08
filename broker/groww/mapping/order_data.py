import json
import logging
from database.token_db import get_symbol 
from broker.dhan.mapping.transform_data import map_exchange

def map_order_data(order_data):
    """
    Processes and modifies order data from Groww format to OpenAlgo format.
    
    Parameters:
    - order_data: A dictionary with either 'data' key or raw Groww API response with 'order_list'.
    
    Returns:
    - The modified order_data with standardized fields in OpenAlgo format.
    """
    logging.info("Starting map_order_data function")
    logging.debug(f"Order data type: {type(order_data)}")
    
    # Initialize empty result
    mapped_orders = []
    
    # Handle empty input
    if not order_data:
        logging.warning("Order data is None or empty")
        return mapped_orders
    
    # Determine which data source to use
    orders_to_process = None
    
    # For debugging, log all keys in the structure
    if isinstance(order_data, dict):
        logging.debug(f"Keys in order_data: {list(order_data.keys())}")
        if 'raw_response' in order_data and isinstance(order_data['raw_response'], dict):
            logging.debug(f"Keys in raw_response: {list(order_data['raw_response'].keys())}")
    
    # Try raw_response (direct Groww API format) first if it exists
    if isinstance(order_data, dict) and 'raw_response' in order_data and order_data['raw_response']:
        raw_response = order_data['raw_response']
        if 'order_list' in raw_response and raw_response['order_list']:
            logging.info("Using raw_response.order_list for mapping")
            orders_to_process = raw_response['order_list']
    
    # Then try the data array if raw_response wasn't available or was empty
    if not orders_to_process and isinstance(order_data, dict) and 'data' in order_data:
        if order_data['data']:
            logging.info("Using data array for mapping")
            orders_to_process = order_data['data']
    
    # Handle direct order_list format (from Groww API)
    if not orders_to_process and isinstance(order_data, dict) and 'order_list' in order_data:
        if order_data['order_list']:
            logging.info("Using direct order_list for mapping")
            orders_to_process = order_data['order_list']
    
    # If no valid orders found, return empty result
    if not orders_to_process:
        logging.warning("No valid orders found for mapping")
        return mapped_orders
        
    logging.info(f"Processing {len(orders_to_process)} orders")
    
    for i, order in enumerate(orders_to_process):
        logging.debug(f"Processing order {i+1}/{len(orders_to_process)}")
        logging.debug(f"Original order: {order}")
        
        # Get fields from order - handle both original Groww API and our standardized format
        order_id = order.get('groww_order_id', order.get('orderid', ''))
        symbol = order.get('trading_symbol', order.get('tradingsymbol', ''))
        status = order.get('order_status', order.get('status', ''))
        remark = order.get('remark', order.get('remarks', ''))
        order_type = order.get('order_type', order.get('pricetype', 'MARKET'))
        transaction_type = order.get('transaction_type', order.get('action', ''))
        product = order.get('product', '')
        timestamp = order.get('created_at', order.get('timestamp', ''))
        
        # For debugging
        if i == 0:
            logging.debug(f"Sample order id: {order_id}, symbol: {symbol}, type: {order_type}")
        
        mapped_order = {
            'orderid': order_id,
            'tradingsymbol': symbol,
            'status': status,
            'remarks': remark,
            'quantity': order.get('quantity', 0),
            'price': order.get('price', 0),
            'trigger_price': order.get('trigger_price', 0),
            'filled_quantity': order.get('filled_quantity', 0),
            'remaining_quantity': order.get('remaining_quantity', 0),
            'average_price': order.get('average_fill_price', 0),
            'validity': order.get('validity', 'DAY'),
            'exchange': order.get('exchange', 'NSE'),
            'order_type': order_type,
            'transaction_type': transaction_type,
            'product': product,
            'order_timestamp': timestamp,
            'exchange_timestamp': order.get('exchange_time', ''),
            'order_reference_id': order.get('order_reference_id', '')
        }
        
        # Map status to OpenAlgo format
        status_map = {
            'NEW': 'open',
            'ACKED': 'open',
            'OPEN': 'open',  # Added OPEN status from Groww API
            'TRIGGER_PENDING': 'trigger pending',
            'APPROVED': 'open',
            'EXECUTED': 'complete',
            'COMPLETED': 'complete',
            'CANCELLED': 'cancelled',
            'REJECTED': 'rejected'
        }
        original_status = mapped_order['status']
        mapped_order['status'] = status_map.get(original_status, 'open')
        logging.debug(f"Mapped status from '{original_status}' to '{mapped_order['status']}'")
        
        # Map product type to OpenAlgo format
        original_product = mapped_order['product']
        if original_product == 'CNC':
            mapped_order['product'] = 'CNC'
        elif original_product == 'INTRADAY':
            mapped_order['product'] = 'MIS'
        elif original_product == 'MARGIN':
            mapped_order['product'] = 'NRML'
        
        logging.debug(f"Mapped product from '{original_product}' to '{mapped_order['product']}'")
        logging.debug(f"Mapped order: {mapped_order}")
            
        mapped_orders.append(mapped_order)
    
    logging.info(f"Finished mapping {len(mapped_orders)} orders")
    return mapped_orders


def calculate_order_statistics(order_data):
    """
    Calculates statistics from order data, including totals for buy orders, sell orders,
    completed orders, open orders, and rejected orders.

    Parameters:
    - order_data: Can be either:
      1. A list of order dictionaries (direct from get_order_book)
      2. A dictionary with nested data structures (for backward compatibility)

    Returns:
    - A dictionary containing counts of different types of orders.
    """
    logging.info("Starting calculate_order_statistics")
    logging.debug(f"Order data type: {type(order_data)}")
    
    # Initialize counters
    total_buy_orders = total_sell_orders = 0
    total_completed_orders = total_open_orders = total_rejected_orders = 0

    # Default empty statistics
    default_stats = {
        'total_buy_orders': 0,
        'total_sell_orders': 0,
        'total_completed_orders': 0,
        'total_open_orders': 0,
        'total_rejected_orders': 0
    }

    # Handle empty input
    if not order_data:
        logging.warning("Order data is None or empty in calculate_order_statistics")
        return default_stats
    
    # Determine which data structure we're dealing with
    orders_to_process = None
    
    # Case 1: Direct list of orders (preferred new format)
    if isinstance(order_data, list):
        logging.info("Using direct list of orders for statistics")
        orders_to_process = order_data
    # Case 2: Nested dictionary with 'data' key (backward compatibility)
    elif isinstance(order_data, dict) and 'data' in order_data:
        logging.info("Using nested data dictionary for statistics")
        orders_to_process = order_data['data']
    # Case 3: Direct Groww API response with 'order_list' (original API format)
    elif isinstance(order_data, dict) and 'order_list' in order_data:
        logging.info("Using direct order_list for statistics")
        orders_to_process = order_data['order_list']
    
    # If no valid order data found, return default stats
    if not orders_to_process:
        logging.warning("No valid orders found for statistics calculation")
        return default_stats
        
    logging.info(f"Calculating statistics for {len(orders_to_process)} orders")

    for i, order in enumerate(orders_to_process):
        # Log the structure of the first order for debugging
        if i == 0:
            logging.debug(f"Sample order structure for statistics: {order}")
            
        # Count buy and sell orders
        transaction_type = order.get('transaction_type')
        if transaction_type == 'BUY':
            total_buy_orders += 1
        elif transaction_type == 'SELL':
            total_sell_orders += 1
        else:
            logging.debug(f"Unknown transaction type: {transaction_type}")
        
        # Count orders based on their status
        status = order.get('order_status')
        if status in ['EXECUTED', 'COMPLETED']:
            total_completed_orders += 1
        elif status in ['NEW', 'ACKED', 'APPROVED', 'OPEN']:
            total_open_orders += 1
        elif status == 'REJECTED':
            total_rejected_orders += 1
        else:
            logging.debug(f"Order with status not counted in statistics: {status}")

    # Compile statistics
    stats = {
        'total_buy_orders': total_buy_orders,
        'total_sell_orders': total_sell_orders,
        'total_completed_orders': total_completed_orders,
        'total_open_orders': total_open_orders,
        'total_rejected_orders': total_rejected_orders
    }
    
    logging.info(f"Order statistics calculated: {stats}")
    return stats


def transform_order_data(orders):
    """
    Transform order data from Groww API format to OpenAlgo standard format
    
    Args:
        orders (dict): Order data from Groww API 
        
    Returns:
        list: Transformed orders in OpenAlgo format for orderbook.py
    """
    logging.info("Starting transform_order_data function")
    logging.debug(f"Input order data type: {type(orders)}")
    
    # If we get a list directly, these are already mapped orders from map_order_data
    if isinstance(orders, list):
        logging.info(f"Received {len(orders)} pre-mapped orders")
        orders_to_process = orders
    else:
        # Try to extract orders from different possible structures
        orders_to_process = []
        
        # If orders is None or empty, return empty list
        if not orders:
            logging.warning("Orders input is None or empty")
            return []
        
        # Handle dictionary structures with data or order_list
        if isinstance(orders, dict):
            # Log keys for debugging
            logging.debug(f"Keys in orders: {list(orders.keys()) if orders else 'None'}")
            
            # Try raw_response.order_list format
            if 'raw_response' in orders and orders['raw_response']:
                raw_response = orders['raw_response']
                logging.debug(f"Raw response keys: {list(raw_response.keys()) if raw_response else 'None'}")
                if 'order_list' in raw_response and raw_response['order_list']:
                    logging.info("Using raw_response.order_list for transformation")
                    orders_to_process = raw_response['order_list']
            
            # Try data array format
            if not orders_to_process and 'data' in orders and orders['data']:
                logging.info("Using data array for transformation")
                orders_to_process = orders['data']
            
            # Try direct order_list format
            if not orders_to_process and 'order_list' in orders and orders['order_list']:
                logging.info("Using direct order_list for transformation")
                orders_to_process = orders['order_list']
    
    # If we still couldn't find orders, return empty list
    if not orders_to_process:
        logging.warning("No valid orders found for transformation")
        return []
    
    logging.info(f"Processing {len(orders_to_process)} orders for transformation")
    transformed_orders = []
    
    # Dump first order for debug
    if len(orders_to_process) > 0:
        logging.debug(f"Sample order to transform: {orders_to_process[0]}")
    
    for i, order in enumerate(orders_to_process):
        # Get fields with fallbacks between original and mapped formats
        order_id = order.get('groww_order_id', order.get('orderid', ''))
        symbol = order.get('trading_symbol', order.get('tradingsymbol', ''))
        status = order.get('order_status', order.get('status', ''))
        order_type = order.get('order_type', order.get('pricetype', 'MARKET'))
        transaction_type = order.get('transaction_type', order.get('action', ''))
        product = order.get('product', order.get('product', 'CNC'))
        timestamp = order.get('created_at', order.get('timestamp', order.get('order_timestamp', '')))
        price = order.get('price', 0.0)
        trigger_price = order.get('trigger_price', 0.0)
        quantity = order.get('quantity', 0)
        
        # Map order type to OpenAlgo format
        mapped_order_type = order_type
        if order_type == 'STOP_LOSS':
            mapped_order_type = 'SL'
        elif order_type == 'STOP_LOSS_MARKET':
            mapped_order_type = 'SL-M'
        
        # Map product type
        mapped_product = product
        if product == 'INTRADAY':
            mapped_product = 'MIS'
        elif product == 'MARGIN':
            mapped_product = 'NRML'
        
        # Map status
        status_map = {
            'NEW': 'open',
            'ACKED': 'open',
            'OPEN': 'open',
            'TRIGGER_PENDING': 'trigger pending',
            'APPROVED': 'open',
            'EXECUTED': 'complete',
            'COMPLETED': 'complete',
            'CANCELLED': 'cancelled',
            'REJECTED': 'rejected'
        }
        mapped_status = status_map.get(status, '')
        
        # Log key fields for debugging
        logging.debug(f"Order {i}: Symbol='{symbol}', ID='{order_id}', Type='{mapped_order_type}', Product='{mapped_product}'")
        
        # Create transformed order in OpenAlgo format
        transformed_order = {
            "symbol": symbol,  # This is the field that was showing empty in logs
            "exchange": order.get("exchange", "NSE"),
            "action": transaction_type,
            "quantity": quantity,
            "price": price,
            "trigger_price": trigger_price,
            "pricetype": mapped_order_type,
            "product": mapped_product,
            "orderid": order_id,
            "order_status": mapped_status,
            "timestamp": timestamp
        }
        
        # Add to result
        transformed_orders.append(transformed_order)

    logging.info(f"Successfully transformed {len(transformed_orders)} orders")
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
        print("No data or no holdings available.")
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


