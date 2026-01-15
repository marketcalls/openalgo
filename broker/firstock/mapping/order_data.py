import json
from database.token_db import get_symbol, get_oa_symbol
from utils.logging import get_logger

logger = get_logger(__name__) 

def map_order_data(order_data):
    """
    Processes and modifies order data based on Firstock's format.
    Handles both raw API response and pre-mapped data.
    
    Parameters:
    - order_data: Either raw API response or list of pre-mapped orders
    
    Returns:
    - List of mapped orders in OpenAlgo format
    """
    # If it's a list, data is already mapped
    if isinstance(order_data, list):
        return order_data

    # If it's a dict with status/data, it's raw API response
    if isinstance(order_data, dict):
        if order_data.get('status') != 'success':
            logger.warning("No data available or invalid response.")
            return []
        orders = order_data.get('data', [])
    else:
        logger.info("Invalid order data format")
        return []

    mapped_orders = []
    for order in orders:
        mapped_order = {}
        # Get OpenAlgo symbol from token
        symbol_from_db = get_symbol(order.get('token'), order.get('exchange'))
        if symbol_from_db:
            mapped_order['tsym'] = symbol_from_db
        else:
            logger.info(f"Symbol not found for token {order.get('token')} and exchange {order.get('exchange')}.")
            mapped_order['tsym'] = order.get('tradingSymbol', '')

        # Map transaction type (will be converted to BUY/SELL in calculate_order_statistics)
        mapped_order['trantype'] = order.get('transactionType', '')
        
        # Map product type (will be converted in calculate_order_statistics)
        mapped_order['prd'] = order.get('product', '')
        
        # Map price type (will be converted in calculate_order_statistics)
        mapped_order['prctyp'] = order.get('priceType', '')
        
        # Map other fields
        mapped_order['norenordno'] = order.get('orderNumber', '')
        mapped_order['qty'] = order.get('quantity', '0')
        mapped_order['prc'] = order.get('price', '0.00')
        mapped_order['exch'] = order.get('exchange', '')
        mapped_order['status'] = order.get('status', '').upper()
        mapped_order['trgprc'] = order.get('triggerPrice', '0.00')
        mapped_order['norentm'] = order.get('orderTime', '')
        
        mapped_orders.append(mapped_order)
        
    return mapped_orders

