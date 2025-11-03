import json
from database.token_db import get_symbol, get_oa_symbol 
from utils.logging import get_logger

logger = get_logger(__name__)


def map_order_data(order_data):
    """
    Processes and modifies a list of order dictionaries based on specific conditions.
    """
    if not order_data or 'data' not in order_data or order_data['data'] is None:
        logger.info("No data available.")
        order_data = []
    else:
        order_data = order_data['data']
        logger.info(f"{order_data}")
        
    if order_data:
        for order in order_data:
            symboltoken = order.get('instrument_token')
            exchange = order.get('exchange')
            
            if symboltoken and exchange:
                symbol_from_db = get_symbol(symboltoken, exchange)
                if symbol_from_db:
                    order['tradingsymbol'] = symbol_from_db
                else:
                    logger.info(f"Symbol not found for token {symboltoken} and exchange {exchange}. Keeping original trading symbol.")
    return order_data


def calculate_order_statistics(order_data):
    """
    Calculates statistics from order data.
    """
    total_buy_orders = total_sell_orders = 0
    total_completed_orders = total_open_orders = total_rejected_orders = 0

    if order_data:
        for order in order_data:
            if order.get('transaction_type') == 'BUY':
                total_buy_orders += 1
            elif order.get('transaction_type') == 'SELL':
                total_sell_orders += 1
            
            status = order.get('status', '').lower()
            if 'complete' in status or 'traded' in status:
                total_completed_orders += 1
            elif 'open' in status or 'pending' in status:
                total_open_orders += 1
            elif 'rejected' in status:
                total_rejected_orders += 1

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

    transformed_orders = []
    
    for order in orders:
        if not isinstance(order, dict):
            logger.warning(f"Warning: Expected a dict, but found a {type(order)}. Skipping this item.")
            continue

        transformed_order = {
            "symbol": order.get("tradingsymbol", ""),
            "exchange": order.get("exchange", ""),
            "action": order.get("transaction_type", ""),
            "quantity": order.get("quantity", 0),
            "price": order.get("average_price", 0.0),
            "trigger_price": order.get("trigger_price", 0.0),
            "pricetype": order.get("order_type", ""),
            "product": order.get("product", ""),
            "orderid": order.get("order_id", ""),
            "order_status": order.get("status", ""),
            "timestamp": order.get("order_timestamp", "")
        }
        transformed_orders.append(transformed_order)

    return transformed_orders


def map_trade_data(trade_data):
    """
    Processes and modifies a list of trade dictionaries.
    """
    if not trade_data or 'data' not in trade_data or trade_data['data'] is None:
        logger.info("No trade data available.")
        return []
    
    trade_data = trade_data['data']
    for trade in trade_data:
        symbol = trade.get('SYMBOL')
        exchange = trade.get('EXCHANGE')
        if symbol and exchange:
            oa_symbol = get_oa_symbol(symbol, exchange)
            if oa_symbol:
                trade['tradingsymbol'] = oa_symbol
            else:
                logger.info(f"Unable to find the OA symbol for {symbol} and exchange {exchange}.")
    return trade_data


def transform_tradebook_data(tradebook_data):
    transformed_data = []
    for trade in tradebook_data:
        transformed_trade = {
            "symbol": trade.get('tradingsymbol', ''),
            "exchange": trade.get('EXCHANGE', ''),
            "product": trade.get('PRODUCT', ''),
            "action": trade.get('BUY_SELL', ''),
            "quantity": trade.get('QUANTITY', 0),
            "average_price": trade.get('PRICE', 0.0),
            "trade_value": trade.get('TRADE_VALUE', 0),
            "orderid": trade.get('ORDER_NUMBER', ''),
            "timestamp": trade.get('ORDER_DATE_TIME', '')
        }
        transformed_data.append(transformed_trade)
    return transformed_data


def map_position_data(position_data):
    return map_order_data(position_data)


def transform_positions_data(positions_data):
    transformed_data = []
    if 'data' in positions_data and positions_data['data']:
        for position in positions_data['data']:
            transformed_position = {
                "symbol": position.get('tradingsymbol', ''),
                "exchange": position.get('exchange', ''),
                "product": position.get('product', ''),
                "quantity": position.get('net_quantity', 0),
                "average_price": position.get('average_price', 0.0),
                "ltp": position.get('last_traded_price', 0.0),  
                "pnl": position.get('pnl', 0.0),  
            }
            transformed_data.append(transformed_position)
    return transformed_data

def transform_holdings_data(holdings_data):
    transformed_data = []
    if 'data' in holdings_data and holdings_data['data']:
        for holding in holdings_data['data']:
            transformed_holding = {
                "symbol": holding.get('trading_symbol', ''),
                "exchange": holding.get('exchange', ''),
                "quantity": holding.get('quantity', 0),
                "product": holding.get('product', ''),
                "pnl": holding.get('pnl', 0.0),
                "pnlpercent": holding.get('pnl_percentage', 0.0)
            }
            transformed_data.append(transformed_holding)
    return transformed_data


def map_portfolio_data(portfolio_data):
    """
    Processes portfolio data.
    """
    if portfolio_data.get('data') is None:
        logger.info("No portfolio data available.")
        return {}
    
    data = portfolio_data['data']
    if 'holdings' in data and data['holdings']:
        for holding in data['holdings']:
            symbol = holding.get('trading_symbol')
            exchange = holding.get('exchange')
            if symbol and exchange:
                oa_symbol = get_oa_symbol(symbol, exchange)
                if oa_symbol:
                    holding['tradingsymbol'] = oa_symbol

    return data


def calculate_portfolio_statistics(holdings_data):
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
