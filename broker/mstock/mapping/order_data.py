import json
from database.token_db import get_symbol, get_oa_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


def map_broker_exchange_to_openalgo(broker_exchange, instrumenttype=''):
    """
    Maps mStock broker exchange to OpenAlgo exchange format.
    mStock returns NSE for both equity and derivatives,
    but OpenAlgo uses NFO for derivatives.

    Parameters:
    - broker_exchange: Exchange from mStock API (e.g., 'NSE', 'BSE', 'MCX')
    - instrumenttype: Instrument type (e.g., 'OPTIDX', 'OPTSTK', 'FUTIDX', 'FUTSTK')

    Returns:
    - OpenAlgo exchange format (e.g., 'NFO' for NSE derivatives)
    """
    if instrumenttype in ['OPTIDX', 'OPTSTK', 'FUTIDX', 'FUTSTK']:
        if broker_exchange == 'NSE':
            return 'NFO'
        elif broker_exchange == 'BSE':
            return 'BFO'

    # For equity and other instruments, return as-is
    return broker_exchange


def map_order_data(order_data):
    """
    Processes and modifies order data from mStock Type B API.
    Converts broker symbols to OpenAlgo symbols and maps product types.

    Parameters:
    - order_data: Response from mStock Type B orders API

    Returns:
    - List of processed order dictionaries
    """
    if not order_data or 'data' not in order_data or order_data['data'] is None:
        logger.info("No order data available.")
        return []

    order_data = order_data['data']
    logger.info(f"{order_data}")

    if order_data:
        for order in order_data:
            # Extract symboltoken, exchange, and instrumenttype
            symboltoken = order.get('symboltoken')
            exchange = order.get('exchange')
            instrumenttype = order.get('instrumenttype', '')
            broker_tradingsymbol = order.get('tradingsymbol', '')

            # Determine correct exchange for derivatives
            # For options/futures, use NFO instead of NSE for symbol lookup
            lookup_exchange = exchange
            if instrumenttype in ['OPTIDX', 'OPTSTK', 'FUTIDX', 'FUTSTK']:
                if exchange == 'NSE':
                    lookup_exchange = 'NFO'
                elif exchange == 'BSE':
                    lookup_exchange = 'BFO'

            # Get OpenAlgo symbol from database using symboltoken
            if symboltoken and exchange:
                symbol_from_db = get_symbol(symboltoken, lookup_exchange)
                if symbol_from_db:
                    order['tradingsymbol'] = symbol_from_db
                    logger.debug(f"Found symbol via token: {symbol_from_db}")
                else:
                    # Fallback: Try converting broker symbol to OA format
                    if broker_tradingsymbol:
                        oa_symbol = get_oa_symbol(broker_tradingsymbol, lookup_exchange)
                        if oa_symbol:
                            order['tradingsymbol'] = oa_symbol
                            logger.debug(f"Converted broker symbol {broker_tradingsymbol} to OA format: {oa_symbol}")
                        else:
                            logger.info(f"Symbol not found for token {symboltoken} or brsymbol {broker_tradingsymbol} on {lookup_exchange}. Keeping original.")

            # Map product types to OpenAlgo format
            producttype = order.get('producttype', '')
            if (exchange in ['NSE', 'BSE']) and producttype == 'DELIVERY':
                order['producttype'] = 'CNC'
            elif producttype == 'INTRADAY':
                order['producttype'] = 'MIS'
            elif exchange in ['NFO', 'MCX', 'BFO', 'CDS'] and producttype == 'CARRYFORWARD':
                order['producttype'] = 'NRML'

            # Normalize status values for statistics
            status = order.get('status', '').lower()
            if 'traded' in status or 'complete' in status:
                order['normalized_status'] = 'complete'
            elif 'pending' in status or 'open' in status or 'o-pending' in status:
                order['normalized_status'] = 'open'
            elif 'rejected' in status or 'cancelled' in status:
                order['normalized_status'] = 'rejected'
            elif 'cancelled' in status:
                order['normalized_status'] = 'cancelled'
            else:
                order['normalized_status'] = status

    return order_data


