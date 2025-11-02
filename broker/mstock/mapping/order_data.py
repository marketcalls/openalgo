from utils.logging import get_logger

logger = get_logger(__name__)

def transform_order_data(orders):
    transformed_orders = []
    if not orders or not orders.get('data'):
        return transformed_orders

    for order in orders['data']:
        transformed_order = {
            "symbol": order.get("tradingsymbol"),
            "exchange": order.get("exchange"),
            "action": order.get("transactiontype"),
            "quantity": order.get("quantity"),
            "price": order.get("price"),
            "trigger_price": order.get("triggerprice"),
            "pricetype": order.get("ordertype"),
            "product": order.get("producttype"),
            "orderid": order.get("orderid"),
            "order_status": order.get("status"),
            "timestamp": order.get("updatetime")
        }
        transformed_orders.append(transformed_order)
    return transformed_orders

def transform_tradebook_data(tradebook_data):
    transformed_data = []
    if not tradebook_data or not tradebook_data.get('data'):
        return transformed_data

    for trade in tradebook_data['data']:
        transformed_trade = {
            "symbol": trade.get('tradingsymbol'),
            "exchange": trade.get('exchange'),
            "product": trade.get('producttype'),
            "action": trade.get('transactiontype'),
            "quantity": trade.get('quantity'),
            "average_price": trade.get('fillprice'),
            "orderid": trade.get('orderid'),
            "timestamp": trade.get('filltime')
        }
        transformed_data.append(transformed_trade)
    return transformed_data

def transform_positions_data(positions_data):
    transformed_data = []
    if not positions_data or not positions_data.get('data'):
        return transformed_data

    for position in positions_data['data']:
        transformed_position = {
            "symbol": position.get('tradingsymbol'),
            "exchange": position.get('exchange'),
            "product": position.get('producttype'),
            "quantity": position.get('netqty'),
            "average_price": position.get('avgnetprice'),
            "ltp": position.get('ltp'),
            "pnl": position.get('pnl'),
        }
        transformed_data.append(transformed_position)
    return transformed_data

def transform_holdings_data(holdings_data):
    transformed_data = []
    if not holdings_data or not holdings_data.get('data'):
        return transformed_data

    for holding in holdings_data['data']:
        transformed_holding = {
            "symbol": holding.get('tradingsymbol'),
            "exchange": holding.get('exchange'),
            "quantity": holding.get('quantity'),
            "product": holding.get('product'),
            "ltp": holding.get('ltp'),
            "pnl": holding.get('pnl'),
        }
        transformed_data.append(transformed_holding)
    return transformed_data
