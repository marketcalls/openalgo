import json
from database.token_db import get_symbol 
from broker.indmoney.mapping.transform_data import map_exchange
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
    try:
        # Check if 'data' is None
        if order_data is None:
            # Handle the case where there is no data
            logger.info("No data available.")
            return []  # Return empty list since we expect a list of orders
        
        # Check if order_data is an error response (dict with status)
        if isinstance(order_data, dict) and 'status' in order_data:
            if order_data.get('status') in ['error', 'failure']:
                logger.error(f"Error in order data: {order_data.get('message', 'Unknown error')}")
                return []
        
        # Check if order_data is a string (unexpected response)
        if isinstance(order_data, str):
            logger.error(f"Received string response instead of order data: {order_data[:200]}...")
            return []
        
        # Ensure order_data is a list
        if not isinstance(order_data, list):
            logger.warning(f"Expected list but got {type(order_data)}: {order_data}")
            return []
            
        if order_data:
            for order in order_data:
                # Ensure each order is a dictionary
                if not isinstance(order, dict):
                    logger.warning(f"Skipping non-dictionary order: {type(order)}")
                    continue
                    
                # Extract the instrument_token and exchange for the current order
                # Handle new IndMoney API format
                instrument_token = order.get('security_id')
                exchange = map_exchange(order.get('exchange', ''))
                
                # Map new format to expected format for consistency
                order['exchangeSegment'] = exchange
                order['securityId'] = instrument_token
                order['transactionType'] = order.get('txn_type', '').upper()
                order['productType'] = order.get('product', '')
                order['orderType'] = order.get('order_type', '').upper()
                order['orderStatus'] = order.get('status', '').upper()
                order['orderId'] = order.get('id', '')
                order['quantity'] = order.get('requested_qty', 0)
                order['price'] = order.get('requested_price', 0.0)
                order['triggerPrice'] = order.get('sl_trigger_price', 0.0)
                order['updateTime'] = order.get('created_at', '')
                
                # Use the get_symbol function to fetch the symbol from the database
                if instrument_token:
                    symbol_from_db = get_symbol(instrument_token, exchange)
                    
                    # Check if a symbol was found; if so, update the trading_symbol in the current order
                    if symbol_from_db:
                        order['tradingSymbol'] = symbol_from_db
                    else:
                        # Use the 'name' field from Indmoney API as fallback
                        order['tradingSymbol'] = order.get('name', '')
                        logger.warning(f"Symbol not found for token {instrument_token} and exchange {exchange}. Using name: {order.get('name', '')}")
                else:
                    # Use the 'name' field from Indmoney API
                    order['tradingSymbol'] = order.get('name', '')
                
                # Map product types
                if (order['exchangeSegment'] == 'NSE' or order['exchangeSegment'] == 'BSE') and order['productType'] == 'CNC':
                    order['productType'] = 'CNC'
                elif order['productType'] == 'INTRADAY':
                    order['productType'] = 'MIS'
                elif order['exchangeSegment'] in ['NFO', 'MCX', 'BFO', 'CDS'] and order['productType'] == 'MARGIN':
                    order['productType'] = 'NRML'
                    
        return order_data
        
    except Exception as e:
        logger.error(f"Exception in map_order_data: {e}")
        return []


def calculate_order_statistics(order_data):
    """
    Calculates statistics from order data, including totals for buy orders, sell orders,
    completed orders, open orders, and rejected orders.

    Parameters:
    - order_data: A list of dictionaries, where each dictionary represents an order.

    Returns:
    - A dictionary containing counts of different types of orders.
    """
    try:
        # Initialize counters
        total_buy_orders = total_sell_orders = 0
        total_completed_orders = total_open_orders = total_rejected_orders = 0

        # Handle None or non-list inputs
        if not order_data or not isinstance(order_data, list):
            return {
                'total_buy_orders': 0,
                'total_sell_orders': 0,
                'total_completed_orders': 0,
                'total_open_orders': 0,
                'total_rejected_orders': 0
            }

        for order in order_data:
            # Skip non-dictionary items
            if not isinstance(order, dict):
                continue
                
            # Count buy and sell orders
            if order.get('transactionType') == 'BUY':
                total_buy_orders += 1
            elif order.get('transactionType') == 'SELL':
                total_sell_orders += 1
            
            # Count orders based on their status - handle new Indmoney status values
            status = order.get('orderStatus', '').upper()
            if status in ['SUCCESS', 'TRADED']:
                total_completed_orders += 1
                order['orderStatus'] = 'complete'
            elif status in ['O-PENDING', 'PENDING']:
                total_open_orders += 1
                order['orderStatus'] = 'open'
            elif status in ['REJECTED']:
                total_rejected_orders += 1
                order['orderStatus'] = 'rejected'
            elif status in ['CANCELLED']:
                order['orderStatus'] = 'cancelled'

        # Compile and return the statistics
        return {
            'total_buy_orders': total_buy_orders,
            'total_sell_orders': total_sell_orders,
            'total_completed_orders': total_completed_orders,
            'total_open_orders': total_open_orders,
            'total_rejected_orders': total_rejected_orders
        }
    except Exception as e:
        logger.error(f"Exception in calculate_order_statistics: {e}")
        return {
            'total_buy_orders': 0,
            'total_sell_orders': 0,
            'total_completed_orders': 0,
            'total_open_orders': 0,
            'total_rejected_orders': 0
        }


