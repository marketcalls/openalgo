import json
from database.token_db import get_symbol, get_oa_symbol 
from broker.tradejini.mapping.transform_data import reverse_map_product_type
import logging

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

def map_order_data(order_data):
    """
    Processes and modifies a list of order dictionaries based on specific conditions.
    
    Parameters:
    - order_data: Tradejini API response containing order information
    
    Returns:
    - The modified order_data with updated fields
    """
    print(f"[DEBUG] map_order_data - Input order_data: {order_data}")
    
    # Check if response status is ok
    if order_data.get('stat') != 'Ok':
        print("[DEBUG] map_order_data - Error in API response")
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
           # print(f"[DEBUG] map_order_data - Processing order info: {order_info}")
            
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
    


def map_position_data(position_data):
    """
    Maps TradeJini position data to OpenAlgo format.
    
    Args:
        position_data: List of position dictionaries from TradeJini API
        
    Returns:
        List of mapped position dictionaries
    """
    if position_data is None or (isinstance(position_data, dict) and (position_data.get('s') != "ok")):
        print("No valid position data available.")
        return []
        
    mapped_positions = []
    
    for position in position_data:
        # Extract position details
        sym = position.get('sym', {})
        
        # Map product type
        product = position.get('product', '').lower()
        mapped_product = 'MIS'
        if product == 'delivery':
            mapped_product = 'CNC'
        elif product == 'intraday':
            mapped_product = 'MIS'
        elif product == 'margin':
            mapped_product = 'NRML'
        
        # Create mapped position
        mapped_position = {
            'tsym': sym.get('symbol', ''),
            'exch': sym.get('exchange', ''),
            'prd': mapped_product,
            'netqty': position.get('netQty', 0),
            'netavgprc': position.get('netAvgPrice', 0.0),
            'realizedpnl': position.get('realizedPnl', 0.0),
            'dayqty': position.get('dayPos', {}).get('dayQty', 0),
            'dayavg': position.get('dayPos', {}).get('dayAvg', 0.0),
            'dayrealizedpnl': position.get('dayPos', {}).get('dayRealizedPnl', 0.0)
        }
        
        mapped_positions.append(mapped_position)
    
    return mapped_positions

def transform_positions_data(positions_data):
    """
    Transforms mapped position data to OpenAlgo format.
    
    Args:
        positions_data: List of mapped position dictionaries
        
    Returns:
        List of positions in OpenAlgo format
    """
    transformed_data = []
    for position in positions_data:
        # Convert quantities to integers
        quantity = int(position.get('netqty', 0))
        day_quantity = int(position.get('dayqty', 0))
        
        # Convert prices to strings
        average_price = str(float(position.get('netavgprc', 0.0)))
        day_average_price = str(float(position.get('dayavg', 0.0)))
        
        # Calculate total P&L
        total_pnl = float(position.get('realizedpnl', 0.0)) + \
                   (quantity * (float(position.get('ltp', 0.0)) - float(position.get('netavgprc', 0.0))))
        
        transformed_position = {
            "symbol": position.get('tsym', ''),
            "exchange": position.get('exch', ''),
            "product": position.get('prd', ''),
            "quantity": quantity,
            "average_price": average_price,
            "day_quantity": day_quantity,
            "day_average_price": day_average_price,
            "total_pnl": str(total_pnl)
        }
        
        transformed_data.append(transformed_position)
    
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
    if not portfolio_data or not isinstance(portfolio_data, list):
        print("No data available or incorrect data format.")
        return []

    # Iterate over the portfolio_data list and process each entry
    for portfolio in portfolio_data:
        # Ensure 'stat' is 'Ok' before proceeding
        if portfolio.get('stat') != 'Ok':
            print(f"Error: {portfolio.get('emsg', 'Unknown error occurred.')}")
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
                print(f"Zebu Portfolio - Product Value for {symbol} Not Found or Changed.")
    
    return portfolio_data

def calculate_portfolio_statistics(holdings_data):
    totalholdingvalue = 0
    totalinvvalue = 0
    totalprofitandloss = 0
    totalpnlpercentage = 0

    # Check if the data is valid or contains an error
    if not holdings_data or not isinstance(holdings_data, list):
        print("Error: Invalid or missing holdings data.")
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
            print(f"Error: {holding.get('emsg', 'Unknown error occurred.')}")
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
        print("test valuation :"+str(npoadqty))
        print("test valuation :"+str(upload_price))
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
    """
    try:
        print(f"[DEBUG] Transforming holdings data: {holdings_data}")
        
        # Calculate statistics if we have holdings data
        statistics = {} if not holdings_data else calculate_portfolio_statistics(holdings_data)
        
        # Transform individual holdings
        transformed_holdings = []
        
        if not isinstance(holdings_data, list):
            print("[ERROR] Holdings data is not a list")
            return {"status": "error", "message": "Invalid holdings data format"}
            
        for holding in holdings_data:
            try:
                if not isinstance(holding, dict):
                    print("[WARNING] Non-dict item in holdings list")
                    continue
                    
                # Get symbol details from the sym object
                sym = holding.get('sym', {})
                
                # Skip if we don't have basic required data
                if not sym or not sym.get('tradSymbol'):
                    print("[WARNING] Missing symbol data")
                    continue
                    
                transformed_holding = {
                    "exchange": sym.get('exchange', ''),
                    "pnl": holding.get('realizedPnl', 0),
                    "pnlpercent": 0,
                    "product": map_product_type(holding.get('product', '').lower()),
                    "quantity": holding.get('qty', 0),
                    "symbol": sym.get('tradSymbol', '')
                }
                
                # Calculate pnl percentage safely
                try:
                    if holding.get('avgPrice', 0) != 0:
                        total_value = holding.get('avgPrice', 0) * holding.get('qty', 0)
                        transformed_holding["pnlpercent"] = round((holding.get('realizedPnl', 0) / total_value) * 100, 2)
                except (ZeroDivisionError, TypeError):
                    print("[WARNING] Could not calculate P&L percentage")
                    transformed_holding["pnlpercent"] = 0
                    
                transformed_holdings.append(transformed_holding)
                
            except Exception as e:
                print(f"[ERROR] Error transforming holding: {str(e)}")
                print(f"[DEBUG] Holding data: {holding}")
                continue
        
        return {
            "status": "success",
            "data": {
                "holdings": transformed_holdings,
                "statistics": statistics
            }
        }
        
    except Exception as e:
        print(f"[ERROR] Error in transform_holdings_data: {str(e)}")
        return {"status": "error", "message": str(e)}