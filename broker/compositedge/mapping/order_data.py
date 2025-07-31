import json
from turtle import position
from database.token_db import get_symbol, get_oa_symbol 
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
    exchange_mapping = {
        "NSECM": "NSE",
        "BSECM": "BSE",
        "NSEFO": "NFO",
        "BSEFO": "BFO",
        "MCXFO": "MCX",
        "NSECD": "CDS"
    }
    
    
        # Check if 'data' is None
    #logger.info(f"order_data: {order_data}")

    if 'result' not in order_data or not order_data['result']:
        logger.info("No data available.")
        return []  # Return an empty list if no orders are available
    
    order_data = order_data['result']

    if order_data:
        for order in order_data:
            # Extract the instrument_token and exchange for the current order
            symboltoken = order['ExchangeInstrumentID']
            exch = order.get("ExchangeSegment", "")
            exchange = exchange_mapping.get(exch, exch)
            
            # Use the get_symbol function to fetch the symbol from the database
            symbol_from_db = get_symbol(symboltoken, exchange)
            
            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol_from_db:
                order['TradingSymbol'] = symbol_from_db

    #logger.info(f"orders: {order_data}")
   
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
            if order['OrderSide'] == 'BUY':
                total_buy_orders += 1
            elif order['OrderSide'] == 'SELL':
                total_sell_orders += 1
            
            # Count orders based on their status
            if order['OrderStatus'] == 'Filled':
                total_completed_orders += 1
            elif order['OrderStatus'] == 'New':
                total_open_orders += 1
            elif order['OrderStatus'] == 'Rejected':
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

     # Define exchange mappings
    exchange_mapping = {
        "NSECM": "NSE",
        "BSECM": "BSE",
        "NSEFO": "NFO",
        "BSEFO": "BFO",
        "MCXFO": "MCX",
        "NSECD": "CDS"
    }
    
    # Define order type mappings
    order_type_mapping = {
            "Limit": "LIMIT",
            "Market": "MARKET",
            "StopLimit": "SL",
            "StopMarket": "SL-M"
        }
    # Define order status mappings
    order_status_mapping = {
        "Filled": "complete",
        "Rejected": "rejected",
        "Cancelled": "cancelled",
        "New": "open",
    }
    for order in orders:
        # Make sure each item is indeed a dictionary
        if not isinstance(order, dict):
            logger.warning(f"Warning: Expected a dict, but found a {type(order)}. Skipping this item.")
            continue
        exchange = order.get("ExchangeSegment", "")
        mapped_exchange = exchange_mapping.get(exchange, exchange)

        
        # Get the order type value and map it
        order_type = order.get("OrderType", "")
        mapped_order_type = order_type_mapping.get(order_type, order_type)  # Use mapped value if available

        # Map order status
        order_status = order.get("OrderStatus", "")
        mapped_order_status = order_status_mapping.get(order_status, order_status)

        transformed_order = {
            "symbol": order.get("TradingSymbol", ""),
            "exchange": mapped_exchange,
            "action": order.get("OrderSide", ""),
            "quantity": order.get("OrderQuantity", 0),
            "price": order.get("OrderPrice", 0.0),
            "trigger_price": order.get("OrderStopPrice", 0.0),
            "pricetype": mapped_order_type,
            "product": order.get("ProductType", ""),
            "orderid": order.get("AppOrderID", ""),
            "order_status": mapped_order_status,
            "timestamp": order.get("LastUpdateDateTime", "")
        }
        logger.info(f"Transformed order: {transformed_order}")
        transformed_orders.append(transformed_order)
        

    return transformed_orders



def map_trade_data(trade_data):
    """
    Processes and modifies a list of order dictionaries based on specific conditions.
    
    Parameters:
    - order_data: A list of dictionaries, where each dictionary represents an order.
    
    Returns:
    - The modified order_data with updated 'tradingsymbol' and 'product' fields.
    """
    exchange_mapping = {
        "NSECM": "NSE",
        "BSECM": "BSE",
        "NSEFO": "NFO",
        "BSEFO": "BFO",
        "MCXFO": "MCX",
        "NSECD": "CDS"
    }
    
        # Check if 'data' is None
    if 'result' not in trade_data or not trade_data['result']:
        logger.info("No data available.")
        return []  # Return an empty list if no orders are available
    
    trade_data = trade_data['result']

    if trade_data:

        for trade in trade_data:
            # Extract the instrument_token and exchange for the current order
            symboltoken = trade['ExchangeInstrumentID']
            exch = trade.get("ExchangeSegment", "")
            exchange = exchange_mapping.get(exch, exch)
            
            # Use the get_symbol function to fetch the symbol from the database
            symbol_from_db = get_symbol(symboltoken, exchange)
            
            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol_from_db:
                trade['TradingSymbol'] = symbol_from_db


    logger.info(f"trade_data: {trade_data}")
   
    return trade_data




