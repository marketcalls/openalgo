import json
from database.token_db import get_symbol
from broker.paytm.mapping.transform_data import map_product_type
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
    if order_data['data'] is None:
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        logger.debug("No data available.")
        order_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        order_data = order_data['data']

    if order_data:
        for order in order_data:
            # Extract the instrument_token and exchange for the current order
            exchange = order['exchange']
            if exchange == "NSE" and ("OPT" in order['instrument'] or "FUT" in order['instrument']):
                exchange = "NFO"
            if exchange == "BSE" and ("OPT" in order['instrument'] or "FUT" in order['instrument']):
                exchange = "BFO"
            symbol = order['security_id']
       
            
            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol:
                order['symbol'] = get_symbol(token=symbol,exchange=exchange)
                if (order['exchange'] == 'NSE' or order['exchange'] == 'BSE') and order['product'] == 'C':
                    order['product'] = 'CNC'
                               
                elif order['product'] == 'I' or order['product'] == 'M':
                    order['product'] = 'MIS'
                
                elif order['exchange'] in ['NFO', 'MCX', 'BFO', 'CDS']:
                    order['product'] = 'NRML'
            else:
                logger.warning(f"Symbol for token {symbol} and exchange {exchange} not found. Keeping original trading symbol.")
                
    logger.debug(f"Mapped order data: {order_data}")
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
            if order['txn_type'] == 'B':
                order['txn_type'] = 'BUY'
                total_buy_orders += 1
            elif order['txn_type'] == 'S':
                order['txn_type'] = 'SELL'
                total_sell_orders += 1
            
            # Count orders based on their status
            if order['display_status'] == 'Successful':
                total_completed_orders += 1
            elif order['display_status'] == 'Pending':
                total_open_orders += 1
            elif order['display_status'] == 'Rejected':
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
            logger.warning(f"Warning: Expected a dict, but found a {type(order)}. Skipping this item.")
            continue

        if(order.get("display_status", "")=="Successful"):
            order_status = "complete"
        if(order.get("display_status", "")=="Rejected"):
            order_status = "rejected"
        if(order.get("display_status", "")=="Pending"):
            order_status = "trigger pending"
        if(order.get("display_status", "")=="Open"):
            order_status = "open"
        if(order.get("display_status", "")=="Cancelled"):
            order_status = "cancelled"

        # Apply exchange mapping for F&O instruments
        exchange = order.get("exchange", "")
        instrument = order.get("instrument", "")
        symbol = order.get("symbol", "")
        
        # Map NSE to NFO for options and futures
        if exchange == "NSE" and ("OPT" in instrument or "FUT" in instrument):
            exchange = "NFO"
        # Map BSE to BFO for options and futures
        elif exchange == "BSE" and ("OPT" in instrument or "FUT" in instrument):
            exchange = "BFO"

        transformed_order = {
            "symbol": symbol,
            "exchange": exchange,  # Use the mapped exchange
            "action": order.get("txn_type", ""),
            "quantity": order.get("quantity", 0),
            "price": order.get("price", 0.0),
            "trigger_price": order.get("trigger_price", 0.0),
            "pricetype": order.get("display_order_type", "").upper(),
            "product": order.get("product", ""),
            "orderid": order.get("order_no", ""),
            "order_status": order_status,
            "timestamp": order.get("order_date_time", "")
        }

        transformed_orders.append(transformed_order)

    return transformed_orders

def map_trade_data(trade_data):
    return map_order_data(trade_data)

