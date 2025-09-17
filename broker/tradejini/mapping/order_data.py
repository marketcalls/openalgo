import json
from database.token_db import get_symbol, get_oa_symbol 
from broker.tradejini.mapping.transform_data import reverse_map_product_type
from utils.logging import get_logger

logger = get_logger(__name__)

def map_order_data(order_data):
    """
    Processes and modifies a list of order dictionaries based on specific conditions.
    
    Parameters:
    - order_data: Tradejini API response containing order information
    
    Returns:
    - The modified order_data with updated fields
    """
    logger.debug(f"map_order_data - Input order_data: {order_data}")
    
    # Check if response status is ok
    if order_data.get('stat') != 'Ok':
        logger.debug("map_order_data - Error in API response")
        return []
    
    # Get orders from response - they are nested under 'data' field
    orders_data = order_data.get('data', [])
    #print(f"[DEBUG] map_order_data - Found {len(orders_data)} orders in response")
    #print(f"[DEBUG] map_order_data - Orders data: {orders_data}")
    
    # Process each order
    if orders_data:
        for order in orders_data:
            # Get the actual order data from the nested structure
            order_info = order.get('data', {})
           # logger.info(f"[DEBUG] map_order_data - Processing order info: {order_info}")
            
            # Update fields in place
            order['action'] = "BUY" if order_info.get('side') == 'buy' else "SELL"
            order['exchange'] = order_info.get('exchange', '')
            order['order_status'] = order_info.get('status', '').lower()
            order['orderid'] = str(order_info.get('order_id', ''))
            order['price'] = float(order_info.get('limit_price', 0))
            order['pricetype'] = order_info.get('type', '').upper()
            
            # Map product type using reverse mapping function
            product = order_info.get('product', '').lower()
            order['product'] = reverse_map_product_type(product) or 'MIS'
            
            order['quantity'] = int(order_info.get('quantity', 0))
            order['symbol'] = order_info.get('tradingsymbol', '')
            order['timestamp'] = order_info.get('order_time', '')
            order['trigger_price'] = float(order_info.get('trigPrice', 0))
            
            #print(f"[DEBUG] map_order_data - Updated order: {order}")
    
    return orders_data


def calculate_order_statistics(order_data):
    """
    Calculates statistics from order data, including totals for buy orders, sell orders,
    completed orders, open orders, and rejected orders.

    Parameters:
    - order_data: List of orders with modified fields

    Returns:
    - Dictionary containing counts of different types of orders
    """
    #print(f"[DEBUG] calculate_order_statistics - Input order_data: {order_data}")
    
    # Initialize counters
    total_buy_orders = total_sell_orders = 0
    total_completed_orders = total_open_orders = total_rejected_orders = 0

    if order_data:
        for order in order_data:
            # Count buy and sell orders
            if order.get('action') == 'BUY':
                total_buy_orders += 1
            elif order.get('action') == 'SELL':
                total_sell_orders += 1
            
            # Count orders based on their status
            status = order.get('order_status', '').lower()
            if status == 'complete':
                total_completed_orders += 1
            elif status == 'rejected':
                total_rejected_orders += 1
            elif status == 'open':
                total_open_orders += 1

    # Compile and return the statistics
    return {
        'total_buy_orders': total_buy_orders,
        'total_sell_orders': total_sell_orders,
        'total_completed_orders': total_completed_orders,
        'total_open_orders': total_open_orders,
        'total_rejected_orders': total_rejected_orders
    }