def calculate_order_statistics(order_data):
    """
    Calculates statistics from mStock Type B order data.

    Parameters:
    - order_data: List of order dictionaries

    Returns:
    - Dictionary containing counts of different types of orders
    """
    total_buy_orders = total_sell_orders = 0
    total_completed_orders = total_open_orders = total_rejected_orders = total_cancelled_orders = 0

    if order_data:
        for order in order_data:
            # Count buy and sell orders using Type B field name
            if order.get('transactiontype') == 'BUY':
                total_buy_orders += 1
            elif order.get('transactiontype') == 'SELL':
                total_sell_orders += 1

            # Count orders based on normalized status
            normalized_status = order.get('normalized_status', '').lower()
            if normalized_status == 'complete':
                total_completed_orders += 1
            elif normalized_status == 'open':
                total_open_orders += 1
            elif normalized_status == 'rejected':
                total_rejected_orders += 1
            elif normalized_status == 'cancelled':
                total_cancelled_orders += 1

    return {
        'total_buy_orders': total_buy_orders,
        'total_sell_orders': total_sell_orders,
        'total_completed_orders': total_completed_orders,
        'total_open_orders': total_open_orders,
        'total_rejected_orders': total_rejected_orders,
        'total_cancelled_orders': total_cancelled_orders
    }


def transform_order_data(orders):
    """
    Transforms mStock Type B order data to OpenAlgo format.

    Parameters:
    - orders: List of order dictionaries from mStock Type B API

    Returns:
    - List of orders in OpenAlgo format
    """
    if isinstance(orders, dict):
        orders = [orders]

    transformed_orders = []

    for order in orders:
        if not isinstance(order, dict):
            logger.warning(f"Warning: Expected a dict, but found a {type(order)}. Skipping this item.")
            continue

        # Map order type to OpenAlgo format
        ordertype = order.get("ordertype", "")
        if ordertype == 'STOP_LOSS':
            ordertype = 'SL'
        elif ordertype == 'STOPLOSS_MARKET':
            ordertype = 'SL-M'

        # Normalize status to OpenAlgo format (lowercase)
        status = order.get("status", "")
        if status == "Traded" or "TRADE CONFIRMED" in status:
            order_status = "complete"
        elif status in ["O-Pending", "Pending", "pending", "O-Modified", "o-modified"]:
            order_status = "open"
        elif status == "Rejected" or status == "rejected":
            order_status = "rejected"
        elif status in ["Cancelled", "cancelled", "O-Cancelled", "o-cancelled"]:
            order_status = "cancelled"
        elif "trigger pending" in status.lower():
            order_status = "trigger pending"
        else:
            order_status = status.lower() if status else ""

        # Determine price based on order type and status
        # For LIMIT/SL orders: always show order price (unless completed, then show average)
        # For MARKET/SL-M orders: show average price
        if order_status == "complete":
            # For completed orders, show average execution price
            order_price = order.get("averageprice", 0.0)
        elif ordertype in ["LIMIT", "SL"]:
            # For LIMIT and SL orders (pending, open, rejected, cancelled), show order price
            order_price = order.get("price", 0.0)
        else:
            # For MARKET/SL-M orders, show average price (0 if pending)
            order_price = order.get("averageprice", 0.0)

        # Convert to float and handle string/numeric values
        try:
            order_price = float(order_price) if order_price else 0.0
        except (ValueError, TypeError):
            order_price = 0.0

        transformed_order = {
            "symbol": order.get("tradingsymbol", ""),
            "exchange": map_broker_exchange_to_openalgo(
                order.get("exchange", ""),
                order.get("instrumenttype", "")
            ),
            "action": order.get("transactiontype", ""),
            "quantity": order.get("quantity", 0),
            "price": order_price,
            "trigger_price": order.get("triggerprice", 0.0),
            "pricetype": ordertype,
            "product": order.get("producttype", ""),
            "orderid": order.get("orderid", ""),
            "order_status": order_status,
            "timestamp": order.get("updatetime", "")
        }

        transformed_orders.append(transformed_order)

    return transformed_orders