def transform_order_data(orders):
    try:
        # Handle None input
        if orders is None:
            return []
            
        # Directly handling a dictionary assuming it's the structure we expect
        if isinstance(orders, dict):
            # Convert the single dictionary into a list of one dictionary
            orders = [orders]

        # Handle non-list inputs
        if not isinstance(orders, list):
            logger.warning(f"Expected list or dict but got {type(orders)}")
            return []

        transformed_orders = []
        
        for order in orders:
            # Make sure each item is indeed a dictionary
            if not isinstance(order, dict):
                logger.warning(f"Warning: Expected a dict, but found a {type(order)}. Skipping this item.")
                continue

            # Map order types to standard format
            order_type = order.get('orderType', '').upper()
            if order_type == 'MARKET':
                order['orderType'] = 'MARKET'
            elif order_type == 'LIMIT':
                order['orderType'] = 'LIMIT'
            elif order_type == 'STOP_LOSS':
                order['orderType'] = 'SL'
            elif order_type == 'STOP_LOSS_MARKET':
                order['orderType'] = 'SL-M'
            elif order_type == 'OCO':
                order['orderType'] = 'OCO'

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
    except Exception as e:
        logger.error(f"Exception in transform_order_data: {e}")
        return []

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
    """
    Processes and modifies position data from IndMoney API format.
    
    Parameters:
    - position_data: A flat list of position dictionaries (actual IndMoney API format)
    
    Returns:
    - A flat list of position dictionaries for compatibility
    """
    try:
        # Check if position_data is None
        if position_data is None:
            logger.info("No position data available.")
            return []
        
        # Check if position_data is an error response (dict with status)
        if isinstance(position_data, dict) and 'status' in position_data:
            if position_data.get('status') in ['error', 'failure']:
                logger.error(f"Error in position data: {position_data.get('message', 'Unknown error')}")
                return []
        
        # Check if position_data is a string (unexpected response)
        if isinstance(position_data, str):
            logger.error(f"Received string response instead of position data: {position_data[:200]}...")
            return []
        
        # Handle the actual IndMoney flat array format
        all_positions = []
        
        if isinstance(position_data, list):
            # Direct flat list from actual API
            all_positions = position_data
        elif isinstance(position_data, dict):
            # Fallback to handle documented nested format if it changes back
            net_positions = position_data.get('net_positions', [])
            day_positions = position_data.get('day_positions', [])
            all_positions = net_positions + day_positions
        else:
            logger.warning(f"Unexpected position data format: {type(position_data)}")
            return []
        
        processed_positions = []
        
        for position in all_positions:
            # Ensure each position is a dictionary
            if not isinstance(position, dict):
                logger.warning(f"Skipping non-dictionary position: {type(position)}")
                continue

            # Extract fields from actual IndMoney API format
            instrument_token = position.get('security_id')
            segment = position.get('segment', '')
            
            # Map segment to standard exchange format
            if segment == 'F&O' or segment == 'FUTURES':
                exchange = 'NFO'
            elif segment == 'EQUITY':
                exchange = 'NSE'  # Default for equity
            elif segment == 'COMMODITY':
                exchange = 'MCX'
            else:
                exchange = segment

            # Map actual IndMoney format to expected format for consistency
            position['exchangeSegment'] = exchange
            position['securityId'] = instrument_token
            position['tradingSymbol'] = position.get('symbol', '')
            position['netQty'] = position.get('net_qty', 0)
            position['avgCostPrice'] = position.get('avg_price', 0.0)
            position['lastTradedPrice'] = position.get('avg_price', 0.0)  # Using avg_price as placeholder
            position['marketValue'] = position.get('net_qty', 0) * position.get('avg_price', 0.0)
            position['pnlAbsolute'] = position.get('realized_profit', 0.0)
            position['multiplier'] = 1  # Default multiplier
            position['positionType'] = 'open' if position.get('net_qty', 0) != 0 else 'closed'
            
            # Determine product type based on actual API response
            api_product = position.get('product', '')
            if api_product == 'INTRADAY':
                position['productType'] = 'MIS'
            elif api_product == 'DELIVERY':
                position['productType'] = 'CNC'
            elif exchange in ['NFO', 'MCX', 'BFO', 'CDS']:
                position['productType'] = 'NRML'  # F&O positions are typically NRML
            else:
                position['productType'] = 'MIS'  # Default to MIS

            # Use the get_symbol function to fetch the symbol from the database
            if instrument_token and exchange:
                symbol_from_db = get_symbol(instrument_token, exchange)
                
                # Check if a symbol was found; if so, update the trading_symbol
                if symbol_from_db:
                    position['tradingSymbol'] = symbol_from_db
                else:
                    # Keep the existing symbol from IndMoney API
                    logger.warning(f"Symbol not found for token {instrument_token} and exchange {exchange}. Using: {position.get('symbol', '')}")

            processed_positions.append(position)

        return processed_positions
        
    except Exception as e:
        logger.error(f"Exception in map_position_data: {e}")
        return []


