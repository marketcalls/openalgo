import json
from database.token_db import get_symbol, get_oa_symbol 
from broker.tradejini.mapping.transform_data import reverse_map_product_type

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
    print(f"[DEBUG] map_order_data - Found {len(orders_data)} orders in response")
    print(f"[DEBUG] map_order_data - Orders data: {orders_data}")
    
    # Process each order
    if orders_data:
        for order in orders_data:
            # Get the actual order data from the nested structure
            order_info = order.get('data', {})
            print(f"[DEBUG] map_order_data - Processing order info: {order_info}")
            
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
            
            print(f"[DEBUG] map_order_data - Updated order: {order}")
    
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
    print(f"[DEBUG] calculate_order_statistics - Input order_data: {order_data}")
    
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
    print(f"[DEBUG] transform_order_data - Input orders: {orders}")
    
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
        print(f"[DEBUG] transform_order_data - Transformed order: {transformed_order}")
    
    return transformed_orders



def map_trade_data(trade_data):
    """
    Processes and modifies a list of order dictionaries based on specific conditions.
    
    Parameters:
    - order_data: A list of dictionaries, where each dictionary represents an order.
    
    Returns:
    - The modified order_data with updated 'tradingsymbol' and 'product' fields.
    """
        # Check if 'data' is None
    if trade_data is None or (isinstance(trade_data, dict) and (trade_data['stat'] == "Not_Ok")):
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        print("No data available.")
        trade_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        trade_data = trade_data
        


    if trade_data:
        for order in trade_data:
            # Extract the instrument_token and exchange for the current order
            symbol = order['tsym']
            exchange = order['exch']
            
            # Use the get_symbol function to fetch the symbol from the database
            symbol_from_db = get_oa_symbol(symbol, exchange)
            
            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol_from_db:
                order['tsym'] = symbol_from_db
                if (order['exch'] == 'NSE' or order['exch'] == 'BSE') and order['prd'] == 'C':
                    order['prd'] = 'CNC'
                               
                elif order['prd'] == 'I':
                    order['prd'] = 'MIS'
                
                elif order['exch'] in ['NFO', 'MCX', 'BFO', 'CDS'] and order['prd'] == 'M':
                    order['prd'] = 'NRML'

                if(order['trantype']=="B"):
                    order['trantype']="BUY"
                elif(order['trantype']=="S"):
                    order['trantype']="SELL"
                
                
            else:
                print(f"Unable to find the symbol {symbol} and exchange {exchange}. Keeping original trading symbol.")
                
    return trade_data




def transform_tradebook_data(tradebook_data):
    """
    Transforms TradeJini trade book data to OpenAlgo format.
    
    Args:
        tradebook_data (list): List of trade records from TradeJini API
        
    Returns:
        list: List of trades in OpenAlgo format
    """
    transformed_data = []
    for trade in tradebook_data:
        # Get symbol details from the sym object
        symbol = trade.get('sym', {})
        
        transformed_trade = {
            "symbol": symbol.get('symbol', ''),
            "exchange": symbol.get('exchange', ''),
            "product": reverse_map_product_type(trade.get('product', '')),
            "action": trade.get('side', '').upper(),
            "quantity": trade.get('fillQty', 0),
            "price": trade.get('fillPrice', 0.0),
            "value": trade.get('fillValue', 0.0),
            "order_id": trade.get('orderId', ''),
            "trade_id": trade.get('fillId', ''),
            "average_price": trade.get('avgPrice', 0.0),
            "timestamp": trade.get('time', ''),
            "exchange_order_id": trade.get('exchOrderId', ''),
            "remarks": trade.get('remarks', ''),
            "leg_type": trade.get('legType', ''),
            "main_leg_order_id": trade.get('mainLegOrderId', ''),
            "tradingsymbol": symbol.get('tradSymbol', ''),
            "company_name": symbol.get('companyName', ''),
            "expiry": symbol.get('expiry', ''),
            "asset": symbol.get('asset', ''),
            "lot_size": symbol.get('lot', 0),
            "instrument_type": symbol.get('instrument', ''),
            "display_symbol": symbol.get('dispSymbol', ''),
            "price_tick": symbol.get('priceTick', 0.0)
        }
        transformed_data.append(transformed_trade)
    return transformed_data


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