def transform_order_data(orders):
    """
    Processes and modifies a list of order dictionaries into the final OpenAlgo format.
    
    Parameters:
    - orders: List of orders with modified fields
    
    Returns:
    - Dictionary with orders in OpenAlgo format
    """
    #print(f"[DEBUG] transform_order_data - Input orders: {orders}")
    
    # Directly handling a dictionary assuming it's the structure we expect
    if isinstance(orders, dict):
        # Convert the single dictionary into a list of one dictionary
        orders = [orders]

    transformed_orders = []
    
    for order in orders:
        # Convert to OpenAlgo format if needed
        transformed_order = {
            "action": order.get('action', ''),
            "exchange": order.get('exchange', ''),
            "order_status": order.get('order_status', ''),
            "orderid": str(order.get('orderid', '')),
            "price": float(order.get('price', 0)),
            "pricetype": order.get('pricetype', '').upper(),
            "product": order.get('product', '').upper(),
            "quantity": int(order.get('quantity', 0)),
            "symbol": order.get('symbol', ''),
            "timestamp": order.get('timestamp', ''),
            "trigger_price": float(order.get('trigger_price', 0))
        }
        transformed_orders.append(transformed_order)
        #print(f"[DEBUG] transform_order_data - Transformed order: {transformed_order}")
    
    return transformed_orders



def map_trade_data(trade_data):
    """
    Processes and modifies a list of trade dictionaries based on specific conditions.
    
    Args:
        trade_data: Tradejini API response containing trade information
        
    Returns:
        The modified trade_data with updated fields
    """
    logger.debug(f"map_trade_data - Input trade_data type: {type(trade_data)}")
    
    # Handle already transformed data that might be in different formats
    
    # Handle direct array of trades (from get_trade_book)
    if isinstance(trade_data, list):
        # If it's already a list of trades, just return it
        return trade_data
        
    # Handle OpenAlgo format with status and data fields
    if isinstance(trade_data, dict) and 'status' in trade_data and trade_data.get('status') == 'success':
        if 'data' in trade_data and isinstance(trade_data['data'], list):
            return trade_data['data']
        return []
    
    # Check if it's a TradeJini API response
    if not isinstance(trade_data, dict) or 's' not in trade_data or trade_data.get('s') != 'ok':
        # Not a TradeJini API response - log at debug level instead of warning to avoid unnecessary warnings
        logger.debug(f"map_trade_data - Not a TradeJini API response format")
        return []
    
    # Get trades from response - they are in the 'd' array
    trades_data = trade_data.get('d', [])
    logger.debug(f"map_trade_data - Found {len(trades_data)} trades in response")
    
    # Process each trade
    mapped_trades = []
    if trades_data:
        for trade in trades_data:
            # Get symbol details from the sym object
            symbol = trade.get('sym', {})
            
            # Map product types
            product = trade.get('product', '').lower()
            if product == 'intraday':
                product = 'MIS'
            elif product == 'delivery':
                product = 'CNC'
            elif product == 'coverorder':
                product = 'CO'
            elif product == 'bracketorder':
                product = 'BO'
            else:
                product = 'NRML'
            
            # Map side to action
            side = trade.get('side', '').lower()
            action = 'BUY' if side == 'buy' else 'SELL'
            
            # Get exchange from sym object
            exchange = symbol.get('exch', '').upper()
            
            # Create mapped trade
            mapped_trade = {
                "symbol": symbol.get('trdSym', ''),
                "exchange": exchange,
                "product": product,
                "action": action,
                "quantity": trade.get('fillQty', 0),
                "average_price": trade.get('fillPrice', 0.0),
                "trade_value": trade.get('fillValue', 0.0),
                "orderid": trade.get('orderId', ''),
                "timestamp": trade.get('time', ''),
                "sym_id": symbol.get('id', '') # Store symbol ID for OpenAlgo lookup
            }
            
            # Add optional fields if present
            if trade.get('exchOrderId'):
                mapped_trade["exchange_order_id"] = trade.get('exchOrderId', '')
            
            if trade.get('remarks'):
                mapped_trade["remarks"] = trade.get('remarks', '')
                
            mapped_trades.append(mapped_trade)
            
    return mapped_trades