def calculate_order_statistics(order_data):
    """
    Calculates statistics from order data, including totals for buy orders, sell orders,
    completed orders, open orders, and rejected orders.

    Parameters:
    - order_data: A list of dictionaries containing order data

    Returns:
    - A dictionary containing counts of different types of orders
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
            
            # Map product type
            if (order['exch'] == 'NSE' or order['exch'] == 'BSE') and order['prd'] == 'C':
                order['prd'] = 'CNC'
            elif order['prd'] == 'I':
                order['prd'] = 'MIS'
            elif order['exch'] in ['NFO', 'MCX', 'BFO', 'CDS'] and order['prd'] == 'M':
                order['prd'] = 'NRML'

            # Map price type
            if order['prctyp'] == "MKT":
                order['prctyp'] = "MARKET"
            elif order['prctyp'] == "LMT":
                order['prctyp'] = "LIMIT"
            elif order['prctyp'] == "SL-MKT":
                order['prctyp'] = "SL-M"
            elif order['prctyp'] == "SL-LMT":
                order['prctyp'] = "SL"
            
            # Count orders based on their status
            if order['status'] == 'COMPLETE':
                total_completed_orders += 1
            elif order['status'] == 'OPEN':
                total_open_orders += 1
            elif order['status'] == 'REJECTED':
                total_rejected_orders += 1

    return {
        'total_buy_orders': total_buy_orders,
        'total_sell_orders': total_sell_orders,
        'total_completed_orders': total_completed_orders,
        'total_open_orders': total_open_orders,
        'total_rejected_orders': total_rejected_orders
    }

def transform_order_data(orders):
    """
    Transform order data to match OpenAlgo format.
    
    Returns:
    - List of transformed orders in the format expected by orderbook.html
    """
    logger.info(f"Input orders: {orders}")
    if not orders:
        return []

    # First map the Firstock response to intermediate format
    mapped_orders = map_order_data(orders)

    logger.info(f"Mapped orders: {mapped_orders}")
    
    # Calculate statistics and transform order fields
    calculate_order_statistics(mapped_orders)

    # Transform to final format
    transformed_orders = []
    for order in mapped_orders:
        # Handle empty trigger price
        trigger_price = order.get("trgprc", "0.00")
        if not trigger_price or trigger_price == "":
            trigger_price = "0.00"

        transformed_order = {
            "symbol": order.get("tsym", ""),
            "exchange": order.get("exch", ""),
            "action": order.get("trantype", ""),
            "quantity": order.get("qty", "0"),
            "price": order.get("prc", "0.00"),
            "trigger_price": trigger_price,
            "pricetype": order.get("prctyp", ""),
            "product": order.get("prd", ""),
            "orderid": order.get("norenordno", ""),
            "order_status": order.get("status", "").lower(),
            "timestamp": order.get("norentm", "")
        }
        transformed_orders.append(transformed_order)

    logger.info(f"Final transformed orders: {transformed_orders}")
    return transformed_orders

def map_trade_data(trade_data):
    """
    Processes and modifies trade data based on Firstock's format.
    
    Parameters:
    - trade_data: Response from Firstock's tradebook API containing status and data fields
    
    Returns:
    - List of mapped trades in OpenAlgo format
    """
    # If it's a list, data is already mapped
    if isinstance(trade_data, list):
        return trade_data

    # If it's a dict with status/data, it's raw API response
    if isinstance(trade_data, dict):
        if trade_data.get('status') != 'success':
            logger.info("No data available or invalid response.")
            return []
        trades = trade_data.get('data', [])
    else:
        logger.info("Invalid trade data format")
        return []

    mapped_trades = []
    for trade in trades:
        mapped_trade = {}
        # Get OpenAlgo symbol from token
        symbol_from_db = get_symbol(trade.get('token'), trade.get('exchange'))
        if symbol_from_db:
            mapped_trade['tsym'] = symbol_from_db
        else:
            logger.info(f"Symbol not found for token {trade.get('token')} and exchange {trade.get('exchange')}.")
            mapped_trade['tsym'] = trade.get('tradingSymbol', '')

        # Map transaction type (will be converted to BUY/SELL)
        mapped_trade['trantype'] = trade.get('transactionType', '')
        
        # Map product type (will be converted to CNC/MIS/NRML)
        mapped_trade['prd'] = trade.get('product', '')
        
        # Map other fields
        mapped_trade['exch'] = trade.get('exchange', '')
        mapped_trade['qty'] = trade.get('fillQuantity', '0')
        mapped_trade['avgprc'] = trade.get('fillPrice', '0.00')
        mapped_trade['norenordno'] = trade.get('orderNumber', '')
        mapped_trade['norentm'] = trade.get('fillTime', '')
        
        mapped_trades.append(mapped_trade)
        
    return mapped_trades

def transform_tradebook_data(trades):
    """
    Transform trade data to match OpenAlgo format.
    
    Parameters:
    - trades: List of trades from map_trade_data
    
    Returns:
    - List of transformed trades in the format expected by tradebook.html
    """
    logger.info(f"Input trades: {trades}")
    if not trades:
        return []

    # First map the Firstock response to intermediate format
    mapped_trades = map_trade_data(trades)
    logger.info(f"Mapped trades: {mapped_trades}")
    
    # Transform to final format
    transformed_trades = []
    for trade in mapped_trades:
        # Convert transaction type
        if trade['trantype'] == 'B':
            trade['trantype'] = 'BUY'
        elif trade['trantype'] == 'S':
            trade['trantype'] = 'SELL'
            
        # Convert product type
        if (trade['exch'] == 'NSE' or trade['exch'] == 'BSE') and trade['prd'] == 'C':
            trade['prd'] = 'CNC'
        elif trade['prd'] == 'I':
            trade['prd'] = 'MIS'
        elif trade['exch'] in ['NFO', 'MCX', 'BFO', 'CDS'] and trade['prd'] == 'M':
            trade['prd'] = 'NRML'
            
        # Calculate trade value
        quantity = float(trade.get('qty', '0'))
        price = float(trade.get('avgprc', '0.00'))
        trade_value = quantity * price

        transformed_trade = {
            "symbol": trade.get("tsym", ""),
            "exchange": trade.get("exch", ""),
            "product": trade.get("prd", ""),
            "action": trade.get("trantype", ""),
            "quantity": trade.get("qty", "0"),
            "average_price": trade.get("avgprc", "0.00"),
            "trade_value": "{:.2f}".format(trade_value),
            "orderid": trade.get("norenordno", ""),
            "timestamp": trade.get("norentm", "")
        }
        transformed_trades.append(transformed_trade)

    logger.info(f"Final transformed trades: {transformed_trades}")
    return transformed_trades

def map_portfolio_data(portfolio_data):
    """
    Processes and modifies portfolio data based on Firstock's format.

    Parameters:
    - portfolio_data: Response from Firstock's holdings API containing status and data fields

    Returns:
    - List of mapped holdings in OpenAlgo format
    """
    logger.info(f"Raw portfolio data: {json.dumps(portfolio_data, indent=2)}")

    # If it's a list, data is already mapped
    if isinstance(portfolio_data, list):
        return portfolio_data

    # If it's a dict with status/data, it's raw API response
    if isinstance(portfolio_data, dict):
        if portfolio_data.get('status') != 'success':
            logger.info("No data available or invalid response.")
            return []
        holdings = portfolio_data.get('data', [])
    else:
        logger.info("Invalid portfolio data format")
        return []

    # Don't deduplicate - show all holdings as returned by Firstock (both NSE and BSE)
    mapped_holdings = []
    for holding in holdings:
        # Handle simple exchange/tradingSymbol structure (new Firstock format)
        if 'exchange' in holding and 'tradingSymbol' in holding:
            mapped_holding = {}

            # Map exchange trading fields
            mapped_holding['exch'] = holding.get('exchange', '')
            mapped_holding['token'] = holding.get('token', '')
            mapped_holding['trading_symbol'] = holding.get('tradingSymbol', '').replace('-EQ', '')  # Remove -EQ suffix
            mapped_holding['tsym'] = holding.get('tradingSymbol', '').replace('-EQ', '')  # Also set tsym
            mapped_holding['price_precision'] = int(holding.get('pricePrecision', '2'))
            mapped_holding['tick_size'] = float(holding.get('tickSize', '0.05'))
            mapped_holding['lot_size'] = int(holding.get('lotSize', '1'))

            # Get OpenAlgo symbol from token
            if holding.get('token'):
                symbol_from_db = get_symbol(holding.get('token'), holding.get('exchange'))
                if symbol_from_db:
                    mapped_holding['tsym'] = symbol_from_db
                else:
                    logger.info(f"Symbol not found for token {holding.get('token')} and exchange {holding.get('exchange')}.")
                    mapped_holding['tsym'] = mapped_holding['trading_symbol']
            else:
                mapped_holding['tsym'] = mapped_holding['trading_symbol']

            # Map holding fields - set default values for now
            lot_size = mapped_holding['lot_size']

            # Firstock holdings API only provides symbol info, no quantity or price data
            # Setting minimal defaults to maintain API contract
            mapped_holding['holdqty'] = '0'  # No quantity data available
            mapped_holding['btstqty'] = '0'
            mapped_holding['usedqty'] = '0'
            mapped_holding['trade_qty'] = '0'
            mapped_holding['sell_amount'] = '0.000000'

            # No price data available from Firstock holdings API
            mapped_holding['upldprc'] = "0.00"  # No average price data
            mapped_holding['s_prdt_ali'] = 'CNC'  # Default to CNC for holdings
            mapped_holding['cur_price'] = "0.00"  # No current price data

            # Add the holding
            mapped_holdings.append(mapped_holding)
        
    return mapped_holdings

def calculate_portfolio_statistics(holdings_data):
    """
    Calculates statistics from holdings data.
    
    Parameters:
    - holdings_data: List of holdings from map_portfolio_data
    
    Returns:
    - Dictionary containing portfolio statistics
    """
    totalholdingvalue = 0.0
    totalinvvalue = 0.0
    totalprofitandloss = 0.0
    totalpnlpercentage = 0.0

    if holdings_data:
        for holding in holdings_data:
            # Calculate total quantity in lots
            holdqty = int(float(holding.get('holdqty', 0)))
            btstqty = int(float(holding.get('btstqty', 0)))
            usedqty = int(float(holding.get('usedqty', 0)))
            trade_qty = int(float(holding.get('trade_qty', 0)))
            total_qty = holdqty + btstqty + trade_qty - usedqty

            # Get prices
            upld_price = float(holding.get('upldprc', 0.00))
            cur_price = float(holding.get('cur_price', 0.00))
            sell_amount = float(holding.get('sell_amount', 0.00))

            # Calculate values
            inv_value = total_qty * upld_price
            cur_value = total_qty * cur_price if cur_price > 0 else total_qty * upld_price
            
            # Update totals
            totalinvvalue += inv_value
            totalholdingvalue += cur_value
            totalprofitandloss += (cur_value - inv_value + sell_amount)

    # Calculate overall P&L percentage
    if totalinvvalue > 0:
        totalpnlpercentage = (totalprofitandloss / totalinvvalue) * 100

    return {
        'totalholdingvalue': round(totalholdingvalue, 2),
        'totalinvvalue': round(totalinvvalue, 2),
        'totalprofitandloss': round(totalprofitandloss, 2),
        'totalpnlpercentage': round(totalpnlpercentage, 2)
    }

def transform_holdings_data(holdings):
    """
    Transform holdings data to match OpenAlgo format.

    Parameters:
    - holdings: List of holdings from map_portfolio_data

    Returns:
    - List of transformed holdings in the format expected by holdings.html
    """
    logger.info(f"Input holdings: {holdings}")
    if not holdings:
        return []

    # Holdings are already mapped from map_portfolio_data
    mapped_holdings = holdings
    logger.info(f"Processing holdings: {mapped_holdings}")

    # Transform to final format
    transformed_holdings = []
    for holding in mapped_holdings:
        # Calculate total quantity in lots
        holdqty = int(float(holding.get('holdqty', 0)))
        btstqty = int(float(holding.get('btstqty', 0)))
        usedqty = int(float(holding.get('usedqty', 0)))
        trade_qty = int(float(holding.get('trade_qty', 0)))
        total_qty = holdqty + btstqty + trade_qty - usedqty

        # Get prices and amounts
        upld_price = float(holding.get('upldprc', 0.00))
        cur_price = float(holding.get('cur_price', 0.00))
        sell_amount = float(holding.get('sell_amount', 0.00))

        # Calculate P&L (will be 0 if no quantity/price data available)
        inv_value = total_qty * upld_price
        cur_value = total_qty * cur_price if cur_price > 0 else total_qty * upld_price
        pnl = cur_value - inv_value + sell_amount
        pnl_percent = (pnl / inv_value * 100) if inv_value > 0 else 0.0

        # Note: Firstock holdings API only provides symbol info
        # Quantity and P&L will be 0 due to API limitations
        transformed_holding = {
            "symbol": holding.get("tsym", ""),
            "exchange": holding.get("exch", ""),
            "quantity": total_qty,  # Will be 0 for Firstock
            "product": holding.get("s_prdt_ali", "CNC"),
            "pnl": round(pnl, 2),  # Will be 0 for Firstock
            "pnlpercent": round(pnl_percent, 2)  # Will be 0 for Firstock
        }
        transformed_holdings.append(transformed_holding)

    logger.info(f"Final transformed holdings: {transformed_holdings}")
    return transformed_holdings

def map_position_data(position_data):
    """
    Processes and modifies position data based on Firstock's format.
    
    Parameters:
    - position_data: Response from Firstock's position book API containing status and data fields
    
    Returns:
    - List of mapped positions in OpenAlgo format
    """
    # If it's a list, data is already mapped
    if isinstance(position_data, list):
        logger.debug("Position data is already mapped, returning as is")
        logger.debug(f"Number of positions: {len(position_data)}")
        return position_data

    # If it's a dict with status/data, it's raw API response
    if isinstance(position_data, dict):
        logger.debug("Raw position data received:")
        logger.info(f"DEBUG: Status: {position_data.get('status')}")
        logger.info(f"DEBUG: Data type: {type(position_data.get('data'))}")
        if position_data.get('status') != 'success':
            logger.info("No data available or invalid response.")
            logger.info(f"DEBUG: Error message: {position_data.get('message', 'No error message')}")
            return []
        positions = position_data.get('data', [])  # Firstock returns list of positions
        logger.debug(f"Number of positions extracted: {len(positions)}")
    else:
        logger.debug(f"Invalid position data format. Type received: {type(position_data)}")
        return []

    mapped_positions = []
    for position in positions:
        logger.debug("\nDEBUG: Processing position:")
        logger.debug(f"Raw position data: {json.dumps(position, indent=2)}")
        mapped_position = {}
        # Get OpenAlgo symbol from token
        symbol_from_db = get_symbol(position.get('token'), position.get('exchange'))
        logger.info(f"DEBUG: Looking up symbol - Token: {position.get('token')}, Exchange: {position.get('exchange')}")
        if symbol_from_db:
            mapped_position['tsym'] = symbol_from_db
            logger.debug(f"Symbol found in DB: {symbol_from_db}")
        else:
            logger.info(f"DEBUG: Symbol not found for token {position.get('token')} and exchange {position.get('exchange')}.")
            mapped_position['tsym'] = position.get('tradingSymbol', '')
            logger.info(f"DEBUG: Using trading symbol from response: {mapped_position['tsym']}")

        # Map product type (will be converted to CNC/MIS/NRML)
        mapped_position['prd'] = position.get('product', '')
        logger.info(f"DEBUG: Product type: {mapped_position['prd']}")
        
        # Map other fields
        mapped_position['exch'] = position.get('exchange', '')
        mapped_position['netqty'] = position.get('netQuantity', '0')
        mapped_position['netavgprc'] = position.get('netAveragePrice', '0.00')
        mapped_position['daybuyqty'] = position.get('dayBuyQuantity', '0')
        mapped_position['daysellqty'] = position.get('daySellQuantity', '0')
        mapped_position['daybuyamt'] = position.get('dayBuyAmount', '0.00')
        mapped_position['daybuyavgprc'] = position.get('dayBuyAveragePrice', '0.00')
        mapped_position['daysellamt'] = position.get('daySellAveragePrice', '0.00') # Using sell avg price as amount
        mapped_position['unrealizedmtom'] = position.get('unrealizedMTOM', '0.00')
        mapped_position['realizedpnl'] = position.get('RealizedPNL', '0.00')
        
        logger.debug(f"Mapped position data: {json.dumps(mapped_position, indent=2)}")
        mapped_positions.append(mapped_position)

    logger.debug(f"\nDEBUG: Total positions mapped: {len(mapped_positions)}")
    return mapped_positions

def transform_positions_data(positions):
    """
    Transform position data to match OpenAlgo format.
    
    Parameters:
    - positions: List of positions from map_position_data
    
    Returns:
    - List of transformed positions in the format expected by positionbook.html
    """
    logger.info(f"Input positions: {positions}")
    if not positions:
        return []

    # First map the Firstock response to intermediate format
    mapped_positions = map_position_data(positions)
    logger.info(f"Mapped positions: {mapped_positions}")
    
    # Transform to final format
    transformed_positions = []
    for position in mapped_positions:
        # Convert product type
        if (position['exch'] == 'NSE' or position['exch'] == 'BSE') and position['prd'] == 'C':
            position['prd'] = 'CNC'
        elif position['prd'] == 'I':
            position['prd'] = 'MIS'
        elif position['exch'] in ['NFO', 'MCX', 'BFO', 'CDS'] and position['prd'] == 'M':
            position['prd'] = 'NRML'

        transformed_position = {
            "symbol": position.get("tsym", ""),
            "exchange": position.get("exch", ""),
            "product": position.get("prd", ""),
            "quantity": position.get("netqty", "0"),
            "average_price": position.get("netavgprc", "0.00"),
            "last_price": "0.00",  # Not available in Firstock API
            "pnl": position.get("realizedpnl", "0.00"),
            "day_buy_quantity": position.get("daybuyqty", "0"),
            "day_sell_quantity": position.get("daysellqty", "0"),
            "day_buy_amount": position.get("daybuyamt", "0.00"),
            "day_sell_amount": position.get("daysellamt", "0.00"),
            "day_buy_average_price": position.get("daybuyavgprc", "0.00"),
            "day_sell_average_price": position.get("daysellamt", "0.00"),  # Using sell amount as avg price
            "unrealized_pnl": position.get("unrealizedmtom", "0.00"),
            "realized_pnl": position.get("realizedpnl", "0.00")
        }
        transformed_positions.append(transformed_position)

    logger.info(f"Final transformed positions: {transformed_positions}")
    return transformed_positions