def map_trade_data(trade_data):
    """
    Processes and modifies trade data from mStock Type B API.

    Parameters:
    - trade_data: Response from mStock Type B tradebook API

    Returns:
    - List of processed trade dictionaries
    """
    if not trade_data or 'data' not in trade_data or trade_data['data'] is None:
        logger.info("No trade data available.")
        return []

    trade_data = trade_data['data']
    logger.info(f"Processing {len(trade_data)} trades")

    for trade in trade_data:
        # Type B tradebook API returns uppercase field names
        symboltoken = trade.get('SEC_ID', '')  # SEC_ID is the symboltoken in tradebook
        symbol = trade.get('SYMBOL', '')
        exchange = trade.get('EXCHANGE', '')
        instrument_name = trade.get('INSTRUMENT_NAME', '')

        # Determine correct exchange for derivatives
        lookup_exchange = exchange
        if instrument_name in ['OPTIDX', 'OPTSTK', 'FUTIDX', 'FUTSTK']:
            if exchange == 'NSE':
                lookup_exchange = 'NFO'
            elif exchange == 'BSE':
                lookup_exchange = 'BFO'

        if exchange:
            # First try: Get OpenAlgo symbol using symboltoken
            if symboltoken:
                symbol_from_db = get_symbol(symboltoken, lookup_exchange)
                if symbol_from_db:
                    trade['tradingsymbol'] = symbol_from_db
                    logger.debug(f"Found tradebook symbol via token: {symbol_from_db}")
                else:
                    # Symbol not found, try broker symbol conversion
                    if symbol:
                        if exchange in ['NSE', 'BSE'] and instrument_name == 'EQUITY':
                            brsymbol = f"{symbol}-EQ"
                        else:
                            brsymbol = symbol
                        oa_symbol = get_oa_symbol(brsymbol, lookup_exchange)
                        if oa_symbol:
                            trade['tradingsymbol'] = oa_symbol
                            logger.debug(f"Converted tradebook symbol {brsymbol} to OA format: {oa_symbol}")
                        else:
                            logger.info(f"Unable to find OA symbol for token {symboltoken} or brsymbol {brsymbol} on {lookup_exchange}. Using base symbol.")
                            trade['tradingsymbol'] = symbol
                    else:
                        trade['tradingsymbol'] = ''
            else:
                # No symboltoken, try broker symbol conversion
                if symbol:
                    if exchange in ['NSE', 'BSE'] and instrument_name == 'EQUITY':
                        brsymbol = f"{symbol}-EQ"
                    else:
                        brsymbol = symbol
                    oa_symbol = get_oa_symbol(brsymbol, lookup_exchange)
                    if oa_symbol:
                        trade['tradingsymbol'] = oa_symbol
                        logger.debug(f"Converted tradebook symbol {brsymbol} to OA format: {oa_symbol}")
                    else:
                        logger.info(f"Unable to find OA symbol for brsymbol {brsymbol} on {lookup_exchange}. Using base symbol.")
                        trade['tradingsymbol'] = symbol
                else:
                    trade['tradingsymbol'] = ''
        else:
            trade['tradingsymbol'] = symbol if symbol else ''

        # Map product types to OpenAlgo format
        # Type B API returns: CNC, INTRADAY (some might return DELIVERY)
        producttype = trade.get('PRODUCT', '')
        if (lookup_exchange in ['NSE', 'BSE']) and producttype == 'DELIVERY':
            trade['producttype'] = 'CNC'
        elif producttype == 'CNC':
            trade['producttype'] = 'CNC'
        elif producttype == 'INTRADAY':
            trade['producttype'] = 'MIS'
        elif lookup_exchange in ['NFO', 'MCX', 'BFO', 'CDS'] and producttype == 'CARRYFORWARD':
            trade['producttype'] = 'NRML'
        else:
            trade['producttype'] = producttype

    return trade_data