def transform_tradebook_data(trades):
    """
    Transforms mapped trade data to OpenAlgo format.
    
    Args:
        trades: List of mapped trade dictionaries or raw API response
        
    Returns:
        dict: Trade book data in OpenAlgo format with {'data': [...], 'status': 'success'}
    """
    logger.debug(f"transform_tradebook_data - Input trades type: {type(trades)}")
    
    # Check if already in OpenAlgo format
    if isinstance(trades, dict) and 'status' in trades and 'data' in trades:
        logger.debug("transform_tradebook_data - Already in OpenAlgo format")
        # Extract just the data array without the wrapper
        return trades['data']
    
    # Handle empty list case
    if not trades:
        logger.debug("transform_tradebook_data - Empty trades list")
        # Return just the array without any wrapper
        return []
    
    # Check if raw TradeJini API response
    if isinstance(trades, dict) and 's' in trades and trades.get('s') == 'ok' and 'd' in trades:
        logger.debug("transform_tradebook_data - Processing raw TradeJini API response")
        trades = trades.get('d', [])
    
    # Directly handling a dictionary assuming it's a single trade
    if isinstance(trades, dict) and 'action' not in trades and 'orderid' not in trades:
        # Convert the single dictionary into a list of one dictionary
        logger.debug("transform_tradebook_data - Converting single dict to list")
        trades = [trades]
        
    if not isinstance(trades, list):
        logger.error(f"Invalid input data type: Expected list or dict, got {type(trades)}")
        return {
            'status': 'error',
            'data': [],
            'message': f"Invalid input data type: Expected list or dict, got {type(trades)}"
        }
    
    transformed_trades = []
    
    for trade in trades:
        if not isinstance(trade, dict):
            logger.warning(f"Skipping invalid trade data: {type(trade)}")
            continue
            
        # Check if this is already transformed
        if all(key in trade for key in ['action', 'average_price', 'exchange', 'orderid']):
            transformed_trades.append(trade)
            continue
        
        # Get Symbol details if it exists
        symbol = trade.get('sym', {})
        sym_id = ''
        
        if isinstance(symbol, dict):
            sym_id = symbol.get('id', '')
            exchange = symbol.get('exch', '')
            trading_symbol = symbol.get('trdSym', '')
        else:
            # Use data from trade directly if sym object doesn't exist
            sym_id = trade.get('sym_id', '')
            exchange = trade.get('exchange', '')
            trading_symbol = trade.get('symbol', '')
        
        # Get OpenAlgo symbol if possible
        try:
            openalgo_symbol = get_oa_symbol(
                symbol=sym_id, 
                exchange=exchange
            )
        except Exception as e:
            logger.warning(f"Symbol lookup failed: {str(e)}")
            openalgo_symbol = None
            
        # Map product type if needed
        if 'product' in trade:
            product = trade['product']
            if isinstance(product, str) and product.lower() in ['intraday', 'delivery', 'coverorder', 'bracketorder']:
                product = trade.get('product', '').lower()
                if product == 'intraday':
                    product = 'MIS'
                elif product == 'delivery':
                    product = 'CNC'
                elif product == 'coverorder':
                    product = 'CO'
                elif product == 'bracketorder':
                    product = 'BO'
                else:
                    product = 'NRML'
            else:
                product = str(product).upper()
        else:
            product = 'MIS'  # Default
            
        # Map side to action if needed
        if 'action' in trade:
            action = trade['action']
        elif 'side' in trade:
            side = trade.get('side', '').lower()
            action = 'BUY' if side == 'buy' else 'SELL'
        else:
            action = ''  # Can't determine
            
        # Create transformed trade - match OpenAlgo format exactly
        transformed_trade = {
            "action": action,
            "average_price": float(trade.get('fillPrice', trade.get('average_price', 0.0))),
            "exchange": exchange.upper() if exchange else '',
            "orderid": str(trade.get('orderId', trade.get('orderid', ''))),
            "product": product,
            "quantity": int(trade.get('fillQty', trade.get('quantity', 0))),
            "symbol": trading_symbol,
            "timestamp": trade.get('time', trade.get('timestamp', '')),
            "trade_value": float(trade.get('fillValue', trade.get('trade_value', 0.0)))
        }
        
        # Removed tradingsymbol and exchange_order_id fields as per requirements
        
        if 'remarks' in trade:
            transformed_trade["remarks"] = trade.get('remarks', '')
        
        transformed_trades.append(transformed_trade)
        
    logger.debug(f"transform_tradebook_data - Transformed {len(transformed_trades)} trades")
    
    return transformed_trades

