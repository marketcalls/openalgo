import json
from database.token_db import get_symbol, get_oa_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


def map_order_data(order_data):
    """
    Processes and modifies a list of order dictionaries based on specific conditions.

    Parameters:
    - order_data: A dictionary containing Samco order book response.

    Returns:
    - The modified order_data with updated 'tradingSymbol' and 'productCode' fields.
    """
    # Check if order_data is empty or doesn't have 'orderBookDetails' key
    if not order_data or 'orderBookDetails' not in order_data or order_data['orderBookDetails'] is None:
        logger.info("No data available.")
        return []

    order_data = order_data['orderBookDetails']
    logger.info(f"{order_data}")

    if order_data:
        for order in order_data:
            # Extract the symbol and exchange for the current order
            symbol = order.get('symbol', '')
            trading_symbol = order.get('tradingSymbol', '')
            exchange = order.get('exchange', '')

            # Use the get_oa_symbol function to fetch the OpenAlgo symbol from the database
            symbol_from_db = get_oa_symbol(trading_symbol, exchange)

            # Check if a symbol was found; if so, update the trading_symbol in the current order
            if symbol_from_db:
                order['tradingSymbol'] = symbol_from_db
                # Map product codes to OpenAlgo format
                product_code = order.get('productCode', '')
                if (order['exchange'] == 'NSE' or order['exchange'] == 'BSE') and product_code == 'CNC':
                    order['productCode'] = 'CNC'
                elif product_code == 'MIS':
                    order['productCode'] = 'MIS'
                elif order['exchange'] in ['NFO', 'MCX', 'BFO', 'CDS'] and product_code == 'NRML':
                    order['productCode'] = 'NRML'
            else:
                logger.info(f"Symbol not found for {trading_symbol} and exchange {exchange}. Keeping original trading symbol.")

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
    total_buy_orders = total_sell_orders = 0
    total_completed_orders = total_open_orders = total_rejected_orders = 0

    if order_data:
        for order in order_data:
            # Count buy and sell orders
            if order.get('transactionType') == 'BUY':
                total_buy_orders += 1
            elif order.get('transactionType') == 'SELL':
                total_sell_orders += 1

            # Count orders based on their status (Samco uses different status values)
            status = order.get('orderStatus', '').lower()
            if status in ['complete', 'executed']:
                total_completed_orders += 1
            elif status in ['open', 'pending', 'trigger pending']:
                total_open_orders += 1
            elif status == 'rejected':
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
    Transforms Samco order data to OpenAlgo standardized format.
    """
    if isinstance(orders, dict):
        orders = [orders]

    transformed_orders = []

    for order in orders:
        if not isinstance(order, dict):
            logger.warning(f"Warning: Expected a dict, but found a {type(order)}. Skipping this item.")
            continue

        # Map Samco order type to OpenAlgo format
        # Samco converts MKT orders to L with marketProtection, so check for that
        ordertype = order.get("orderType", "")
        market_protection = order.get("marketProtection")

        if ordertype == 'L' and market_protection:
            # Market order converted to Limit with market protection
            ordertype = 'MARKET'
        elif ordertype == 'L':
            ordertype = 'LIMIT'
        elif ordertype == 'MKT':
            ordertype = 'MARKET'
        elif ordertype == 'SL':
            ordertype = 'SL'
        elif ordertype == 'SL-M':
            ordertype = 'SL-M'

        transformed_order = {
            "symbol": order.get("tradingSymbol", ""),
            "exchange": order.get("exchange", ""),
            "action": order.get("transactionType", ""),
            "quantity": order.get("totalQuanity", 0),
            "price": order.get("orderPrice", 0.0),
            "trigger_price": order.get("triggerPrice", 0.0),
            "pricetype": ordertype,
            "product": order.get("productCode", ""),
            "orderid": order.get("orderNumber", ""),
            "order_status": order.get("orderStatus", ""),
            "timestamp": order.get("orderTime", "")
        }

        transformed_orders.append(transformed_order)

    return transformed_orders


def map_trade_data(trade_data):
    """
    Processes and modifies a list of trade dictionaries based on specific conditions.

    Parameters:
    - trade_data: A dictionary containing Samco trade book response.

    Returns:
    - The modified trade_data with updated 'tradingSymbol' and 'productCode' fields.
    """
    # Check if 'tradeBookDetails' is None or missing
    if not trade_data or 'tradeBookDetails' not in trade_data or trade_data['tradeBookDetails'] is None:
        logger.info("No trade data available.")
        return []

    trade_data = trade_data['tradeBookDetails']

    if trade_data:
        for trade in trade_data:
            symbol = trade.get('tradingSymbol', '')
            exchange = trade.get('exchange', '')

            symbol_from_db = get_oa_symbol(symbol, exchange)

            if symbol_from_db:
                trade['tradingSymbol'] = symbol_from_db
                product_code = trade.get('productCode', '')
                if (trade['exchange'] == 'NSE' or trade['exchange'] == 'BSE') and product_code == 'CNC':
                    trade['productCode'] = 'CNC'
                elif product_code == 'MIS':
                    trade['productCode'] = 'MIS'
                elif trade['exchange'] in ['NFO', 'MCX', 'BFO', 'CDS'] and product_code == 'NRML':
                    trade['productCode'] = 'NRML'
            else:
                logger.info(f"Unable to find the symbol {symbol} and exchange {exchange}. Keeping original trading symbol.")

    return trade_data


def transform_tradebook_data(tradebook_data):
    """
    Transforms Samco tradebook data to OpenAlgo standardized format.
    """
    transformed_data = []
    for trade in tradebook_data:
        transformed_trade = {
            "symbol": trade.get('tradingSymbol', ''),
            "exchange": trade.get('exchange', ''),
            "product": trade.get('productCode', ''),
            "action": trade.get('transactionType', ''),
            "quantity": trade.get('filledQuantity', 0),
            "average_price": trade.get('tradePrice', 0.0),
            "trade_value": trade.get('orderValue', 0),
            "orderid": trade.get('orderNumber', ''),
            "timestamp": trade.get('tradeTime', '')
        }
        transformed_data.append(transformed_trade)
    return transformed_data


def map_position_data(position_data):
    """
    Processes and modifies position data from Samco.
    """
    if not position_data or 'positionDetails' not in position_data or position_data['positionDetails'] is None:
        logger.info("No position data available.")
        return []

    positions = position_data['positionDetails']

    if positions:
        for position in positions:
            symbol = position.get('tradingSymbol', '')
            exchange = position.get('exchange', '')

            symbol_from_db = get_oa_symbol(symbol, exchange)

            if symbol_from_db:
                position['tradingSymbol'] = symbol_from_db
                product_code = position.get('productCode', '')
                if (position['exchange'] == 'NSE' or position['exchange'] == 'BSE') and product_code == 'CNC':
                    position['productCode'] = 'CNC'
                elif product_code == 'MIS':
                    position['productCode'] = 'MIS'
                elif position['exchange'] in ['NFO', 'MCX', 'BFO', 'CDS'] and product_code == 'NRML':
                    position['productCode'] = 'NRML'
            else:
                logger.info(f"Symbol not found for {symbol} and exchange {exchange}. Keeping original trading symbol.")

    return positions


def transform_positions_data(positions_data):
    """
    Transforms Samco positions data to OpenAlgo standardized format.
    """
    transformed_data = []
    for position in positions_data:
        transformed_position = {
            "symbol": position.get('tradingSymbol', ''),
            "exchange": position.get('exchange', ''),
            "product": position.get('productCode', ''),
            "quantity": position.get('netQuantity', 0),
            "average_price": position.get('averagePrice', 0.0),
            "ltp": position.get('lastTradedPrice', 0.0),
            "pnl": position.get('realizedProfitLoss', 0.0),
        }
        transformed_data.append(transformed_position)
    return transformed_data


def map_portfolio_data(portfolio_data):
    """
    Processes and modifies portfolio/holdings data from Samco.
    """
    if not portfolio_data or portfolio_data.get('status') != 'Success':
        logger.info("No portfolio data available.")
        return {}

    holdings = portfolio_data.get('holdingDetails', [])

    if holdings:
        for holding in holdings:
            symbol = holding.get('tradingSymbol', '')
            exchange = holding.get('exchange', 'NSE')

            symbol_from_db = get_oa_symbol(symbol, exchange)

            if symbol_from_db:
                holding['tradingSymbol'] = symbol_from_db

            # Samco holdings are typically CNC
            holding['product'] = 'CNC'

    return {
        'holdings': holdings,
        'totalholding': portfolio_data.get('holdingSummary', None)
    }


def transform_holdings_data(holdings_data):
    """
    Transforms Samco holdings data to OpenAlgo standardized format.
    """
    transformed_data = []
    holdings = holdings_data.get('holdings', [])

    for holding in holdings:
        transformed_holding = {
            "symbol": holding.get('tradingSymbol', ''),
            "exchange": holding.get('exchange', 'NSE'),
            "quantity": holding.get('holdingQuantity', 0),
            "product": holding.get('product', 'CNC'),
            "pnl": holding.get('profitAndLoss', 0.0),
            "pnlpercent": holding.get('pnlPercentage', 0.0)
        }
        transformed_data.append(transformed_holding)
    return transformed_data


def calculate_portfolio_statistics(holdings_data):
    """
    Calculates portfolio statistics from Samco holdings data.
    """
    totalholding = holdings_data.get('totalholding')

    if totalholding is None:
        return {
            'totalholdingvalue': 0,
            'totalinvvalue': 0,
            'totalprofitandloss': 0,
            'totalpnlpercentage': 0
        }

    return {
        'totalholdingvalue': totalholding.get('totalHoldingValue', 0),
        'totalinvvalue': totalholding.get('totalInvestmentValue', 0),
        'totalprofitandloss': totalholding.get('totalProfitAndLoss', 0),
        'totalpnlpercentage': totalholding.get('totalPnlPercentage', 0)
    }