def transform_tradebook_data(tradebook_data):
    """
    Transforms mStock Type B tradebook data to OpenAlgo format.

    Parameters:
    - tradebook_data: List of trade dictionaries from mStock Type B API

    Returns:
    - List of trades in OpenAlgo format
    """
    transformed_data = []
    for trade in tradebook_data:
        # Type B tradebook API uses uppercase field names
        # After map_trade_data, we have 'tradingsymbol' and 'producttype' added

        # Convert PRICE to float, handle potential string values
        try:
            average_price = float(trade.get('PRICE', 0.0))
        except (ValueError, TypeError):
            average_price = 0.0

        # Convert TRADE_VALUE to float
        try:
            trade_value = float(trade.get('TRADE_VALUE', 0))
        except (ValueError, TypeError):
            trade_value = 0

        # Convert QUANTITY to int
        try:
            quantity = int(trade.get('QUANTITY', 0))
        except (ValueError, TypeError):
            quantity = 0

        # Normalize action to uppercase for consistency with orderbook
        action = trade.get('BUY_SELL', '')
        if action:
            action = action.upper()  # Convert "Buy" to "BUY", "Sell" to "SELL"

        transformed_trade = {
            "symbol": trade.get('tradingsymbol', ''),  # Mapped by map_trade_data
            "exchange": map_broker_exchange_to_openalgo(
                trade.get('EXCHANGE', ''),
                trade.get('INSTRUMENT_NAME', '')
            ),
            "product": trade.get('producttype', ''),  # Mapped by map_trade_data
            "action": action,  # BUY_SELL field from Type B API (normalized to uppercase)
            "quantity": quantity,
            "average_price": average_price,
            "trade_value": trade_value,
            "orderid": trade.get('ORDER_NUMBER', ''),  # ORDER_NUMBER field from Type B API
            "timestamp": trade.get('ORDER_DATE_TIME', '')  # ORDER_DATE_TIME field from Type B API
        }
        transformed_data.append(transformed_trade)

    return transformed_data


def map_position_data(position_data):
    """
    Processes and modifies position data from mStock Type B API.

    Parameters:
    - position_data: Response from mStock Type B positions API

    Returns:
    - List of processed position dictionaries
    """
    if not position_data or 'data' not in position_data or position_data['data'] is None:
        logger.info("No position data available.")
        return []

    position_data = position_data['data']
    logger.info(f"Processing {len(position_data)} positions")

    if position_data:
        for position in position_data:
            # Extract symboltoken, exchange, and instrumenttype for symbol lookup
            symboltoken = position.get('symboltoken')
            exchange = position.get('exchange')
            instrumenttype = position.get('instrumenttype', '')
            symbolname = position.get('symbolname', '')

            # Determine correct exchange for derivatives
            lookup_exchange = exchange
            if instrumenttype in ['OPTIDX', 'OPTSTK', 'FUTIDX', 'FUTSTK']:
                if exchange == 'NSE':
                    lookup_exchange = 'NFO'
                elif exchange == 'BSE':
                    lookup_exchange = 'BFO'

            # Get OpenAlgo symbol from database using symboltoken
            if symboltoken and exchange:
                symbol_from_db = get_symbol(symboltoken, lookup_exchange)
                if symbol_from_db:
                    position['tradingsymbol'] = symbol_from_db
                    logger.debug(f"Found position symbol via token: {symbol_from_db}")
                else:
                    # Fallback: Try converting broker symbolname to OA format
                    if symbolname:
                        oa_symbol = get_oa_symbol(symbolname, lookup_exchange)
                        if oa_symbol:
                            position['tradingsymbol'] = oa_symbol
                            logger.debug(f"Converted position symbol {symbolname} to OA format: {oa_symbol}")
                        else:
                            logger.info(f"Symbol not found for token {symboltoken} or symbolname {symbolname} on {lookup_exchange}. Keeping symbolname.")
                            position['tradingsymbol'] = symbolname
                    else:
                        position['tradingsymbol'] = ''

            # Map product types to OpenAlgo format
            producttype = position.get('producttype', '')
            if (exchange in ['NSE', 'BSE']) and producttype == 'DELIVERY':
                position['producttype'] = 'CNC'
            elif producttype == 'INTRADAY':
                position['producttype'] = 'MIS'
            elif exchange in ['NFO', 'MCX', 'BFO', 'CDS'] and producttype == 'CARRYFORWARD':
                position['producttype'] = 'NRML'

    return position_data