def transform_positions_data(positions_data):
    try:
        # Handle None input
        if positions_data is None:
            return []
            
        # Handle non-list inputs
        if not isinstance(positions_data, list):
            logger.warning(f"Expected list but got {type(positions_data)}")
            return []
            
        transformed_data = []
        for position in positions_data:
            # Ensure each position is a dictionary
            if not isinstance(position, dict):
                logger.warning(f"Skipping non-dictionary position: {type(position)}")
                continue
                
            transformed_position = {
                "symbol": position.get('tradingSymbol', ''),
                "exchange": position.get('exchangeSegment', ''),
                "product": position.get('productType', ''),
                "quantity": position.get('netQty', 0),
                "average_price": str(position.get('avgCostPrice', 0.0))  # OpenAlgo expects string format
            }
            transformed_data.append(transformed_position)
        return transformed_data
    except Exception as e:
        logger.error(f"Exception in transform_positions_data: {e}")
        return []

def transform_holdings_data(holdings_data):
    try:
        # Handle None input
        if holdings_data is None:
            return []
            
        # Handle non-list inputs
        if not isinstance(holdings_data, list):
            logger.warning(f"Expected list but got {type(holdings_data)}")
            return []
            
        transformed_data = []
        for holding in holdings_data:
            # Ensure each holding is a dictionary
            if not isinstance(holding, dict):
                logger.warning(f"Skipping non-dictionary holding: {type(holding)}")
                continue
                
            transformed_holding = {
                "symbol": holding.get('tradingSymbol', holding.get('symbol', '')),
                "exchange": holding.get('exchangeSegment', 'NSE'),  # Default to NSE
                "quantity": holding.get('totalQty', holding.get('total_qty', 0)),
                "product": 'CNC',  # Holdings are always CNC (Cash and Carry)
                "pnl": holding.get('pnlAbsolute', 0.0),
                "pnlpercent": holding.get('pnlPercent', 0.0)
            }
            transformed_data.append(transformed_holding)
        return transformed_data
    except Exception as e:
        logger.error(f"Exception in transform_holdings_data: {e}")
        return []

    
