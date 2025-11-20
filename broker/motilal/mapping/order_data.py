import json
from database.token_db import get_symbol, get_oa_symbol
from utils.logging import get_logger
from broker.motilal.mapping.transform_data import reverse_map_exchange

logger = get_logger(__name__)


def map_order_data(order_data):
    """
    Processes and modifies a list of order dictionaries based on specific conditions.
    
    Parameters:
    - order_data: A list of dictionaries, where each dictionary represents an order.
    
    Returns:
    - The modified order_data with updated 'tradingsymbol' and 'product' fields.
    """
    # Check if order_data is empty or doesn't have 'data' key
    if not order_data or 'data' not in order_data or order_data['data'] is None:
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        logger.info("No data available.")
        order_data = []  # Return empty list as the functions expect a list
    else:
        order_data = order_data['data']
        logger.info(f"{order_data}")
        


    if order_data:
        for order in order_data:
            # Extract the instrument_token and exchange for the current order
            symboltoken = order['symboltoken']
            motilal_exchange = order['exchange']
            # Convert Motilal exchange (NSEFO) to OpenAlgo exchange (NFO) for database lookup
            openalgo_exchange = reverse_map_exchange(motilal_exchange)

            # Use the get_symbol function to fetch the symbol from the database
            # Use OpenAlgo exchange format for lookup
            symbol_from_db = get_symbol(symboltoken, openalgo_exchange)

            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol_from_db:
                order['symbol'] = symbol_from_db  # Motilal uses 'symbol' field
                # Convert exchange to OpenAlgo format for display
                order['exchange'] = openalgo_exchange

                # Map Motilal product types to OpenAlgo format
                if openalgo_exchange in ['NSE', 'BSE']:
                    if order['producttype'] == 'DELIVERY':
                        order['producttype'] = 'CNC'
                    elif order['producttype'] == 'VALUEPLUS':
                        order['producttype'] = 'MIS'  # Motilal uses VALUEPLUS for margin intraday

                elif openalgo_exchange in ['NFO', 'MCX', 'CDS', 'BFO']:
                    # F&O segment product mapping
                    if order['producttype'] == 'NORMAL':
                        order['producttype'] = 'MIS'  # Motilal uses NORMAL for F&O intraday
                    elif order['producttype'] == 'VALUEPLUS':
                        order['producttype'] = 'NRML'
            else:
                logger.info(f"Symbol not found for token {symboltoken} and exchange {openalgo_exchange}. Keeping original trading symbol.")
                # Still convert exchange to OpenAlgo format
                order['exchange'] = openalgo_exchange

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
            # Count buy and sell orders - Motilal uses 'buyorsell' field
            if order.get('buyorsell', '').upper() == 'BUY':
                total_buy_orders += 1
            elif order.get('buyorsell', '').upper() == 'SELL':
                total_sell_orders += 1

            # Count orders based on their status - Motilal uses 'orderstatus' field
            order_status = order.get('orderstatus', '').lower()
            if order_status == 'traded' or order_status == 'complete':
                total_completed_orders += 1
            elif order_status in ['confirm', 'sent', 'open']:
                total_open_orders += 1
            elif order_status in ['rejected', 'error']:
                total_rejected_orders += 1
            # Note: 'cancel' status orders are not counted in statistics (following Angel One implementation)

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

        # Map Motilal order types to OpenAlgo standard format
        # Motilal returns: Market, Limit, Stoploss (title case)
        # OpenAlgo standard: MARKET, LIMIT, SL, SL-M (uppercase)
        ordertype = order.get("ordertype", "")
        if ordertype == 'Stoploss' or ordertype == 'STOPLOSS':
            # Determine if it's SL or SL-M based on trigger price
            if float(order.get("triggerprice", 0)) > 0:
                ordertype = 'SL'
            else:
                ordertype = 'SL-M'
        elif ordertype == 'Market':
            ordertype = 'MARKET'
        elif ordertype == 'Limit':
            ordertype = 'LIMIT'
        else:
            # Default to uppercase if unrecognized
            ordertype = ordertype.upper()

        # Map Motilal order status to OpenAlgo standard format
        # Motilal returns: Traded, Confirm, Sent, Error, Rejected, Cancel (title case)
        # OpenAlgo standard: complete, open, rejected, cancelled (lowercase)
        order_status = order.get("orderstatus", "")
        if order_status == 'Traded' or order_status == 'Complete':
            order_status = 'complete'
        elif order_status in ['Confirm', 'Sent', 'Open']:
            order_status = 'open'
        elif order_status in ['Rejected', 'Error']:
            order_status = 'rejected'
        elif order_status == 'Cancel':
            order_status = 'cancelled'
        else:
            # Keep lowercase for standard format
            order_status = order_status.lower()

        # Determine which price to use:
        # - For executed orders: use averageprice (execution price)
        # - For pending/open orders: use price (order price)
        avg_price = float(order.get("averageprice", 0.0))
        order_price = float(order.get("price", 0.0))

        # Log for debugging price issues
        if order_price == 0 and ordertype == 'LIMIT' and order_status == 'open':
            logger.warning(f"LIMIT order with open status has price=0.")
            logger.warning(f"Order ID: {order.get('uniqueorderid')}")
            logger.warning(f"Symbol: {order.get('symbol')}")
            logger.warning(f"Order Type: {order.get('ordertype')}")
            logger.warning(f"Order Status: {order.get('orderstatus')}")
            logger.warning(f"Raw price field value: '{order.get('price')}' (type: {type(order.get('price'))})")
            logger.warning(f"Raw averageprice field value: '{order.get('averageprice')}' (type: {type(order.get('averageprice'))})")
            logger.warning(f"Full raw order data: {json.dumps(order, indent=2)}")

        # If averageprice is 0, use the order price (for pending orders)
        display_price = avg_price if avg_price > 0 else order_price

        transformed_order = {
            "symbol": order.get("symbol", ""),  # Motilal uses 'symbol'
            "exchange": order.get("exchange", ""),
            "action": order.get("buyorsell", "").upper(),  # Ensure uppercase BUY/SELL
            "quantity": order.get("orderqty", 0),  # Motilal uses 'orderqty'
            "price": round(float(display_price), 2),  # Format to 2 decimal places
            "trigger_price": round(float(order.get("triggerprice", 0.0)), 2),  # Format to 2 decimal places
            "pricetype": ordertype,
            "product": order.get("producttype", ""),
            "orderid": order.get("uniqueorderid", ""),  # Motilal uses 'uniqueorderid'
            "order_status": order_status,  # Standardized lowercase status
            "timestamp": order.get("lastmodifiedtime", "")  # Motilal uses 'lastmodifiedtime'
        }

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
        # Check if 'data' is None
    if trade_data['data'] is None:
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        logger.info("No data available.")
        trade_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        trade_data = trade_data['data']
        


    if trade_data:
        for order in trade_data:
            # Extract the instrument_token and exchange for the current order
            symbol = order['symbol']  # Motilal uses 'symbol'
            motilal_exchange = order['exchange']
            # Convert Motilal exchange to OpenAlgo exchange for database lookup
            openalgo_exchange = reverse_map_exchange(motilal_exchange)

            # Use the get_symbol function to fetch the symbol from the database
            symbol_from_db = get_oa_symbol(symbol, openalgo_exchange)

            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol_from_db:
                order['symbol'] = symbol_from_db
                # Convert exchange to OpenAlgo format
                order['exchange'] = openalgo_exchange

                # Map Motilal product types to OpenAlgo format
                if openalgo_exchange in ['NSE', 'BSE']:
                    if order['producttype'] == 'DELIVERY':
                        order['producttype'] = 'CNC'
                    elif order['producttype'] == 'VALUEPLUS':
                        order['producttype'] = 'MIS'  # Motilal uses VALUEPLUS for margin intraday

                elif openalgo_exchange in ['NFO', 'MCX', 'CDS', 'BFO']:
                    if order['producttype'] == 'NORMAL':
                        order['producttype'] = 'MIS'  # Motilal uses NORMAL for F&O intraday
                    elif order['producttype'] == 'VALUEPLUS':
                        order['producttype'] = 'NRML'
            else:
                logger.info(f"Unable to find the symbol {symbol} and exchange {openalgo_exchange}. Keeping original trading symbol.")
                order['exchange'] = openalgo_exchange

    return trade_data




