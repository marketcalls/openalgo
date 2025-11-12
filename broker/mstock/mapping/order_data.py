import json
from database.token_db import get_symbol, get_oa_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


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
            # Extract symboltoken and exchange
            symboltoken = order.get('symboltoken')
            exchange = order.get('exchange')

            # Get OpenAlgo symbol from database
            if symboltoken and exchange:
                symbol_from_db = get_symbol(symboltoken, exchange)
                if symbol_from_db:
                    order['tradingsymbol'] = symbol_from_db
                else:
                    logger.info(f"Symbol not found for token {symboltoken} and exchange {exchange}. Keeping original trading symbol.")

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
        elif status in ["O-Pending", "Pending", "pending"]:
            order_status = "open"
        elif status == "Rejected" or status == "rejected":
            order_status = "rejected"
        elif status in ["Cancelled", "cancelled", "O-Cancelled", "o-cancelled"]:
            order_status = "cancelled"
        elif "trigger pending" in status.lower():
            order_status = "trigger pending"
        else:
            order_status = status.lower() if status else ""

        transformed_order = {
            "symbol": order.get("tradingsymbol", ""),
            "exchange": order.get("exchange", ""),
            "action": order.get("transactiontype", ""),
            "quantity": order.get("quantity", 0),
            "price": order.get("averageprice", 0.0),
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

    for trade in trade_data:
        # Get trading symbol from Type B response
        symbol = trade.get('SYMBOL') or trade.get('tradingsymbol')
        exchange = trade.get('EXCHANGE') or trade.get('exchange')

        if symbol and exchange:
            oa_symbol = get_oa_symbol(symbol, exchange)
            if oa_symbol:
                trade['tradingsymbol'] = oa_symbol
            else:
                logger.info(f"Unable to find the OA symbol for {symbol} and exchange {exchange}.")

        # Map product types to OpenAlgo format
        producttype = trade.get('PRODUCT') or trade.get('producttype', '')
        if producttype == 'DELIVERY' or producttype == 'CNC':
            trade['producttype'] = 'CNC'
        elif producttype == 'INTRADAY':
            trade['producttype'] = 'MIS'
        elif producttype == 'CARRYFORWARD':
            trade['producttype'] = 'NRML'

    return trade_data


def transform_tradebook_data(tradebook_data):
    """
    Transforms mStock Type B tradebook data to OpenAlgo format.

    Parameters:
    - tradebook_data: List of trade dictionaries

    Returns:
    - List of trades in OpenAlgo format
    """
    transformed_data = []
    for trade in tradebook_data:
        transformed_trade = {
            "symbol": trade.get('tradingsymbol', ''),
            "exchange": trade.get('EXCHANGE') or trade.get('exchange', ''),
            "product": trade.get('producttype') or trade.get('PRODUCT', ''),
            "action": trade.get('BUY_SELL') or trade.get('transactiontype', ''),
            "quantity": trade.get('QUANTITY') or trade.get('quantity', 0),
            "average_price": trade.get('PRICE') or trade.get('fillprice', 0.0),
            "trade_value": trade.get('TRADE_VALUE') or trade.get('tradevalue', 0),
            "orderid": trade.get('ORDER_NUMBER') or trade.get('orderid', ''),
            "timestamp": trade.get('ORDER_DATE_TIME') or trade.get('filltime', '')
        }
        transformed_data.append(transformed_trade)
    return transformed_data


def map_position_data(position_data):
    """
    Processes and modifies position data from mStock Type B API.
    """
    return map_order_data(position_data)


def transform_positions_data(positions_data):
    """
    Transforms mStock Type B positions data to OpenAlgo format.

    Parameters:
    - positions_data: List of position dictionaries or response dict

    Returns:
    - List of positions in OpenAlgo format
    """
    transformed_data = []

    # Handle both list and dict with 'data' key
    if isinstance(positions_data, dict):
        if 'data' in positions_data and positions_data['data']:
            positions_data = positions_data['data']
        else:
            return transformed_data

    if positions_data:
        for position in positions_data:
            # Map product type
            producttype = position.get('producttype', '')
            if producttype == 'DELIVERY':
                producttype = 'CNC'
            elif producttype == 'INTRADAY':
                producttype = 'MIS'
            elif producttype == 'CARRYFORWARD':
                producttype = 'NRML'

            transformed_position = {
                "symbol": position.get('tradingsymbol', ''),
                "exchange": position.get('exchange', ''),
                "product": producttype,
                "quantity": position.get('netqty') or position.get('net_quantity', 0),
                "average_price": position.get('avgnetprice') or position.get('average_price', 0.0),
                "ltp": position.get('ltp') or position.get('last_traded_price', 0.0),
                "pnl": position.get('pnl', 0.0),
            }
            transformed_data.append(transformed_position)

    return transformed_data


def transform_holdings_data(holdings_data):
    """
    Transforms mStock Type B holdings data to OpenAlgo format.

    Parameters:
    - holdings_data: Response from holdings API

    Returns:
    - List of holdings in OpenAlgo format
    """
    transformed_data = []

    if 'data' in holdings_data and holdings_data['data']:
        for holding in holdings_data['data']:
            # Map product type
            producttype = holding.get('product', '')
            if producttype == 'DELIVERY':
                producttype = 'CNC'

            transformed_holding = {
                "symbol": holding.get('trading_symbol') or holding.get('tradingsymbol', ''),
                "exchange": holding.get('exchange', ''),
                "quantity": holding.get('quantity', 0),
                "product": producttype,
                "pnl": holding.get('pnl', 0.0),
                "pnlpercent": holding.get('pnl_percentage') or holding.get('pnlpercentage', 0.0)
            }
            transformed_data.append(transformed_holding)

    return transformed_data


def map_portfolio_data(portfolio_data):
    """
    Processes portfolio/holdings data from mStock Type B API.

    Parameters:
    - portfolio_data: Response from holdings API

    Returns:
    - Processed portfolio data
    """
    if portfolio_data.get('data') is None:
        logger.info("No portfolio data available.")
        return {}

    data = portfolio_data['data']

    if 'holdings' in data and data['holdings']:
        for holding in data['holdings']:
            symbol = holding.get('trading_symbol') or holding.get('tradingsymbol')
            exchange = holding.get('exchange')
            if symbol and exchange:
                oa_symbol = get_oa_symbol(symbol, exchange)
                if oa_symbol:
                    holding['tradingsymbol'] = oa_symbol

            # Map product type
            if holding.get('product') == 'DELIVERY':
                holding['product'] = 'CNC'

    return data


def calculate_portfolio_statistics(holdings_data):
    """
    Calculates portfolio statistics from holdings data.

    Parameters:
    - holdings_data: Holdings response data

    Returns:
    - Dictionary with portfolio statistics
    """
    totalholdingvalue = 0
    totalinvvalue = 0
    totalprofitandloss = 0
    totalpnlpercentage = 0

    if 'data' in holdings_data and 'total_holding' in holdings_data['data']:
        total_holding = holdings_data['data']['total_holding']
        totalholdingvalue = total_holding.get('total_holding_value', 0)
        totalinvvalue = total_holding.get('total_investment_value', 0)
        totalprofitandloss = total_holding.get('total_pnl', 0)
        totalpnlpercentage = total_holding.get('total_pnl_percentage', 0)

    return {
        'totalholdingvalue': totalholdingvalue,
        'totalinvvalue': totalinvvalue,
        'totalprofitandloss': totalprofitandloss,
        'totalpnlpercentage': totalpnlpercentage
    }
