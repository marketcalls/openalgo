from utils.logging import get_logger

logger = get_logger(__name__)

def transform_data(data, token_id):
    """Transform OpenAlgo order data to DefinedGe Securities format"""
    from database.token_db import get_br_symbol
    
    try:
        # Get broker symbol format
        symbol = get_br_symbol(data["symbol"], data["exchange"])
        
        # Map OpenAlgo fields to DefinedGe fields based on API docs
        transformed_data = {
            "tradingsymbol": symbol,
            "exchange": map_exchange(data['exchange']),
            "quantity": data['quantity'],
            "price": data.get('price', '0'),
            "price_type": map_price_type(data['pricetype']),
            "product_type": map_product_type(data['product']),
            "order_type": data['action'].upper()
        }

        # Add optional fields based on order type
        if data.get('trigger_price') and data['pricetype'] in ['SL', 'SL-M']:
            transformed_data["trigger_price"] = data['trigger_price']
        
        # Add disclosed quantity if provided
        if data.get('disclosed_quantity'):
            transformed_data["disclosed_quantity"] = data['disclosed_quantity']

        logger.info(f"Transformed order data: {transformed_data}")
        return transformed_data

    except Exception as e:
        logger.error(f"Error transforming data: {e}")
        return data

def transform_modify_order_data(data, token_id):
    """Transform modify order data to DefinedGe format"""
    from database.token_db import get_br_symbol
    
    try:
        logger.info(f"Input modify order data: {data}")
        
        # Check if symbol already has broker format (-EQ suffix)
        if '-' in data["symbol"]:
            # Symbol is already in broker format, use it directly
            symbol = data["symbol"]
            logger.info(f"Symbol already in broker format: {symbol}")
        else:
            # Get broker symbol format
            symbol = get_br_symbol(data["symbol"], data["exchange"])
            logger.info(f"Broker symbol after conversion: {symbol}")
        
        # If symbol is None or empty, raise an error
        if not symbol:
            logger.error(f"Failed to get broker symbol for {data['symbol']} on {data['exchange']}")
            symbol = data["symbol"]  # Use original as fallback
        
        # Map DefinedGe API fields according to documentation
        transformed_data = {
            "order_id": data['orderid'],  # API expects 'order_id', not 'norenordno'
            "tradingsymbol": symbol,  # REQUIRED field
            "exchange": map_exchange(data['exchange']),
            "quantity": str(data.get('quantity')),  # Ensure it's a string
            "price": str(data.get('price', '0')),  # Ensure it's a string
            "price_type": map_definedge_price_type(data.get('pricetype', 'LIMIT')),
            "product_type": map_product_type_for_modify(data.get('product', 'CNC')),
            "order_type": data.get('action', 'BUY').upper()  # BUY/SELL required
        }
        
        # Only add trigger_price if it's actually provided AND the order type requires it
        pricetype = data.get('pricetype', 'LIMIT')
        trigger_price = data.get('trigger_price')
        
        # More robust filtering - only include trigger_price for stop loss orders with valid values
        if (trigger_price and 
            trigger_price != '0' and 
            trigger_price != '' and
            trigger_price != '0.0' and
            str(trigger_price).replace('.', '').replace('0', '') and  # Not just zeros
            pricetype in ['SL', 'SL-M']):
            try:
                # Validate it's actually a number
                float(trigger_price)
                transformed_data["trigger_price"] = trigger_price
                logger.info(f"Added trigger_price: {trigger_price} for pricetype: {pricetype}")
            except (ValueError, TypeError):
                logger.warning(f"Invalid trigger_price value: {trigger_price}, excluding from request")
        else:
            logger.info(f"Excluding trigger_price - pricetype: {pricetype}, trigger_price: {trigger_price}")
        
        # Add optional fields if provided
        if data.get('disclosed_quantity'):
            transformed_data["disclosed_quantity"] = data.get('disclosed_quantity')
            
        # Default values for required fields
        transformed_data["validity"] = "DAY"  # Default validity

        # Remove None values and empty strings, but keep required fields
        required_fields = ['order_id', 'tradingsymbol', 'exchange', 'quantity', 'price', 'price_type', 'product_type', 'order_type']
        transformed_data = {
            k: v for k, v in transformed_data.items() 
            if (k in required_fields) or (v is not None and v != '')
        }
        
        # Final safety check: Remove trigger_price if pricetype is not SL or SL-M
        final_pricetype = data.get('pricetype', 'LIMIT')
        if final_pricetype not in ['SL', 'SL-M'] and 'trigger_price' in transformed_data:
            logger.warning(f"Removing trigger_price for non-SL order type: {final_pricetype}")
            del transformed_data['trigger_price']

        logger.info(f"Final transformed modify order data: {transformed_data}")
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
        'NORMAL': 'CNC',  # For NSE/BSE cash segment
        'COVER_ORDER': 'CO',
        'BRACKET_ORDER': 'BO'
    }
    # Default based on exchange - NORMAL maps to CNC for cash, NRML for F&O
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

def map_definedge_price_type(pricetype):
    """Map OpenAlgo price type to DefinedGe API price type (for modify order)"""
    price_mapping = {
        'MARKET': 'MARKET',
        'LIMIT': 'LIMIT',
        'SL': 'SL-LIMIT',
        'SL-M': 'SL-MARKET'
    }
    return price_mapping.get(pricetype, 'LIMIT')

def map_product_type_for_modify(product):
    """Map OpenAlgo product type to DefinedGe product type for modify order"""
    product_mapping = {
        'MIS': 'INTRADAY',
        'CNC': 'CNC',  # DefinedGe modify API expects CNC for equity
        'NRML': 'NORMAL'
    }
    return product_mapping.get(product, 'CNC')

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