def transform_tradebook_data(tradebook_data):
    """
    Transforms Motilal Oswal tradebook data to OpenAlgo format.
    Motilal field names: symbol, buyorsell, tradeqty, tradeprice, tradetime, etc.
    """
    transformed_data = []
    for trade in tradebook_data:
        transformed_trade = {
            "symbol": trade.get('symbol', ''),  # Motilal uses 'symbol'
            "exchange": trade.get('exchange', ''),
            "product": trade.get('producttype', ''),
            "action": trade.get('buyorsell', ''),  # Motilal uses 'buyorsell'
            "quantity": trade.get('tradeqty', 0),  # Motilal uses 'tradeqty'
            "average_price": trade.get('tradeprice', 0.0),  # Motilal uses 'tradeprice'
            "trade_value": trade.get('tradevalue', 0),
            "orderid": trade.get('uniqueorderid', ''),  # Motilal uses 'uniqueorderid'
            "timestamp": trade.get('tradetime', '')  # Motilal uses 'tradetime'
        }
        transformed_data.append(transformed_trade)
    return transformed_data


def map_position_data(position_data):
    """
    Processes and modifies position data based on specific conditions.
    Motilal uses 'productname' field instead of 'producttype' for positions.

    Parameters:
    - position_data: Response from Motilal positions API

    Returns:
    - Modified position_data with updated symbols and product types
    """
    # Check if position_data is empty or doesn't have 'data' key
    if not position_data or 'data' not in position_data or position_data['data'] is None:
        logger.info("No position data available.")
        return []

    position_data_list = position_data['data']
    logger.info(f"Processing {len(position_data_list)} positions")

    if position_data_list:
        for position in position_data_list:
            # Extract the symboltoken and exchange for the current position
            symboltoken = position.get('symboltoken')
            motilal_exchange = position.get('exchange')
            # Convert Motilal exchange to OpenAlgo exchange for database lookup
            openalgo_exchange = reverse_map_exchange(motilal_exchange)

            # Use the get_symbol function to fetch the symbol from the database
            symbol_from_db = get_symbol(symboltoken, openalgo_exchange)

            # Check if a symbol was found; if so, update the symbol in the current position
            if symbol_from_db:
                position['symbol'] = symbol_from_db
                # Convert exchange to OpenAlgo format
                position['exchange'] = openalgo_exchange

                # Map Motilal product types to OpenAlgo format
                # Motilal uses 'productname' field for positions instead of 'producttype'
                productname = position.get('productname', '')

                if openalgo_exchange in ['NSE', 'BSE']:
                    # Cash segment product mapping
                    if productname == 'DELIVERY':
                        position['productname'] = 'CNC'
                    elif productname == 'VALUEPLUS':
                        position['productname'] = 'MIS'  # Motilal uses VALUEPLUS for margin intraday

                elif openalgo_exchange in ['NFO', 'MCX', 'CDS', 'BFO']:
                    # F&O segment product mapping
                    if productname == 'NORMAL':
                        position['productname'] = 'MIS'  # Motilal uses NORMAL for F&O intraday
                    elif productname == 'VALUEPLUS':
                        position['productname'] = 'NRML'
            else:
                logger.info(f"Symbol not found for token {symboltoken} and exchange {openalgo_exchange}. Keeping original symbol.")
                position['exchange'] = openalgo_exchange

    return position_data_list