def transform_positions_data(positions_data):
    """
    Transforms mStock Type B positions data to OpenAlgo format.

    Parameters:
    - positions_data: List of position dictionaries (already mapped by map_position_data)

    Returns:
    - List of positions in OpenAlgo format
    """
    transformed_data = []

    # positions_data should already be a list after map_position_data
    if not positions_data or not isinstance(positions_data, list):
        return transformed_data

    for position in positions_data:
        # Convert netqty to int, handle string values
        try:
            quantity = int(position.get('netqty', 0))
        except (ValueError, TypeError):
            quantity = 0

        # Convert avgnetprice to float
        try:
            average_price = float(position.get('avgnetprice', 0.0))
        except (ValueError, TypeError):
            average_price = 0.0

        # mStock Type B API doesn't provide ltp directly in positions
        # Setting to "NA" as it requires separate market data API call
        ltp = "NA"

        # Use netvalue as P&L
        # netvalue represents the realized/unrealized profit/loss for the position
        try:
            pnl = float(position.get('netvalue', 0.0))
        except (ValueError, TypeError):
            pnl = 0.0

        transformed_position = {
            "symbol": position.get('tradingsymbol', ''),
            "exchange": map_broker_exchange_to_openalgo(
                position.get('exchange', ''),
                position.get('instrumenttype', '')
            ),
            "product": position.get('producttype', ''),  # Already mapped by map_position_data
            "quantity": quantity,
            "average_price": average_price,
            "ltp": ltp,  # Not available in Type B positions API
            "pnl": pnl,  # Using netvalue as pnl
        }
        transformed_data.append(transformed_position)

    return transformed_data


def transform_holdings_data(holdings_data):
    """
    Transforms mStock Type B holdings data to OpenAlgo format.

    Can handle two input formats:
    1. Raw API response: {"status": "true", "data": [...]}
    2. Mapped data from map_portfolio_data: {"holdings": [...], "totalholding": ...}

    mStock Type B holdings fields:
    - tradingsymbol, exchange, quantity, averageprice, ltp
    - profitandloss, pnlpercentage, isin, symboltoken, etc.

    Parameters:
    - holdings_data: Response from holdings API or mapped portfolio data

    Returns:
    - List of holdings in OpenAlgo format
    """
    transformed_data = []

    # Handle mapped data format (from map_portfolio_data)
    if 'holdings' in holdings_data and holdings_data['holdings']:
        holdings_list = holdings_data['holdings']
    # Handle raw API response format
    elif 'data' in holdings_data and holdings_data['data']:
        holdings_list = holdings_data['data']
    else:
        logger.info("No holdings data to transform")
        return transformed_data

    for holding in holdings_list:
        # Get symbol (already mapped by map_portfolio_data or raw)
        symbol = holding.get('tradingsymbol', '')

        # Get exchange, default to NSE for equity holdings
        exchange = holding.get('exchange') or 'NSE'

        # Map product type - mStock Type B returns DELIVERY or null for holdings
        producttype = holding.get('product', '')
        if producttype == 'DELIVERY' or not producttype:
            producttype = 'CNC'

        # Get quantity
        quantity = holding.get('quantity', 0)
        if isinstance(quantity, str):
            try:
                quantity = int(quantity)
            except (ValueError, TypeError):
                quantity = 0

        # Get P&L - mStock Type B uses 'profitandloss' and 'pnlpercentage'
        try:
            pnl = float(holding.get('profitandloss', 0) or 0)
        except (ValueError, TypeError):
            pnl = 0.0

        try:
            pnl_percent = float(holding.get('pnlpercentage', 0) or 0)
        except (ValueError, TypeError):
            pnl_percent = 0.0

        transformed_holding = {
            "symbol": symbol,
            "exchange": exchange,
            "quantity": quantity,
            "product": producttype,
            "pnl": round(pnl, 2),
            "pnlpercent": round(pnl_percent, 2)
        }
        transformed_data.append(transformed_holding)

    return transformed_data