def transform_tradebook_data(tradebook_data):
    transformed_data = []

    # Define exchange mappings
    exchange_mapping = {
        "NSECM": "NSE",
        "BSECM": "BSE",
        "NSEFO": "NFO",
        "BSEFO": "BFO",
        "MCXFO": "MCX",
        "NSECD": "CDS"
    }
    
   
    for trade in tradebook_data:

        exchange = trade.get("ExchangeSegment", "")
        mapped_exchange = exchange_mapping.get(exchange, exchange)
        
        # Ensure quantity and average price are converted to the correct types
        quantity = int(trade.get('OrderQuantity', 0))
        average_price = float(trade.get('OrderAverageTradedPrice', 0.0))

        transformed_trade = {
            "symbol": trade.get('TradingSymbol', ''),
            "exchange": mapped_exchange,
            "product": trade.get('ProductType', ''),
            "action": trade.get('OrderSide', ''),
            "quantity": quantity,
            "average_price": average_price,
            "trade_value": quantity * average_price,
            "orderid": trade.get('AppOrderID', ''),
            "timestamp": trade.get('OrderGeneratedDateTime', '')
        }
        transformed_data.append(transformed_trade)
    return transformed_data


def map_position_data(position_data):
    """
     Processes and modifies a list of order dictionaries based on specific conditions.
     
     Parameters:
     - order_data: A list of dictionaries, where each dictionary represents an order.
     
     Returns:
     - The modified order_data with updated 'tradingsymbol' and 'product' fields.
    """
    # Check if 'data' is None
    #logger.info(f"order_data: {order_data}")
    if 'result' not in position_data or not position_data['result']:
        logger.info("No data available.")
        return []  # Return an empty list if no orders are available
    
    position_data = position_data['result']
 
    #logger.info(f"position_data: {position_data}")
    
 
    return position_data


def transform_positions_data(positions_data):
    logger.info(f"positions_data: {positions_data}")
    positions_data = positions_data.get("positionList", [])
    transformed_data = []
    # Define exchange mappings
    exchange_mapping = {
        "NSECM": "NSE",
        "BSECM": "BSE",
        "NSEFO": "NFO",
        "BSEFO": "BFO",
        "MCXFO": "MCX",
        "NSECD": "CDS"
    }
    if not isinstance(positions_data, list):
        logger.error(f"Error: positions_data is not a list. Received: {{type(positions_data)}} - {positions_data}")
        return transformed_data

    for position in positions_data:

        if not isinstance(position, dict):  # Ensure it's a dictionary
            logger.info(f"Skipping invalid position: {position}")
            continue
        symboltoken = position.get('ExchangeInstrumentId')
        
        exchange = position.get("ExchangeSegment", "")
        mapped_exchange = exchange_mapping.get(exchange, exchange)

        symbol_from_db = get_symbol(symboltoken, mapped_exchange)
        
        if symbol_from_db:
            position['TradingSymbol'] = symbol_from_db

        netqty = float(position.get('Quantity', 0))
        if netqty > 0 :
            net_amount = float(position.get('BuyAveragePrice', 0))
        elif netqty < 0:
            net_amount = float(position.get('SellAveragePrice', 0))
        else:
            net_amount = 0
        
        average_price = net_amount    
        # Ensure average_price is treated as a float, then format to a string with 2 decimal places
        average_price_formatted = "{:.2f}".format(average_price)

        transformed_position = {
            "symbol": position.get("TradingSymbol", ""),
            "exchange": mapped_exchange,
            "product": position.get('ProductType', ''),
            "quantity": position.get('Quantity', 0),
            "average_price": average_price_formatted,
            "ltp": position.get('ltp', 0.0),  
            "pnl": position.get('pnl', 0.0),  
        }
        #logger.info(f"Transformed Position: {transformed_position}") 
        transformed_data.append(transformed_position)
    return transformed_data