def map_portfolio_data(portfolio_data):
    """
    Processes and modifies a list of Portfolio dictionaries based on specific conditions.
    
    Parameters:
    - portfolio_data: A list of dictionaries, where each dictionary represents portfolio information.
    
    Returns:
    - The modified portfolio_data with updated fields.
    """
    try:
        # Check if 'portfolio_data' is None
        if portfolio_data is None:
            logger.info("No portfolio data available.")
            return []
        
        # Check if portfolio_data is an error response (dict with status)
        if isinstance(portfolio_data, dict) and 'status' in portfolio_data:
            if portfolio_data.get('status') in ['error', 'failure']:
                logger.error(f"Error in portfolio data: {portfolio_data.get('message', 'Unknown error')}")
                return []
        
        # Check if portfolio_data is a string (unexpected response)
        if isinstance(portfolio_data, str):
            logger.error(f"Received string response instead of portfolio data: {portfolio_data[:200]}...")
            return []
        
        # Ensure portfolio_data is a list
        if not isinstance(portfolio_data, list):
            logger.warning(f"Expected list but got {type(portfolio_data)}: {portfolio_data}")
            return []

        if portfolio_data:
            for holding in portfolio_data:
                # Ensure each holding is a dictionary
                if not isinstance(holding, dict):
                    logger.warning(f"Skipping non-dictionary holding: {type(holding)}")
                    continue

                # Extract the instrument_token from the actual Indmoney format
                instrument_token = holding.get('security_id')
                symbol = holding.get('symbol', '')
                
                # Map actual Indmoney format to expected format for consistency
                holding['securityId'] = instrument_token
                holding['tradingSymbol'] = symbol
                holding['totalQty'] = holding.get('total_qty', 0)
                holding['avgCostPrice'] = holding.get('avg_price', 0.0)
                holding['dpQty'] = holding.get('dp_qty', 0)  # Demat quantity
                holding['dpAvgPrice'] = holding.get('dp_avg_price', 0.0)
                holding['usedQty'] = holding.get('used_qty', 0)
                holding['t1Qty'] = holding.get('t1_qty', 0)
                holding['t1AvgPrice'] = holding.get('t1_avg_price', 0.0)
                holding['isin'] = holding.get('isin', '')

                # For Indmoney, we'll assume NSE as default exchange since it's not provided
                # We can try to determine exchange from symbol or use database lookup
                exchange = 'NSE'  # Default to NSE for equity holdings
                holding['exchangeSegment'] = exchange

                # Calculate market value and P&L (we'll need current market price for accurate calculation)
                # For now, we'll use average price as placeholder - this should be updated with live market data
                total_qty = holding.get('total_qty', 0)
                avg_price = holding.get('avg_price', 0.0)
                
                # Use average price as last traded price placeholder
                holding['lastTradedPrice'] = avg_price
                holding['marketValue'] = total_qty * avg_price
                holding['pnlAbsolute'] = 0.0  # Will be calculated when we have market price
                holding['pnlPercent'] = 0.0   # Will be calculated when we have market price

                # Use the get_symbol function to fetch the symbol from the database if needed
                if instrument_token and exchange:
                    symbol_from_db = get_symbol(instrument_token, exchange)
                    
                    # Check if a symbol was found; if so, update the trading_symbol
                    if symbol_from_db:
                        holding['tradingSymbol'] = symbol_from_db
                    else:
                        # Keep the existing symbol from Indmoney API
                        logger.warning(f"Symbol not found for token {instrument_token} and exchange {exchange}. Using: {symbol}")

        return portfolio_data
        
    except Exception as e:
        logger.error(f"Exception in map_portfolio_data: {e}")
        return []


def calculate_portfolio_statistics(holdings_data):
    try:
        # Handle None or empty input
        if not holdings_data or not isinstance(holdings_data, list):
            return {
                'totalholdingvalue': 0.0,
                'totalinvvalue': 0.0,
                'totalprofitandloss': 0.0,
                'totalpnlpercentage': 0.0
            }
        
        totalholdingvalue = 0.0
        totalinvvalue = 0.0
        totalprofitandloss = 0.0
        
        for holding in holdings_data:
            # Ensure each holding is a dictionary
            if not isinstance(holding, dict):
                continue
                
            # Calculate values from actual Indmoney format
            total_qty = holding.get('total_qty', holding.get('totalQty', 0))
            avg_price = holding.get('avg_price', holding.get('avgCostPrice', 0.0))
            
            # For now, use avg_price as market price since Indmoney doesn't provide current market price
            # In a real implementation, this should fetch current market price
            market_price = avg_price  # Placeholder - should be replaced with live market data
            
            # Calculate values
            investment_value = total_qty * avg_price
            market_value = total_qty * market_price
            pnl = market_value - investment_value
            
            # Add to totals
            totalholdingvalue += market_value
            totalinvvalue += investment_value
            totalprofitandloss += pnl
        
        # Calculate percentage - avoid division by zero
        totalpnlpercentage = (totalprofitandloss / totalinvvalue * 100) if totalinvvalue > 0 else 0.0

        return {
            'totalholdingvalue': round(totalholdingvalue, 2),
            'totalinvvalue': round(totalinvvalue, 2),
            'totalprofitandloss': round(totalprofitandloss, 2),
            'totalpnlpercentage': round(totalpnlpercentage, 2)
        }
    except Exception as e:
        logger.error(f"Exception in calculate_portfolio_statistics: {e}")
        return {
            'totalholdingvalue': 0.0,
            'totalinvvalue': 0.0,
            'totalprofitandloss': 0.0,
            'totalpnlpercentage': 0.0
        }