# Position mapping functions have been moved to get_positions function in order_api.py
# These compatibility functions are kept for backward compatibility

def map_position_data(position_data):
    """
    Map TradeJini position data to a standardized format.
    DEPRECATED: This function is kept for backward compatibility only.
    Position mapping is now done directly in get_positions function.
    """
    logger.warning("map_position_data is deprecated - position mapping is now done directly in get_positions")
    
    # Check for different response formats
    if isinstance(position_data, dict):
        # Handle the case where the entire API response is passed
        if position_data.get('s') == 'ok' and 'd' in position_data:
            position_data = position_data.get('d', [])
        # Handle already processed data with status and data fields
        elif position_data.get('status') == 'success' and 'data' in position_data:
            # Data already mapped - return as is
            return position_data.get('data', [])
    
    if not position_data or not isinstance(position_data, list):
        logger.warning("No valid position data available or invalid format")
        return []
        
    mapped_positions = []
    
    for position in position_data:
        try:
            # Skip zero positions
            net_qty = position.get('netQty', 0)
            if net_qty == 0:
                continue
                
            # Map product type
            product_map = {
                'delivery': 'CNC',
                'intraday': 'MIS',
                'margin': 'NRML'
            }
            product = product_map.get(position.get('product', '').lower(), 'MIS')
            
            sym = position.get('sym', {})
            exchange_symbol = sym.get('sym', '')
            tradingsymbol = sym.get('trdSym', '')
            exchange = sym.get('exch', '')
            
            # Get symbol ID from the position data
            symbol_id = position.get('symId', '')
            
            # Log position data for debugging
            logger.info(f"Position data: symId={symbol_id}, tradingsymbol={tradingsymbol}, exchange={exchange}")
            
            # Get OpenAlgo symbol - follow same approach as the main implementation
            openalgo_symbol = None
            try:
                # First try with the symbol ID from sym object
                symid_from_object = sym.get('id', '') if sym else ''
                if symid_from_object:
                    openalgo_symbol = get_oa_symbol(symid_from_object, exchange)
                    logger.info(f"Symbol lookup with sym.id: {symid_from_object} -> {openalgo_symbol}")
                
                # If not found and we have the position symId, try that
                if not openalgo_symbol and symbol_id:
                    openalgo_symbol = get_oa_symbol(symbol_id, '')
                    logger.info(f"Symbol lookup with position.symId: {symbol_id} -> {openalgo_symbol}")
                    
                # If still not found, try with exchange symbol
                if not openalgo_symbol:
                    openalgo_symbol = get_oa_symbol(exchange_symbol, exchange)
                    logger.info(f"Symbol lookup with exchange symbol: {exchange_symbol} -> {openalgo_symbol}")
                    
            except Exception as e:
                logger.warning(f"Symbol lookup failed: {str(e)}")
                openalgo_symbol = None
            
            # Determine the final symbol to use
            final_symbol = ""
            if openalgo_symbol:
                final_symbol = openalgo_symbol
                logger.info(f"Using OpenAlgo symbol: {final_symbol}")
            else:
                # Fallback to exchange symbol if OpenAlgo symbol isn't available
                final_symbol = exchange_symbol
                logger.info(f"Fallback to exchange symbol: {final_symbol}")
            
            # Create mapped position - without tradingsymbol field as requested
            mapped_position = {
                'symbol': final_symbol,  # Use final symbol (OpenAlgo or fallback)
                'exchange': exchange,
                'product': product,
                'quantity': int(position.get('netQty', 0)),
                'average_price': str(round(float(position.get('netAvgPrice', 0.0)), 2)),
                'pnl': position.get('realizedPnl', 0.0),
                'day_quantity': position.get('dayPos', {}).get('dayQty', 0),
                'day_average': position.get('dayPos', {}).get('dayAvg', 0.0),
                'day_pnl': position.get('dayPos', {}).get('dayRealizedPnl', 0.0)
            }
            
            mapped_positions.append(mapped_position)
            
        except Exception as e:
            logger.error(f"Error mapping position: {e}", exc_info=True)
    
    return mapped_positions