def transform_positions_data(positions_data):
    """
    Transforms Motilal Oswal positions data to OpenAlgo format.
    Motilal doesn't have netqty - calculate from buyquantity and sellquantity.
    """
    transformed_data = []
    for position in positions_data:
        # Calculate net quantity from buy and sell quantities
        buyqty = int(position.get('buyquantity', 0))
        sellqty = int(position.get('sellquantity', 0))
        net_qty = buyqty - sellqty

        # Calculate average price (weighted average if needed)
        buyamt = float(position.get('buyamount', 0.0))
        sellamt = float(position.get('sellamount', 0.0))
        avg_price = 0.0
        if net_qty != 0:
            if net_qty > 0:  # Long position
                avg_price = buyamt / buyqty if buyqty > 0 else 0.0
            else:  # Short position
                avg_price = sellamt / sellqty if sellqty > 0 else 0.0

        transformed_position = {
            "symbol": position.get('symbol', ''),  # Motilal uses 'symbol'
            "exchange": position.get('exchange', ''),
            "product": position.get('productname', ''),  # Motilal uses 'productname'
            "quantity": net_qty,
            "average_price": avg_price,
            "ltp": position.get('LTP', 0.0),  # Motilal uses 'LTP'
            "pnl": position.get('marktomarket', 0.0) + position.get('bookedprofitloss', 0.0),  # Total P&L
        }
        transformed_data.append(transformed_position)
    return transformed_data

