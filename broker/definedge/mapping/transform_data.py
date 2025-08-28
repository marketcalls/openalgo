from utils.logging import get_logger

logger = get_logger(__name__)

def transform_data(data, token_id):
    """Transform OpenAlgo order data to DefinedGe Securities format"""
    try:
        # Map OpenAlgo fields to DefinedGe fields
        transformed_data = {
            "tradingsymbol": data['symbol'],
            "exchange": map_exchange(data['exchange']),
            "quantity": data['quantity'],
            "price": data['price'],
            "price_type": map_price_type(data['pricetype']),
            "product_type": map_product_type(data['product']),
            "order_type": data['action'].upper()
        }

        # Add token if available
        if token_id:
            transformed_data["token"] = token_id

        logger.info(f"Transformed order data: {transformed_data}")
        return transformed_data

    except Exception as e:
        logger.error(f"Error transforming data: {e}")
        return data

def transform_modify_order_data(data):
    """Transform modify order data to DefinedGe format"""
    try:
        transformed_data = {
            "order_id": data['orderid'],
            "quantity": data.get('quantity'),
            "price": data.get('price'),
            "price_type": map_price_type(data.get('pricetype', 'LIMIT'))
        }

        # Remove None values
        transformed_data = {k: v for k, v in transformed_data.items() if v is not None}

        return transformed_data

    except Exception as e:
        logger.error(f"Error transforming modify order data: {e}")
        return data

def map_exchange(exchange):
    """Map OpenAlgo exchange to DefinedGe exchange"""
    exchange_mapping = {
        'NSE': 'NSE',
        'BSE': 'BSE',
        'NFO': 'NFO',
        'BFO': 'BFO',
        'CDS': 'CDS',
        'MCX': 'MCX'
    }
    return exchange_mapping.get(exchange, exchange)

def reverse_map_exchange(exchange):
    """Map DefinedGe exchange to OpenAlgo exchange"""
    reverse_mapping = {
        'NSE': 'NSE',
        'BSE': 'BSE',
        'NFO': 'NFO',
        'BFO': 'BFO',
        'CDS': 'CDS',
        'MCX': 'MCX'
    }
    return reverse_mapping.get(exchange, exchange)

def map_product_type(product):
    """Map OpenAlgo product type to DefinedGe product type"""
    product_mapping = {
        'MIS': 'INTRADAY',
        'CNC': 'NORMAL',
        'NRML': 'NORMAL',
        'CO': 'COVER_ORDER',
        'BO': 'BRACKET_ORDER'
    }
    return product_mapping.get(product, 'NORMAL')

def reverse_map_product_type(product):
    """Map DefinedGe product type to OpenAlgo product type"""
    reverse_mapping = {
        'INTRADAY': 'MIS',
        'NORMAL': 'CNC',
        'COVER_ORDER': 'CO',
        'BRACKET_ORDER': 'BO'
    }
    return reverse_mapping.get(product, 'CNC')

def map_price_type(pricetype):
    """Map OpenAlgo price type to DefinedGe price type"""
    price_mapping = {
        'MARKET': 'MARKET',
        'LIMIT': 'LIMIT',
        'SL': 'STOP_LOSS',
        'SL-M': 'STOP_LOSS_MARKET'
    }
    return price_mapping.get(pricetype, 'LIMIT')

def reverse_map_price_type(pricetype):
    """Map DefinedGe price type to OpenAlgo price type"""
    reverse_mapping = {
        'MARKET': 'MARKET',
        'LIMIT': 'LIMIT',
        'STOP_LOSS': 'SL',
        'STOP_LOSS_MARKET': 'SL-M'
    }
    return reverse_mapping.get(pricetype, 'LIMIT')

def map_order_status(status):
    """Map DefinedGe order status to OpenAlgo status"""
    status_mapping = {
        'COMPLETE': 'COMPLETE',
        'OPEN': 'OPEN',
        'PENDING': 'PENDING',
        'CANCELLED': 'CANCELLED',
        'REJECTED': 'REJECTED',
        'PARTIALLY_FILLED': 'OPEN'
    }
    return status_mapping.get(status, status)

def transform_order_data(order):
    """Transform DefinedGe order data to OpenAlgo format"""
    try:
        transformed_order = {
            'symbol': order.get('tradingsymbol', ''),
            'exchange': reverse_map_exchange(order.get('exchange', '')),
            'action': order.get('order_type', '').lower(),
            'quantity': order.get('quantity', '0'),
            'price': order.get('price', '0'),
            'pricetype': reverse_map_price_type(order.get('price_type', 'LIMIT')),
            'product': reverse_map_product_type(order.get('product_type', 'NORMAL')),
            'orderid': order.get('order_id', ''),
            'status': map_order_status(order.get('order_status', '')),
            'timestamp': order.get('order_entry_time', ''),
            'filled_qty': order.get('filled_qty', '0'),
            'pending_qty': order.get('pending_qty', '0'),
            'average_price': order.get('average_traded_price', '0')
        }

        return transformed_order

    except Exception as e:
        logger.error(f"Error transforming order data: {e}")
        return order

def transform_position_data(position):
    """Transform DefinedGe position data to OpenAlgo format"""
    try:
        transformed_position = {
            'symbol': position.get('tradingsymbol', ''),
            'exchange': reverse_map_exchange(position.get('exchange', '')),
            'product': reverse_map_product_type(position.get('product_type', 'NORMAL')),
            'quantity': position.get('net_quantity', '0'),
            'average_price': position.get('net_averageprice', '0'),
            'pnl': position.get('unrealized_pnl', '0'),
            'realized_pnl': position.get('realized_pnl', '0'),
            'last_price': position.get('lastPrice', '0')
        }

        return transformed_position

    except Exception as e:
        logger.error(f"Error transforming position data: {e}")
        return position

def transform_holding_data(holding):
    """Transform DefinedGe holding data to OpenAlgo format"""
    try:
        # DefinedGe holdings have multiple trading symbols for different exchanges
        trading_symbols = holding.get('tradingsymbol', [])

        # Use NSE symbol if available, otherwise use first available
        symbol_info = None
        for ts in trading_symbols:
            if ts.get('exchange') == 'NSE':
                symbol_info = ts
                break

        if not symbol_info and trading_symbols:
            symbol_info = trading_symbols[0]

        if symbol_info:
            transformed_holding = {
                'symbol': symbol_info.get('tradingsymbol', ''),
                'exchange': symbol_info.get('exchange', ''),
                'quantity': holding.get('t1_qty', '0'),
                'average_price': holding.get('avg_buy_price', '0'),
                'isin': symbol_info.get('isin', ''),
                'product': 'CNC'
            }
        else:
            transformed_holding = {
                'symbol': '',
                'exchange': '',
                'quantity': '0',
                'average_price': '0',
                'isin': '',
                'product': 'CNC'
            }

        return transformed_holding

    except Exception as e:
        logger.error(f"Error transforming holding data: {e}")
        return holding