def transform_positions_data(positions_data):
    """
    Transform mapped position data to OpenAlgo format.
    DEPRECATED: This function is kept for backward compatibility only.
    Position transformation is now done directly in get_positions function.
    """
    logger.warning("transform_positions_data is deprecated - transformation is now done directly in get_positions")
    
    # Handle already processed data with status and data fields
    if isinstance(positions_data, dict):
        if positions_data.get('status') == 'success' and 'data' in positions_data:
            return positions_data.get('data', [])
    
    # Check if this is an empty or invalid list
    if not positions_data or not isinstance(positions_data, list):
        logger.warning("No valid positions data to transform")
        return []
    
    transformed_data = []
    
    for position in positions_data:
        try:
            # Check if position data is already in expected format
            if all(k in position for k in ('symbol', 'exchange', 'product', 'quantity', 'average_price')):
                # Already transformed, just add to list
                transformed_data.append(position)
                continue
                
            # Convert quantity to int and skip zero positions
            quantity = int(position.get('quantity', 0))
            if quantity == 0:
                continue
                
            # Create transformed position with required fields
            transformed_position = {
                'symbol': position.get('symbol', ''),
                'exchange': position.get('exchange', 'NSE'),
                'product': position.get('product', 'MIS'),
                'quantity': quantity,
                'average_price': str(round(float(position.get('average_price', 0.0)), 2))
            }
            
            transformed_data.append(transformed_position)
            
        except Exception as e:
            logger.error(f"Error transforming position: {e}", exc_info=True)
    
    return transformed_data

def map_portfolio_data(portfolio_data):
    """
    Processes and modifies a list of Portfolio dictionaries based on specific conditions and
    ensures both holdings and totalholding parts are transmitted in a single response.
    
    Parameters:
    - portfolio_data: A list of dictionaries, where each dictionary represents portfolio information.
    
    Returns:
    - The modified portfolio_data with 'product' fields changed for 'holdings' and 'totalholding' included.
    """
    # Check if 'portfolio_data' is a list
    if not isinstance(portfolio_data, list):
        logger.warning("Portfolio data is not a list.")
        return []

    # Handle empty list gracefully - it's not an error
    if len(portfolio_data) == 0:
        logger.debug("No portfolio data available (empty list)")
        return []

    # Iterate over the portfolio_data list and process each entry
    for portfolio in portfolio_data:
        # Ensure 'stat' is 'Ok' before proceeding
        if portfolio.get('stat') != 'Ok':
            logger.error(f"Error: {portfolio.get('emsg', 'Unknown error occurred.')}")
            continue

        # Process the 'exch_tsym' list inside each portfolio entry
        for exch_tsym in portfolio.get('exch_tsym', []):
            symbol = exch_tsym.get('tsym', '')
            exchange = exch_tsym.get('exch', '')

            # Replace 'get_oa_symbol' function with your actual symbol fetching logic
            symbol_from_db = get_oa_symbol(symbol, exchange)
            
            if symbol_from_db:
                exch_tsym['tsym'] = symbol_from_db
            else:
                logger.warning(f"Zebu Portfolio - Product Value for {symbol} Not Found or Changed.")
    
    return portfolio_data