def transform_tradebook_data(tradebook_data):
    transformed_data = []
    tnx_type_mapping = {
        "B": "BUY",
        "S": "SELL"
    }
    for trade in tradebook_data:
        mapped_tnx = tnx_type_mapping.get(trade.get('txn_type', ''), trade.get('txn_type', ''))
        
        # Apply exchange mapping for F&O instruments
        exchange = trade.get('exchange', '')
        instrument = trade.get('instrument', '')
        
        # Map NSE to NFO for options and futures
        if exchange == "NSE" and ("OPT" in instrument or "FUT" in instrument):
            exchange = "NFO"
        # Map BSE to BFO for options and futures
        elif exchange == "BSE" and ("OPT" in instrument or "FUT" in instrument):
            exchange = "BFO"
            
        transformed_trade = {
            "symbol": trade.get('symbol'),
            "exchange": exchange,  # Use the mapped exchange
            "product": trade.get('product', ''),
            "action": mapped_tnx,
            "quantity": trade.get('quantity', 0),
            "average_price": trade.get('avg_traded_price', 0.0),
            "trade_value": trade.get('remaining_quantity', 0) * trade.get('avg_traded_price', 0.0),
            "orderid": trade.get('order_no', ''),
            "timestamp": trade.get('order_date_time', '')
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
    if position_data['data'] is None:
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        logger.debug("No data available.")
        position_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        position_data = position_data['data']

    if position_data:
        for position in position_data:
            # Extract the instrument_token and exchange for the current order
            logger.debug(f"Processing position: {position}")
            exchange = position['exchange']
            symbol = position['security_id']
            
            if exchange == "NSE" and ("OPT" in position['instrument'] or "FUT" in position['instrument']):
                exchange = "NFO"

            if exchange == "BSE" and ("OPT" in position['instrument'] or "FUT" in position['instrument']):
                exchange = "BFO"
            
            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol:
                position['security_id'] = get_symbol(token=symbol,exchange=exchange)
            else:
                logger.warning(f"Symbol for token {symbol} and exchange {exchange} not found. Keeping original trading symbol.")
        
    logger.debug(f"Mapped position data: {position_data}")
    return position_data
    

def transform_positions_data(positions_data):
    transformed_data = [] 

    for position in positions_data:
        # Ensure average_price is treated as a float, then format to a string with 2 decimal places
        if position.get('display_pos_type') is not None:
            if position.get('display_pos_type') == "B":
                average_price_formatted = "{:.2f}".format(float(position.get('buy_avg', 0.0)))
            elif position.get('display_pos_type') == "S":
                average_price_formatted = "{:.2f}".format(float(position.get('sell_avg', 0.0)))
            else:
                average_price_formatted = "{:.2f}".format(float(position.get('net_avg', 0.0)))
        else:
            average_price_formatted = "{:.2f}".format(float(position.get('net_avg', 0.0)))

        # Apply exchange mapping for F&O instruments
        exchange = position.get('exchange', '')
        instrument = position.get('instrument', '')
        
        # Map NSE to NFO for options and futures
        if exchange == "NSE" and ("OPT" in instrument or "FUT" in instrument):
            exchange = "NFO"
        # Map BSE to BFO for options and futures
        elif exchange == "BSE" and ("OPT" in instrument or "FUT" in instrument):
            exchange = "BFO"

        transformed_position = {
            "symbol": position.get('security_id', ''),
            "exchange": exchange,  # Use the mapped exchange
            "product": map_product_type(position.get('product', '')),
            "quantity": position.get('net_qty', '0'),
            "average_price": average_price_formatted,
            "ltp": position.get('last_traded_price', '0.00'),
            "pnl": position.get('net_val', '0.00'),
        }
        transformed_data.append(transformed_position)
    return transformed_data

def transform_holdings_data(holdings_data):
    # Handle two types of inputs:
    # 1. Raw API response from Paytm (initial call)
    # 2. Already mapped data (from map_portfolio_data)
    
    # Parse JSON response if it's a string
    if isinstance(holdings_data, str):
        try:
            holdings_data = json.loads(holdings_data)
        except json.JSONDecodeError:
            logger.exception("Error decoding holdings JSON response")
            return []
    
    # Handle already mapped list of holdings (output of map_portfolio_data)
    if isinstance(holdings_data, list):
        transformed_data = []
        
        # If we have an empty list, simply return it
        if not holdings_data:
            logger.debug("No holdings data in list form")
            return []
        
        for holding in holdings_data:
            if not isinstance(holding, dict):
                logger.warning(f"Invalid holding format in list: {holding}")
                continue
                
            # Don't filter too aggressively - only skip if we're 100% sure it's just a placeholder
            # and not a legitimate holding with a temporary symbol issue
            if holding.get('symbol') == 'None' and holding.get('quantity', 0) <= 0:
                logger.debug(f"Skipping definite placeholder holding: {holding}")
                continue
                
            try:
                # Match field names exactly as they come from map_portfolio_data
                quantity = float(holding.get('quantity', 0))
                avg_price = float(holding.get('avg_price', 0.0))
                ltp = float(holding.get('ltp', 0.0))
                pnl = float(holding.get('pnl', (ltp - avg_price) * quantity))
                
                # Use a placeholder symbol if needed but keep the holding
                symbol = holding.get('symbol', '')
                if not symbol or symbol == 'None':
                    symbol = holding.get('security_id', 'Unknown')
                
                transformed_position = {
                    "symbol": symbol,
                    "exchange": holding.get('exchange', 'NSE'),
                    "quantity": quantity,
                    "product": holding.get('product', 'CNC'),
                    "pnl": round(pnl, 2),
                    "ltp": ltp,
                    "avg_price": avg_price,
                    "pnlpercent": round((ltp - avg_price) / avg_price * 100, 2) if avg_price > 0 else 0.0
                }
                transformed_data.append(transformed_position)
            except (ValueError, TypeError) as e:
                logger.exception(f"Error parsing values in holding: {holding}, Error: {e}")
                continue
        return transformed_data
    
    # Handle raw API response (dict with 'data' field)
    if not holdings_data or not isinstance(holdings_data, dict):
        logger.warning(f"Invalid holdings data format: {holdings_data}")
        return []
    
    # Paytm may return holdings in different formats, try both structures
    if 'data' in holdings_data:
        # First check direct data array
        holdings_list = holdings_data.get('data', [])
        # If data is a dict with 'results' key (older API format)
        if isinstance(holdings_list, dict) and 'results' in holdings_list:
            holdings_list = holdings_list.get('results', [])
    else:
        logger.warning(f"Invalid holdings data format: {holdings_data}")
        return []
    
    if not holdings_list:
        logger.debug(f"No holdings data found: {holdings_list}")
        return []
        
    transformed_data = []
    for holding in holdings_list:
        if not isinstance(holding, dict):
            logger.warning(f"Invalid holding format: {holding}")
            continue
            
        try:
            quantity = float(holding.get('quantity', 0))
            cost_price = float(holding.get('avg_price', holding.get('cost_price', 0.0)))
            last_traded_price = float(holding.get('ltp', holding.get('last_traded_price', 0.0)))
            pnl = (last_traded_price - cost_price) * quantity
            
            transformed_position = {
                "symbol": holding.get('security_id', ''),
                "exchange": holding.get('exchange', ''),
                "quantity": quantity,
                "product": 'CNC',  # Paytm only supports CNC for holdings
                "pnl": round(holding.get('pnl', pnl), 2),
                "ltp": last_traded_price,
                "avg_price": cost_price,
                "pnlpercent": round((last_traded_price - cost_price) / cost_price * 100, 2) if cost_price > 0 else 0.0
            }
            transformed_data.append(transformed_position)
        except (ValueError, TypeError) as e:
            logger.exception(f"Error parsing values in holding: {holding}, Error: {e}")
            continue
            
    return transformed_data

def map_portfolio_data(holdings_data):
    """Map Paytm holdings data to standardized portfolio format"""
    logger.debug("\n==== PAYTM PORTFOLIO RAW RESPONSE ====")
    logger.debug(f"{json.dumps(holdings_data, indent=2)}")
    logger.debug("=======================================")
    
    # Parse JSON response if it's a string
    if isinstance(holdings_data, str):
        try:
            holdings_data = json.loads(holdings_data)
        except json.JSONDecodeError:
            logger.exception("Error decoding holdings JSON response")
            return []
    
    if not holdings_data or not isinstance(holdings_data, dict):
        logger.warning(f"Invalid holdings data format: {holdings_data}")
        return []
    
    # Paytm may return holdings in different formats, try both structures
    if 'data' in holdings_data:
        # First check direct data array
        holdings_list = holdings_data.get('data', [])
        logger.debug(f"\nParsing 'data' field: {type(holdings_list)}, len: {len(holdings_list) if isinstance(holdings_list, list) else 'not list'}")
        
        # If data is a dict with 'results' key (older API format)
        if isinstance(holdings_list, dict) and 'results' in holdings_list:
            holdings_list = holdings_list.get('results', [])
            logger.debug(f"Found 'results' subkey, extracted: {len(holdings_list) if isinstance(holdings_list, list) else 'not list'}")
    else:
        logger.warning(f"Invalid holdings data format: {holdings_data}")
        return []
    
    if not holdings_list:
        logger.debug(f"No holdings data found: {holdings_list}")
        return []
        
    logger.debug(f"\nHoldings list contains {len(holdings_list)} items")
    if holdings_list:
        logger.debug(f"First holding sample: {holdings_list[0]}")
        
    mapped_data = []
    for i, holding in enumerate(holdings_list):
        if not isinstance(holding, dict):
            logger.warning(f"Invalid holding format: {holding}")
            continue
            
        logger.debug(f"\nProcessing holding #{i+1}:")
        logger.debug(f"NSE Symbol: {holding.get('nse_symbol', 'N/A')}")
        logger.debug(f"BSE Symbol: {holding.get('bse_symbol', 'N/A')}")
        logger.debug(f"NSE Security ID: {holding.get('nse_security_id', 'N/A')}")
        logger.debug(f"BSE Security ID: {holding.get('bse_security_id', 'N/A')}")
        logger.debug(f"Exchange: {holding.get('exchange', 'N/A')}")
        logger.debug(f"Quantity: {holding.get('quantity', 'N/A')}")
        
        # Paytm uses 'ALL' for holdings available on both exchanges
        # Default to NSE for consistent behavior
        exchange = 'NSE'
        security_id = holding.get('nse_security_id', '')
        
        # Only use BSE as fallback or if explicitly specified
        if (not security_id and holding.get('bse_security_id')) or holding.get('exchange') == 'BSE':
            exchange = 'BSE'
            security_id = holding.get('bse_security_id', '')
            
        logger.debug(f"Selected exchange: {exchange}, Security ID: {security_id}")
            
        # Try to get the symbol
        symbol = None
        if security_id:
            symbol = get_symbol(token=security_id, exchange=exchange)
            logger.debug(f"Mapped symbol: {symbol} (from security_id: {security_id})")
        
        # If symbol mapping fails, use the exchange-specific symbol directly
        if not symbol:
            if exchange == 'NSE':
                symbol = holding.get('nse_symbol', '')
            else:
                symbol = holding.get('bse_symbol', '')
            logger.debug(f"Using direct symbol from API: {symbol}")
        
        avg_price = holding.get('cost_price', holding.get('avg_price', 0.0))
        ltp = holding.get('last_traded_price', holding.get('ltp', 0.0))
        
        # Calculate PNL if not provided
        try:
            quantity = float(holding.get('quantity', 0))
            avg_price_float = float(avg_price)
            ltp_float = float(ltp)
            pnl = (ltp_float - avg_price_float) * quantity
        except (ValueError, TypeError) as e:
            pnl = 0.0
            logger.exception(f"Error calculating PNL for holding {holding}: {e}")
        
        # Use previous close price (pc) if available
        close_price = holding.get('pc', holding.get('previous_close_price', holding.get('close_price', 0.0)))
        
        mapped_holding = {
            'symbol': symbol or 'Unknown',
            'exchange': exchange,
            'quantity': holding.get('quantity', 0),
            'avg_price': avg_price,
            'ltp': ltp,
            'close_price': close_price,
            'pnl': round(pnl, 2),
            'product': 'CNC'  # Paytm only supports CNC for holdings
        }
        logger.debug(f"Final mapped holding: {mapped_holding}")
        mapped_data.append(mapped_holding)
    
    logger.debug(f"\n==== FINAL MAPPED PORTFOLIO DATA ({len(mapped_data)} items) ====")
    logger.debug(f"{json.dumps(mapped_data, indent=2, default=str)}")
    logger.debug("=======================================")
    return mapped_data

def calculate_portfolio_statistics(holdings_data):
    """Calculate portfolio statistics from holdings data"""
    # Parse JSON response if it's a string
    if isinstance(holdings_data, str):
        try:
            holdings_data = json.loads(holdings_data)
        except json.JSONDecodeError:
            logger.error("Error decoding holdings JSON response")
            return {
                'totalholdingvalue': 0.0,
                'totalinvvalue': 0.0,
                'totalprofitandloss': 0.0,
                'totalpnlpercentage': 0.0,
                'total_holdings': 0
            }
    
    if not holdings_data or not isinstance(holdings_data, list):
        logger.info(f"Invalid holdings data format: {holdings_data}")
        return {
            'totalholdingvalue': 0.0,
            'totalinvvalue': 0.0,
            'totalprofitandloss': 0.0,
            'totalpnlpercentage': 0.0,
            'total_holdings': 0
        }
    
    total_investment = 0.0
    total_current_value = 0.0
    total_pnl = 0.0
    
    for holding in holdings_data:
        if not isinstance(holding, dict):
            logger.info(f"Invalid holding format: {holding}")
            continue
        
        try:    
            # Ensure numeric type conversion for calculations
            quantity = float(holding.get('quantity', 0))
            cost_price = float(holding.get('avg_price', 0.0))
            last_traded_price = float(holding.get('ltp', 0.0))
            
            position_investment = cost_price * quantity
            position_current_value = last_traded_price * quantity
            
            total_investment += position_investment
            total_current_value += position_current_value
            total_pnl += float(holding.get('pnl', 0.0))
        except (ValueError, TypeError) as e:
            logger.error(f"Error converting values in holding: {holding}, Error: {e}")
            continue
    
    total_pnl_percentage = (total_pnl / total_investment * 100) if total_investment > 0 else 0.0
    
    return {
        'totalholdingvalue': round(total_current_value, 2),
        'totalinvvalue': round(total_investment, 2),
        'totalprofitandloss': round(total_pnl, 2),
        'totalpnlpercentage': round(total_pnl_percentage, 2),
        'total_holdings': len(holdings_data)
    }
