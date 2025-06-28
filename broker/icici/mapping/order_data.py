from database.token_db import get_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


def map_exchange(breeze_exchange_code):
    """Maps ICICI exchange code to OpenAlgo standard."""
    mapping = {
        "NSE": "NSE",
        "BSE": "BSE"
    }
    return mapping.get(breeze_exchange_code, breeze_exchange_code)


def map_order_data(order_data):
    """
    Maps ICICI order response data to OpenAlgo format.
    """
    if order_data is None:
        logger.info("No order data found.")
        return {}

    if isinstance(order_data, dict):
        order_data = [order_data]

    for order in order_data:
        token = order.get('stock_token')
        exchange = map_exchange(order.get('exchange_code', ''))
        symbol = get_symbol(token, exchange)

        if symbol:
            order['tradingSymbol'] = symbol
        else:
            order['tradingSymbol'] = order.get('stock_code', '')

        order['exchangeSegment'] = exchange

        # Product Type Mapping
        order['productType'] = {
            'cash': 'CNC',
            'margin': 'NRML'
        }.get(order.get('product_type', '').lower(), order.get('product_type'))

    return order_data


def calculate_order_statistics(order_data):
    total_buy_orders = total_sell_orders = 0
    total_completed_orders = total_open_orders = total_rejected_orders = 0

    for order in order_data:
        if order['action'] == 'BUY':
            total_buy_orders += 1
        elif order['action'] == 'SELL':
            total_sell_orders += 1

        status = order.get('status', '').upper()
        if status == 'EXECUTED':
            total_completed_orders += 1
            order['orderStatus'] = 'complete'
        elif status in ['TRIGGER_PENDING', 'OPEN', 'PENDING']:
            total_open_orders += 1
            order['orderStatus'] = 'open'
        elif status == 'REJECTED':
            total_rejected_orders += 1
            order['orderStatus'] = 'rejected'
        elif status == 'CANCELLED':
            order['orderStatus'] = 'cancelled'

    return {
        'total_buy_orders': total_buy_orders,
        'total_sell_orders': total_sell_orders,
        'total_completed_orders': total_completed_orders,
        'total_open_orders': total_open_orders,
        'total_rejected_orders': total_rejected_orders
    }


def transform_order_data(orders):
    if isinstance(orders, dict):
        orders = [orders]

    transformed = []
    for order in orders:
        transformed.append({
            "symbol": order.get("tradingSymbol", ""),
            "exchange": order.get("exchangeSegment", ""),
            "action": order.get("action", ""),
            "quantity": order.get("quantity", 0),
            "price": order.get("price", 0.0),
            "trigger_price": order.get("trigger_price", 0.0),
            "pricetype": order.get("order_type", ""),
            "product": order.get("productType", ""),
            "orderid": order.get("order_id", ""),
            "order_status": order.get("orderStatus", ""),
            "timestamp": order.get("created_at", "")
        })
    return transformed


def map_trade_data(trade_data):
    return map_order_data(trade_data)


def transform_tradebook_data(trades):
    transformed = []
    for trade in trades:
        transformed.append({
            "symbol": trade.get('stock_code', ''),
            "exchange": map_exchange(trade.get('exchange_code', '')),
            "product": trade.get('product_type', ''),
            "action": trade.get('action', ''),
            "quantity": trade.get('quantity', 0),
            "average_price": trade.get('price', 0.0),
            "trade_value": trade.get('quantity', 0) * trade.get('price', 0.0),
            "orderid": trade.get('order_id', ''),
            "timestamp": trade.get('created_at', '')
        })
    return transformed


def map_position_data(position_data):
    return map_order_data(position_data)


def transform_positions_data(positions):
    transformed = []
    for pos in positions:
        transformed.append({
            "symbol": pos.get('stock_code', ''),
            "exchange": map_exchange(pos.get('exchange_code', '')),
            "product": pos.get('product_type', ''),
            "quantity": pos.get('quantity', 0),
            "average_price": pos.get('buy_average', 0.0),
        })
    return transformed


def transform_holdings_data(holdings_data):
    transformed = []
    for holding in holdings_data:
        transformed.append({
            "symbol": holding.get('stock_code', ''),
            "exchange": map_exchange(holding.get('exchange_code', '')),
            "quantity": holding.get('quantity', 0),
            "product": "CNC",
            "pnl": 0.0,  # Breeze doesn't provide this
            "pnlpercent": 0.0
        })
    return transformed


def map_portfolio_data(portfolio_data):
    return portfolio_data or {}


def calculate_portfolio_statistics(holdings_data):
    total_value = sum(h.get('quantity', 0) * h.get('average_price', 0.0) for h in holdings_data)
    return {
        'totalholdingvalue': total_value,
        'totalinvvalue': total_value,
        'totalprofitandloss': 0.0,
        'totalpnlpercentage': 0.0
    }