def calculate_portfolio_statistics(holdings_data):
    totalholdingvalue = 0
    totalinvvalue = 0
    totalprofitandloss = 0
    totalpnlpercentage = 0

    # Check if the data is valid
    if not isinstance(holdings_data, list):
        logger.error("Error: Holdings data is not a list.")
        return {
            'totalholdingvalue': totalholdingvalue,
            'totalinvvalue': totalinvvalue,
            'totalprofitandloss': totalprofitandloss,
            'totalpnlpercentage': totalpnlpercentage
        }

    # Handle empty list gracefully - it's not an error
    if len(holdings_data) == 0:
        logger.debug("No holdings to calculate statistics for (empty list)")
        return {
            'totalholdingvalue': totalholdingvalue,
            'totalinvvalue': totalinvvalue,
            'totalprofitandloss': totalprofitandloss,
            'totalpnlpercentage': totalpnlpercentage
        }

    # Iterate over the list of holdings
    for holding in holdings_data:
        # Ensure 'stat' is 'Ok' before proceeding
        if holding.get('stat') != 'Ok':
            logger.error(f"Error: {holding.get('emsg', 'Unknown error occurred.')}")
            continue

        # Filter out the NSE entry and ignore BSE for the same symbol
        nse_entry = next((exch for exch in holding.get('exch_tsym', []) if exch.get('exch') == 'NSE'), None)
        if not nse_entry:
            continue  # Skip if no NSE entry is found

        # Process only the NSE entry
        quantity = float(holding.get('holdqty', 0)) + max(float(holding.get('npoadt1qty', 0)) , float(holding.get('dpqty', 0)))
        upload_price = float(holding.get('upldprc', 0))
        market_price = float(nse_entry.get('upldprc', 0))  # Assuming 'pp' is the market price for NSE

        # Calculate investment value and holding value for NSE
        inv_value = quantity * upload_price
        holding_value = quantity * upload_price
        profit_and_loss = holding_value - inv_value
        pnl_percentage = (profit_and_loss / inv_value) * 100 if inv_value != 0 else 0

        # Accumulate the totals
        #totalholdingvalue += holding_value
        totalinvvalue += inv_value
        totalprofitandloss += profit_and_loss

        # Valuation formula from API
        holdqty = float(holding.get('holdqty', 0))
        btstqty = float(holding.get('btstqty', 0))
        brkcolqty = float(holding.get('brkcolqty', 0))
        unplgdqty = float(holding.get('unplgdqty', 0))
        benqty = float(holding.get('benqty', 0))
        npoadqty = float(holding.get('npoadt1qty', 0))
        dpqty = float(holding.get('dpqty', 0))
        usedqty = float(holding.get('usedqty', 0))

        # Valuation formula from API
        valuation = ((btstqty + holdqty + brkcolqty + unplgdqty + benqty + max(npoadqty, dpqty)) - usedqty)*upload_price
        logger.debug(f"test valuation: {str(npoadqty)}")
        logger.debug(f"test valuation: {str(upload_price)}")
        # Accumulate total valuation
        totalholdingvalue += valuation

    # Calculate overall P&L percentage
    totalpnlpercentage = (totalprofitandloss / totalinvvalue) * 100 if totalinvvalue != 0 else 0

    return {
        'totalholdingvalue': totalholdingvalue,
        'totalinvvalue': totalinvvalue,
        'totalprofitandloss': totalprofitandloss,
        'totalpnlpercentage': totalpnlpercentage
    }