def map_portfolio_data(portfolio_data):
    """
    Processes portfolio/holdings data from mStock Type B API.

    mStock Type B holdings API returns:
    {
        "status": "true",
        "message": "SUCCESS",
        "data": [
            {
                "tradingsymbol": "RELIANCE-EQ",
                "exchange": "NSE",
                "quantity": 10,
                "averageprice": 2500.50,
                "ltp": 2550.00,
                "profitandloss": 495.00,
                "pnlpercentage": 1.98,
                ...
            }
        ]
    }

    Parameters:
    - portfolio_data: Response from holdings API

    Returns:
    - Processed portfolio data with 'holdings' key for compatibility
    """
    logger.debug(f"map_portfolio_data received: {portfolio_data}")

    if portfolio_data.get('data') is None:
        logger.info("No portfolio data available.")
        return {}

    data = portfolio_data['data']

    # mStock Type B returns data as a flat array, not nested under 'holdings'
    # Convert to expected format for compatibility with OpenAlgo
    if isinstance(data, list):
        # Process each holding in the flat array
        holdings = []
        for holding in data:
            symbol = holding.get('tradingsymbol', '')
            exchange = holding.get('exchange') or 'NSE'

            # Get OpenAlgo symbol from broker symbol
            if symbol:
                oa_symbol = get_oa_symbol(symbol, exchange)
                if oa_symbol:
                    holding['tradingsymbol'] = oa_symbol

            # Map product type - mStock Type B returns DELIVERY or null for holdings
            product = holding.get('product', '')
            if product == 'DELIVERY' or not product:
                holding['product'] = 'CNC'

            holdings.append(holding)

        # Return in expected format with 'holdings' key
        return {
            'holdings': holdings,
            'totalholding': None  # mStock doesn't provide summary in same response
        }

    # Fallback for nested structure (if API changes)
    if isinstance(data, dict) and 'holdings' in data:
        for holding in data.get('holdings', []):
            symbol = holding.get('trading_symbol') or holding.get('tradingsymbol')
            exchange = holding.get('exchange')
            if symbol and exchange:
                oa_symbol = get_oa_symbol(symbol, exchange)
                if oa_symbol:
                    holding['tradingsymbol'] = oa_symbol

            if holding.get('product') == 'DELIVERY':
                holding['product'] = 'CNC'
        return data

    logger.warning(f"Unexpected portfolio data format: {type(data)}")
    return {}


def calculate_portfolio_statistics(holdings_data):
    """
    Calculates portfolio statistics from holdings data.

    mStock Type B doesn't provide a summary endpoint, so we calculate from holdings.

    Parameters:
    - holdings_data: Holdings response data (mapped or raw)

    Returns:
    - Dictionary with portfolio statistics
    """
    totalholdingvalue = 0
    totalinvvalue = 0
    totalprofitandloss = 0
    totalpnlpercentage = 0

    # Get holdings list from different formats
    holdings_list = []
    if 'holdings' in holdings_data and holdings_data['holdings']:
        holdings_list = holdings_data['holdings']
    elif 'data' in holdings_data and isinstance(holdings_data['data'], list):
        holdings_list = holdings_data['data']

    # Calculate totals from individual holdings
    if holdings_list:
        for holding in holdings_list:
            try:
                # Get quantity and prices
                quantity = float(holding.get('quantity', 0) or 0)
                avg_price = float(holding.get('averageprice', 0) or 0)
                ltp = float(holding.get('ltp', 0) or 0)
                pnl = float(holding.get('profitandloss', 0) or 0)

                # Calculate values
                inv_value = quantity * avg_price
                holding_value = quantity * ltp

                totalinvvalue += inv_value
                totalholdingvalue += holding_value
                totalprofitandloss += pnl
            except (ValueError, TypeError) as e:
                logger.warning(f"Error calculating holding stats: {e}")
                continue

        # Calculate overall P&L percentage
        if totalinvvalue > 0:
            totalpnlpercentage = round((totalprofitandloss / totalinvvalue) * 100, 2)

    return {
        'totalholdingvalue': round(totalholdingvalue, 2),
        'totalinvvalue': round(totalinvvalue, 2),
        'totalprofitandloss': round(totalprofitandloss, 2),
        'totalpnlpercentage': totalpnlpercentage
    }