def transform_holdings_data(holdings_data):
    """
    Transforms holdings data into a standardized format for the frontend.
    
    Parameters:
    - holdings_data: A dictionary with 'holdings' key containing a list of holdings.
    
    Returns:
    - A list of transformed holdings in a standardized format.
    """
    logger.info(f"holdings_data: {holdings_data}")
    transformed_data = []
    
    # Check if holdings_data has the expected structure
    if not holdings_data or 'holdings' not in holdings_data:
        return transformed_data
    
    # Process each holding
    for holdings in holdings_data['holdings']:
        transformed_position = {
            "symbol": holdings.get('tradingsymbol', ''),
            "exchange": holdings.get('exchange', ''),
            "quantity": holdings.get('quantity', 0),
            "product": holdings.get('product', ''),
            "pnl": holdings.get('profitandloss', 0.0),
            "pnlpercent": holdings.get('pnlpercentage', 0.0)
        }
        transformed_data.append(transformed_position)
    
    return transformed_data

def map_portfolio_data(portfolio_data):
    logger.info(f"portfolio_data: {portfolio_data}")
    """
    Processes and modifies portfolio data from FivePaisaXTS API.
    
    Parameters:
    - portfolio_data: A dictionary containing the portfolio/holdings information from FivePaisaXTS API.
    
    Returns:
    - A dictionary with 'holdings' and 'totalholding' keys structured for the OpenAlgoXTS system.
    """
    # Check if response is valid and contains result data
    if not portfolio_data or portfolio_data.get('type') != 'success' or 'result' not in portfolio_data:
        logger.info("No data available.")
        return {'holdings': [], 'totalholding': None}
    
    # Extract the holdings data from the response
    result = portfolio_data['result']
    rms_holdings = result.get('RMSHoldings', {})
    holdings_data = rms_holdings.get('Holdings', {})
    
    # Create a list to store the transformed holdings
    holdings_list = []
    total_holding_value = 0
    total_inv_value = 0
    total_pnl = 0
    
    # Process each holding
    for isin, holding in holdings_data.items():
        # Extract NSE instrument ID for symbol lookup
        nse_instrument_id = holding.get('ExchangeNSEInstrumentId')
        exchange = 'NSE'  # Default to NSE for equity holdings
        
        # Get trading symbol from database using instrument ID and exchange
        trading_symbol = get_symbol(nse_instrument_id, exchange) or isin
        
        # Get quantity and buy price
        quantity = holding.get('HoldingQuantity', 0)
        buy_avg_price = holding.get('BuyAvgPrice', 0)
        
        # Calculate investment value
        inv_value = quantity * buy_avg_price
        
        # Create holding entry
        holding_entry = {
            'tradingsymbol': trading_symbol,  # Use actual trading symbol instead of ISIN
            'exchange': exchange,
            'quantity': quantity,
            'product': 'CNC',  # Assuming all holdings are delivery/CNC
            'buy_price': buy_avg_price,
            'investment_value': inv_value,
            'current_value': inv_value,  # Placeholder, ideally should be current market value
            'profitandloss': 0,  # Placeholder, should be calculated with current market price
            'pnlpercentage': 0  # Placeholder
        }
        
        holdings_list.append(holding_entry)
        
        # Update totals
        total_inv_value += inv_value
        total_holding_value += inv_value  # Placeholder, should be current market value
    
    # Create totalholding summary
    totalholding = {
        'totalholdingvalue': total_holding_value,
        'totalinvvalue': total_inv_value,
        'totalprofitandloss': total_pnl,
        'totalpnlpercentage': 0 if total_inv_value == 0 else (total_pnl / total_inv_value) * 100
    }
    
    # Return the structured data
    return {
        'holdings': holdings_list,
        'totalholding': totalholding
    }


def calculate_portfolio_statistics(holdings_data):
    """
    Calculates portfolio statistics from holdings data.
    
    Parameters:
    - holdings_data: A dictionary with 'holdings' and 'totalholding' keys.
    
    Returns:
    - A dictionary with portfolio statistics.
    """
    logger.info(f"holdings_data: {holdings_data}")
    
    # Check if totalholding exists and is not None
    if 'totalholding' not in holdings_data or holdings_data['totalholding'] is None:
        totalholdingvalue = 0
        totalinvvalue = 0
        totalprofitandloss = 0
        totalpnlpercentage = 0
    else:
        # Extract values from totalholding
        totalholdingvalue = holdings_data['totalholding'].get('totalholdingvalue', 0)
        totalinvvalue = holdings_data['totalholding'].get('totalinvvalue', 0)
        totalprofitandloss = holdings_data['totalholding'].get('totalprofitandloss', 0)
        totalpnlpercentage = holdings_data['totalholding'].get('totalpnlpercentage', 0)

    return {
        'totalholdingvalue': totalholdingvalue,
        'totalinvvalue': totalinvvalue,
        'totalprofitandloss': totalprofitandloss,
        'totalpnlpercentage': totalpnlpercentage
    }