def transform_holdings_data(holdings_data):
    """
    Transforms Tradejini holdings data to OpenAlgo format.
    
    Args:
        holdings_data (list): List of holdings dictionaries from TradeJini API
        
    Returns:
        dict: Holdings data in OpenAlgo format
        {
            "data": {
                "holdings": [
                    {
                        "exchange": "NSE",
                        "pnl": 3.27,
                        "pnlpercent": 13.04,
                        "product": "CNC",
                        "quantity": 1,
                        "symbol": "BSLNIFTY"
                    }
                ],
                "statistics": {
                    "totalholdingvalue": 36.46,
                    "totalinvvalue": 32.17,
                    "totalpnlpercentage": 13.34,
                    "totalprofitandloss": 4.29
                }
            },
            "status": "success"
        }
    """
    try:
        # Handle empty list case gracefully - it's not an error
        if isinstance(holdings_data, list) and len(holdings_data) == 0:
            logger.debug("No holdings to transform (empty list)")
            # Return empty list for service layer
            return []

        logger.debug(f"Transforming {len(holdings_data) if isinstance(holdings_data, list) else 0} holdings records")

        # Initialize statistics
        statistics = {
            'totalholdingvalue': 0.0,
            'totalinvvalue': 0.0,
            'totalprofitandloss': 0.0,
            'totalpnlpercentage': 0.0
        }

        # Transform individual holdings
        transformed_holdings = []

        if not isinstance(holdings_data, list):
            logger.error("Holdings data is not a list")
            # Return empty list for consistency
            return []
            
        for holding in holdings_data:
            try:
                if not isinstance(holding, dict):
                    logger.warning("Non-dict item in holdings list")
                    continue
                    
                # Get symbol details from the sym object
                sym = holding.get('sym', {})

                # Skip if we don't have basic required data
                # Check both tradSymbol and tradSymbol (different capitalizations)
                trade_symbol = sym.get('tradSymbol') or sym.get('tradSymbol') or sym.get('symbol', '')
                if not sym or not trade_symbol:
                    logger.warning(f"Missing symbol data in holding: {holding}")
                    continue

                # Get quantity - use saleable quantity if available, otherwise use total quantity
                quantity = float(holding.get('saleableQty', holding.get('qty', 0)))
                avg_price = float(holding.get('avgPrice', 0))
                ltp = float(sym.get('lastPrice', avg_price))  # Use last price if available, otherwise use avg price
                
                # Calculate P&L values
                pnl = float(holding.get('realizedPnl', 0))
                pnl_percent = 0.0
                
                # Calculate investment value and current value
                investment_value = quantity * avg_price
                current_value = quantity * ltp if ltp > 0 else investment_value
                
                # Calculate P&L percentage
                if investment_value > 0:
                    pnl_percent = ((current_value - investment_value) / investment_value) * 100
                
                # Map product type (CNC for delivery, MIS for intraday)
                product = 'CNC'  # Default to CNC (delivery)
                if holding.get('product', '').upper() in ['MIS', 'INTRADAY']:
                    product = 'MIS'
                
                # Create the transformed holding
                transformed_holding = {
                    "exchange": sym.get('exchange', 'NSE'),  # Default to NSE if not specified
                    "pnl": round(pnl, 2),
                    "pnlpercent": round(pnl_percent, 2),
                    "product": product,
                    "quantity": int(quantity),
                    "symbol": trade_symbol.strip(),
                    # Additional fields that might be useful
                    "avgprice": round(avg_price, 2),
                    "ltp": round(ltp, 2),
                    "investment": round(investment_value, 2),
                    "current_value": round(current_value, 2)
                }
                
                # Update statistics
                statistics['totalholdingvalue'] += current_value
                statistics['totalinvvalue'] += investment_value
                statistics['totalprofitandloss'] += (current_value - investment_value)
                
                transformed_holdings.append(transformed_holding)
                
            except Exception as e:
                logger.error(f"Error transforming holding: {str(e)}\nHolding data: {holding}", exc_info=True)
                continue
        
        # Calculate final statistics
        if statistics['totalinvvalue'] > 0:
            statistics['totalpnlpercentage'] = (statistics['totalprofitandloss'] / statistics['totalinvvalue']) * 100
        
        # Round all statistics to 2 decimal places
        for key in statistics:
            statistics[key] = round(statistics[key], 2)

        # Return just the holdings list - service layer handles statistics separately
        return transformed_holdings
        
    except Exception as e:
        logger.error(f"Error in transform_holdings_data: {str(e)}", exc_info=True)
        # Return empty list on error for consistency
        return []