def transform_holdings_data(holdings_data):
    """
    Transforms Motilal Oswal holdings data to OpenAlgo format.
    Motilal returns data differently - check the API response structure.
    """
    transformed_data = []
    # Motilal returns holdings directly in the data array
    holdings_list = holdings_data if isinstance(holdings_data, list) else holdings_data.get('holdings', [])

    for holdings in holdings_list:
        # Calculate P&L percentage if not provided
        buy_avg = float(holdings.get('buyavgprice', 0.0))
        dp_qty = int(holdings.get('dpquantity', 0))
        # P&L calculation would need current price, which may not be in holdings response

        transformed_position = {
            "symbol": holdings.get('scripname', ''),  # Motilal uses 'scripname'
            "exchange": "NSE",  # Default to NSE, adjust based on scripcode mapping
            "quantity": dp_qty,
            "product": "CNC",  # Holdings are always CNC/DELIVERY
            "pnl": 0.0,  # Would need current price to calculate
            "pnlpercent": 0.0
        }
        transformed_data.append(transformed_position)
    return transformed_data

def map_portfolio_data(portfolio_data):
    """
    Processes Motilal Oswal portfolio/holdings data.
    Motilal returns holdings in a simple list format with DP holding data.

    Parameters:
    - portfolio_data: A dictionary containing holdings data

    Returns:
    - The modified portfolio_data with mapped fields.
    """
    # Motilal returns status as "SUCCESS" string
    if portfolio_data.get('status') != 'SUCCESS' or portfolio_data.get('data') is None:
        logger.info("No data available.")
        return {}

    # Directly work with 'data' for clarity and simplicity
    data = portfolio_data['data']

    # Motilal returns holdings as a list directly
    if isinstance(data, list):
        for portfolio in data:
            scripname = portfolio.get('scripname', '')
            # Map Motilal scripname to OpenAlgo symbol if needed
            # This would require looking up by ISIN or scripcode
            isin = portfolio.get('scripisinno', '')
            if isin:
                # Try to get symbol from database using ISIN
                symbol_from_db = get_oa_symbol(isin, 'NSE')
                if symbol_from_db:
                    portfolio['scripname'] = symbol_from_db

            # All holdings are CNC/DELIVERY product
            portfolio['product'] = 'CNC'

    return {'holdings': data, 'totalholding': None}  # Match expected structure


def calculate_portfolio_statistics(holdings_data):

    if holdings_data['totalholding'] is None:
        totalholdingvalue = 0
        totalinvvalue = 0
        totalprofitandloss = 0
        totalpnlpercentage = 0
    else:

        totalholdingvalue = holdings_data['totalholding']['totalholdingvalue']
        totalinvvalue = holdings_data['totalholding']['totalinvvalue']
        totalprofitandloss = holdings_data['totalholding']['totalprofitandloss']
        
        # To avoid division by zero in the case when total_investment_value is 0
        totalpnlpercentage = holdings_data['totalholding']['totalpnlpercentage']

    return {
        'totalholdingvalue': totalholdingvalue,
        'totalinvvalue': totalinvvalue,
        'totalprofitandloss': totalprofitandloss,
        'totalpnlpercentage': totalpnlpercentage
    }
