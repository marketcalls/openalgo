import json
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
        # Check if 'data' is None
    if order_data is None or (isinstance(order_data, dict) and (order_data['stat'] == "Not_Ok")):
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
            symboltoken = order['token']
            exchange = order['exch']
            
            # Use the get_symbol function to fetch the symbol from the database
            symbol_from_db = get_symbol(symboltoken, exchange)
            
            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol_from_db:
                order['tsym'] = symbol_from_db
                if (order['exch'] == 'NSE' or order['exch'] == 'BSE') and order['prd'] == 'C':
                    order['prd'] = 'CNC'
                               
                elif order['prd'] == 'I':
                    order['prd'] = 'MIS'
                
                elif order['exch'] in ['NFO', 'MCX', 'BFO', 'CDS'] and order['prd'] == 'M':
                    order['prd'] = 'NRML'

                if(order['prctyp']=="MKT"):
                    order['prctyp']="MARKET"
                elif(order['prctyp']=="LMT"):
                    order['prctyp']="LIMIT"
                elif(order['prctyp']=="SL-MKT"):
                    order['prctyp']="SL-M"
                elif(order['prctyp']=="SL-LMT"):
                    order['prctyp']="SL"
                
            else:
                logger.info(f"Symbol not found for token {symboltoken} and exchange {exchange}. Keeping original trading symbol.")
                
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
            if order['trantype'] == 'B':
                order['trantype'] = 'BUY'
                total_buy_orders += 1
            elif order['trantype'] == 'S':
                order['trantype'] = 'SELL'
                total_sell_orders += 1
            
            # Count orders based on their status
            if order['status'] == 'COMPLETE':
                total_completed_orders += 1
            elif order['status'] == 'OPEN':
                total_open_orders += 1
            elif order['status'] == 'REJECTED':
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
    

    transformed_orders = []
    
    for order in orders:
        # Make sure each item is indeed a dictionary
        if not isinstance(order, dict):
            logger.warning(f"Warning: Expected a dict, but found a {type(order)}. Skipping this item.")
            continue

        transformed_order = {
            "symbol": order.get("tsym", ""),
            "exchange": order.get("exch", ""),
            "action": order.get("trantype", ""),
            "quantity": order.get("qty", 0),
            "price": order.get("prc", 0.0),
            "trigger_price": order.get("trgprc", 0.0),
            "pricetype": order.get("prctyp", ""),
            "product": order.get("prd", ""),
            "orderid": order.get("norenordno", ""),
            "order_status": order.get("status", "").lower(),
            "timestamp": order.get("norentm", "")
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
    if trade_data is None or (isinstance(trade_data, dict) and (trade_data['stat'] == "Not_Ok")):
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        logger.info("No data available.")
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
                logger.info(f"Unable to find the symbol {symbol} and exchange {exchange}. Keeping original trading symbol.")
                
    return trade_data




def transform_tradebook_data(tradebook_data):
    transformed_data = []
    for trade in tradebook_data:
        # Parse the timestamp from Zebu format "HH:MM:SS DD-MM-YYYY" to just "HH:MM:SS"
        timestamp = trade.get('norentm', '')
        if timestamp and ' ' in timestamp:
            # Extract just the time part (HH:MM:SS) from "HH:MM:SS DD-MM-YYYY"
            timestamp = timestamp.split(' ')[0]

        transformed_trade = {
            "symbol": trade.get('tsym', ''),
            "exchange": trade.get('exch', ''),
            "product": trade.get('prd', ''),
            "action": trade.get('trantype', ''),
            "quantity": trade.get('qty', 0),
            "average_price": trade.get('avgprc', 0.0),
            "trade_value": float(trade.get('avgprc', 0)) * int(trade.get('qty', 0)),
            "orderid": trade.get('norenordno', ''),
            "timestamp": timestamp  # Now just "HH:MM:SS"
        }
        transformed_data.append(transformed_trade)
    return transformed_data


def map_position_data(position_data):

    if  position_data is None or (isinstance(position_data, dict) and (position_data['stat'] == "Not_Ok")):
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        logger.info("No data available.")
        position_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        position_data = position_data
        


    if position_data:
        for order in position_data:
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


                
                
            else:
                logger.info(f"Unable to find the symbol {symbol} and exchange {exchange}. Keeping original trading symbol.")
                
    return position_data


def transform_positions_data(positions_data):
    transformed_data = []
    for position in positions_data:
        # Get position values
        netqty = float(position.get('netqty', 0))
        netavgprc = float(position.get('netavgprc', 0.0))
        lp = float(position.get('lp', 0.0))  # Last Price from Zebu

        # Calculate PnL only if there's an open position
        if netqty != 0 and lp > 0:
            if netqty > 0:
                # Long position
                pnl = (lp - netavgprc) * netqty
            else:
                # Short position
                pnl = (netavgprc - lp) * abs(netqty)
        else:
            # No position or no LTP available
            pnl = 0.0
            lp = 0.0 if netqty == 0 else lp  # Set LTP to 0 if position is closed

        transformed_position = {
            "symbol": position.get('tsym', ''),
            "exchange": position.get('exch', ''),
            "product": position.get('prd', ''),
            "quantity": netqty,
            "average_price": netavgprc,
            "ltp": lp,
            "pnl": pnl
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
        logger.info("No data available or incorrect data format.")
        return []

    # Iterate over the portfolio_data list and process each entry
    for portfolio in portfolio_data:
        # Ensure 'stat' is 'Ok' before proceeding
        if portfolio.get('stat') != 'Ok':
            logger.info(f"Error: {portfolio.get('emsg', 'Unknown error occurred.')}")
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
                logger.info(f"Zebu Portfolio - Product Value for {symbol} Not Found or Changed.")
    
    return portfolio_data

def calculate_portfolio_statistics(holdings_data):
    totalholdingvalue = 0
    totalinvvalue = 0
    totalprofitandloss = 0
    totalpnlpercentage = 0

    # Check if the data is valid or contains an error
    if not holdings_data or not isinstance(holdings_data, list):
        logger.info("Error: Invalid or missing holdings data.")
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
            logger.info(f"Error: {holding.get('emsg', 'Unknown error occurred.')}")
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
        logger.info(f"test valuation :{npoadqty}")
        logger.info(f"test valuation :{upload_price}")
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
    transformed_data = []
    if isinstance(holdings_data, list):
        for holding in holdings_data:
            # Filter out only NSE exchange
            nse_entries = [exch for exch in holding.get('exch_tsym', []) if exch.get('exch') == 'NSE']
            for exch_tsym in nse_entries:
                transformed_position = {
                    "symbol": exch_tsym.get('tsym', ''),
                    "exchange": exch_tsym.get('exch', ''),
                    "quantity": int(holding.get('holdqty', 0)) + max(int(holding.get('npoadt1qty', 0)) , int(holding.get('dpqty', 0))),
                    "product": exch_tsym.get('product', 'CNC'),
                    "pnl": holding.get('profitandloss', 0.0),
                    "pnlpercent": holding.get('pnlpercentage', 0.0)
                }
                transformed_data.append(transformed_position)
    return transformed_data