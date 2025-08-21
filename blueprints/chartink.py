from flask import Blueprint, render_template, request, jsonify, session, flash, redirect, url_for, abort
from database.chartink_db import (
    ChartinkStrategy, ChartinkSymbolMapping, db_session,
    create_strategy, add_symbol_mapping, get_strategy_by_webhook_id,
    get_symbol_mappings, get_all_strategies, delete_strategy,
    update_strategy_times, delete_symbol_mapping, bulk_add_symbol_mappings,
    toggle_strategy, get_strategy, get_user_strategies
)
from database.symbol import enhanced_search_symbols
from database.auth_db import get_api_key_for_tradingview
from utils.session import check_session_validity
from limiter import limiter
import json
from datetime import datetime, time
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from utils.logging import get_logger
import requests
import os
import uuid
import time as time_module
import queue
import threading
from collections import deque
from time import time

logger = get_logger(__name__)

# Rate limiting configuration
WEBHOOK_RATE_LIMIT = os.getenv("WEBHOOK_RATE_LIMIT", "100 per minute")
STRATEGY_RATE_LIMIT = os.getenv("STRATEGY_RATE_LIMIT", "200 per minute")

chartink_bp = Blueprint('chartink_bp', __name__, url_prefix='/chartink')

# Initialize scheduler for time-based controls
scheduler = BackgroundScheduler(timezone=pytz.timezone('Asia/Kolkata'))
scheduler.start()

# Get base URL from environment or default to localhost
BASE_URL = os.getenv('HOST_SERVER', 'http://127.0.0.1:5000')

# Valid exchanges
VALID_EXCHANGES = ['NSE', 'BSE']

# Separate queues for different order types
regular_order_queue = queue.Queue()  # For placeorder (up to 10/sec)
smart_order_queue = queue.Queue()    # For placesmartorder (1/sec)

# Order processor state
order_processor_running = False
order_processor_lock = threading.Lock()

# Rate limiting state for regular orders
last_regular_orders = deque(maxlen=10)  # Track last 10 regular order timestamps

def process_orders():
    """Background task to process orders from both queues with rate limiting"""
    global order_processor_running
    
    while True:
        try:
            # Process smart orders first (1 per second)
            try:
                smart_order = smart_order_queue.get_nowait()
                if smart_order is None:  # Poison pill
                    break
                
                try:
                    response = requests.post(f'{BASE_URL}/api/v1/placesmartorder', json=smart_order['payload'])
                    if response.ok:
                        logger.info(f'Smart order placed for {smart_order["payload"]["symbol"]} in strategy {smart_order["payload"]["strategy"]}')
                    else:
                        logger.error(f'Error placing smart order for {smart_order["payload"]["symbol"]}: {response.text}')
                except Exception as e:
                    logger.error(f'Error placing smart order: {str(e)}')
                
                # Always wait 1 second after smart order
                time_module.sleep(1)
                continue  # Start next iteration
                
            except queue.Empty:
                pass  # No smart orders, continue to regular orders
            
            # Process regular orders (up to 10 per second)
            now = time()
            
            # Clean up old timestamps
            while last_regular_orders and now - last_regular_orders[0] > 1:
                last_regular_orders.popleft()
            
            # Process regular orders if under rate limit
            if len(last_regular_orders) < 10:
                try:
                    regular_order = regular_order_queue.get_nowait()
                    if regular_order is None:  # Poison pill
                        break
                    
                    try:
                        response = requests.post(f'{BASE_URL}/api/v1/placeorder', json=regular_order['payload'])
                        if response.ok:
                            logger.info(f'Regular order placed for {regular_order["payload"]["symbol"]} in strategy {regular_order["payload"]["strategy"]}')
                            last_regular_orders.append(now)
                        else:
                            logger.error(f'Error placing regular order for {regular_order["payload"]["symbol"]}: {response.text}')
                    except Exception as e:
                        logger.error(f'Error placing regular order: {str(e)}')
                        
                except queue.Empty:
                    time_module.sleep(0.1)  # No orders to process
            else:
                # Rate limit hit, wait until next second
                time_module.sleep(0.1)
                
        except Exception as e:
            logger.error(f'Error in order processor: {str(e)}')
            time_module.sleep(0.1)  # Prevent tight loop on error
    
    with order_processor_lock:
        order_processor_running = False

def ensure_order_processor():
    """Ensure order processor is running"""
    global order_processor_running
    
    with order_processor_lock:
        if not order_processor_running:
            order_processor_running = True
            thread = threading.Thread(target=process_orders, daemon=True)
            thread.start()

def queue_order(endpoint, payload):
    """Add order to appropriate processing queue"""
    ensure_order_processor()
    
    if endpoint == 'placesmartorder':
        smart_order_queue.put({'endpoint': endpoint, 'payload': payload})
    else:  # placeorder
        regular_order_queue.put({'endpoint': endpoint, 'payload': payload})

def validate_strategy_times(start_time, end_time, squareoff_time):
    """Validate strategy time settings"""
    try:
        start = datetime.strptime(start_time, '%H:%M').time()
        end = datetime.strptime(end_time, '%H:%M').time()
        squareoff = datetime.strptime(squareoff_time, '%H:%M').time()
        
        if start >= end:
            return False, 'Start time must be before end time'
        if end >= squareoff:
            return False, 'End time must be before square off time'
        
        return True, None
    except ValueError:
        return False, 'Invalid time format'

def validate_strategy_name(name):
    """Validate strategy name format"""
    if not name:
        return False, 'Strategy name is required'
    
    # Add prefix if not present
    if not name.startswith('chartink_'):
        name = f'chartink_{name}'
    
    # Check for valid characters
    if not all(c.isalnum() or c in ['-', '_', ' '] for c in name.replace('chartink_', '')):
        return False, 'Strategy name can only contain letters, numbers, spaces, hyphens and underscores'
    
    return True, name

def schedule_squareoff(strategy_id):
    """Schedule squareoff for intraday strategy"""
    strategy = get_strategy(strategy_id)
    if not strategy or not strategy.is_intraday or not strategy.squareoff_time:
        return
    
    try:
        hours, minutes = map(int, strategy.squareoff_time.split(':'))
        job_id = f'squareoff_{strategy_id}'
        
        # Remove existing job if any
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
        
        # Add new job
        scheduler.add_job(
            squareoff_positions,
            'cron',
            hour=hours,
            minute=minutes,
            args=[strategy_id],
            id=job_id,
            timezone=pytz.timezone('Asia/Kolkata')
        )
        logger.info(f'Scheduled squareoff for strategy {strategy_id} at {hours}:{minutes}')
    except Exception as e:
        logger.error(f'Error scheduling squareoff for strategy {strategy_id}: {str(e)}')

def squareoff_positions(strategy_id):
    """Square off all positions for intraday strategy"""
    try:
        strategy = get_strategy(strategy_id)
        if not strategy or not strategy.is_intraday:
            return
        
        # Get API key for authentication
        api_key = get_api_key_for_tradingview(strategy.user_id)
        if not api_key:
            logger.error(f'No API key found for strategy {strategy_id}')
            return
            
        # Get all symbol mappings
        mappings = get_symbol_mappings(strategy_id)
        
        for mapping in mappings:
            # Use placesmartorder with quantity=0 and position_size=0 for squareoff
            payload = {
                'apikey': api_key,
                'strategy': strategy.name,
                'symbol': mapping.chartink_symbol,
                'exchange': mapping.exchange,
                'action': 'SELL',  # Direction doesn't matter for closing
                'product': mapping.product_type,
                'pricetype': 'MARKET',
                'quantity': '0',
                'position_size': '0',  # This will close the position
                'price': '0',
                'trigger_price': '0',
                'disclosed_quantity': '0'
            }
            
            # Queue the order instead of executing directly
            queue_order('placesmartorder', payload)
            
    except Exception as e:
        logger.error(f'Error in squareoff_positions for strategy {strategy_id}: {str(e)}')

@chartink_bp.route('/')
@check_session_validity
def index():
    """List all strategies"""
    user_id = session.get('user')
    if not user_id:
        flash('Session expired. Please login again.', 'error')
        return redirect(url_for('auth.login'))
        
    strategies = get_user_strategies(user_id)  # Get only user's strategies
    return render_template('chartink/index.html', strategies=strategies)

@chartink_bp.route('/new', methods=['GET', 'POST'])
@check_session_validity
@limiter.limit(STRATEGY_RATE_LIMIT)
def new_strategy():
    """Create new strategy"""
    if request.method == 'POST':
        try:
            # Get user_id from session
            user_id = session.get('user')
            if not user_id:
                logger.error("No user_id found in session")
                flash('Session expired. Please login again.', 'error')
                return redirect(url_for('auth.login'))
            
            # Validate strategy name
            name = request.form.get('name', '').strip()
            is_valid_name, name_result = validate_strategy_name(name)
            if not is_valid_name:
                flash(name_result, 'error')
                return redirect(url_for('chartink_bp.new_strategy'))
            name = name_result  # Use the validated and prefixed name
            
            is_intraday = request.form.get('type') == 'intraday'
            start_time = request.form.get('start_time') if is_intraday else None
            end_time = request.form.get('end_time') if is_intraday else None
            squareoff_time = request.form.get('squareoff_time') if is_intraday else None
            
            if is_intraday:
                if not all([start_time, end_time, squareoff_time]):
                    flash('All time fields are required for intraday strategy', 'error')
                    return redirect(url_for('chartink_bp.new_strategy'))
                
                # Validate time settings
                is_valid, error_msg = validate_strategy_times(start_time, end_time, squareoff_time)
                if not is_valid:
                    flash(error_msg, 'error')
                    return redirect(url_for('chartink_bp.new_strategy'))
            
            # Generate unique webhook ID
            webhook_id = str(uuid.uuid4())
            
            # Create strategy with user ID
            strategy = create_strategy(
                name=name,
                webhook_id=webhook_id,
                user_id=user_id,
                is_intraday=is_intraday,
                start_time=start_time,
                end_time=end_time,
                squareoff_time=squareoff_time
            )
            
            if strategy:
                # Schedule squareoff if intraday
                if is_intraday and squareoff_time:
                    schedule_squareoff(strategy.id)
                
                flash('Strategy created successfully', 'success')
                return redirect(url_for('chartink_bp.view_strategy', strategy_id=strategy.id))
            else:
                flash('Error creating strategy', 'error')
        except Exception as e:
            logger.error(f'Error creating strategy: {str(e)}')
            flash('Error creating strategy', 'error')
        
        return redirect(url_for('chartink_bp.new_strategy'))
    
    return render_template('chartink/new_strategy.html')

@chartink_bp.route('/<int:strategy_id>')
@check_session_validity
def view_strategy(strategy_id):
    """View strategy details"""
    user_id = session.get('user')
    if not user_id:
        flash('Session expired. Please login again.', 'error')
        return redirect(url_for('auth.login'))
        
    strategy = get_strategy(strategy_id)
    if not strategy:
        abort(404)
    
    # Check if strategy belongs to user
    if strategy.user_id != user_id:
        abort(403)
    
    symbol_mappings = get_symbol_mappings(strategy_id)
    return render_template('chartink/view_strategy.html', strategy=strategy, symbol_mappings=symbol_mappings)

@chartink_bp.route('/<int:strategy_id>/delete', methods=['POST'])
@check_session_validity
@limiter.limit(STRATEGY_RATE_LIMIT)
def delete_strategy_route(strategy_id):
    """Delete a strategy"""
    user_id = session.get('user')
    if not user_id:
        return jsonify({'status': 'error', 'error': 'Session expired'}), 401
        
    strategy = get_strategy(strategy_id)
    if not strategy:
        return jsonify({'status': 'error', 'error': 'Strategy not found'}), 404
    
    # Check if strategy belongs to user
    if strategy.user_id != user_id:
        return jsonify({'status': 'error', 'error': 'Unauthorized'}), 403
    
    try:
        # Remove squareoff job if exists
        job_id = f'squareoff_{strategy_id}'
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
        
        # Delete strategy and its mappings
        if delete_strategy(strategy_id):
            return jsonify({'status': 'success'})
        else:
            return jsonify({'status': 'error', 'error': 'Failed to delete strategy'}), 500
    except Exception as e:
        logger.error(f'Error deleting strategy {strategy_id}: {str(e)}')
        return jsonify({'status': 'error', 'error': str(e)}), 500

@chartink_bp.route('/<int:strategy_id>/configure', methods=['GET', 'POST'])
@check_session_validity
@limiter.limit(STRATEGY_RATE_LIMIT)
def configure_symbols(strategy_id):
    """Configure symbols for strategy"""
    user_id = session.get('user')
    if not user_id:
        flash('Session expired. Please login again.', 'error')
        return redirect(url_for('auth.login'))
        
    strategy = get_strategy(strategy_id)
    if not strategy:
        abort(404)
    
    # Check if strategy belongs to user
    if strategy.user_id != user_id:
        abort(403)
    
    if request.method == 'POST':
        try:
            # Get data from either JSON or form
            if request.is_json:
                data = request.get_json()
            else:
                data = request.form.to_dict()
            
            logger.info(f"Received data: {data}")
            
            # Handle bulk symbols
            if 'symbols' in data:
                symbols_text = data.get('symbols')
                mappings = []
                
                for line in symbols_text.strip().split('\n'):
                    if not line.strip():
                        continue
                    
                    parts = line.strip().split(',')
                    if len(parts) != 4:
                        raise ValueError(f'Invalid format in line: {line}')
                    
                    symbol, exchange, quantity, product = parts
                    if exchange not in VALID_EXCHANGES:
                        raise ValueError(f'Invalid exchange: {exchange}')
                    
                    mappings.append({
                        'chartink_symbol': symbol.strip(),
                        'exchange': exchange.strip(),
                        'quantity': int(quantity),
                        'product_type': product.strip()
                    })
                
                if mappings:
                    bulk_add_symbol_mappings(strategy_id, mappings)
                    return jsonify({'status': 'success'})
            
            # Handle single symbol
            else:
                symbol = data.get('symbol')
                exchange = data.get('exchange')
                quantity = data.get('quantity')
                product_type = data.get('product_type')
                
                logger.info(f"Processing single symbol: symbol={symbol}, exchange={exchange}, quantity={quantity}, product_type={product_type}")
                
                if not all([symbol, exchange, quantity, product_type]):
                    missing = []
                    if not symbol: missing.append('symbol')
                    if not exchange: missing.append('exchange')
                    if not quantity: missing.append('quantity')
                    if not product_type: missing.append('product_type')
                    raise ValueError(f'Missing required fields: {", ".join(missing)}')
                
                if exchange not in VALID_EXCHANGES:
                    raise ValueError(f'Invalid exchange: {exchange}')
                
                try:
                    quantity = int(quantity)
                except ValueError:
                    raise ValueError('Quantity must be a valid number')
                
                if quantity <= 0:
                    raise ValueError('Quantity must be greater than 0')
                
                mapping = add_symbol_mapping(
                    strategy_id=strategy_id,
                    chartink_symbol=symbol,
                    exchange=exchange,
                    quantity=quantity,
                    product_type=product_type
                )
                
                if mapping:
                    return jsonify({'status': 'success'})
                else:
                    raise ValueError('Failed to add symbol mapping')
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f'Error configuring symbols: {error_msg}')
            return jsonify({'status': 'error', 'error': error_msg}), 400
    
    symbol_mappings = get_symbol_mappings(strategy_id)
    return render_template('chartink/configure_symbols.html', 
                         strategy=strategy, 
                         symbol_mappings=symbol_mappings,
                         exchanges=VALID_EXCHANGES)

@chartink_bp.route('/<int:strategy_id>/symbol/<int:mapping_id>/delete', methods=['POST'])
@check_session_validity
@limiter.limit(STRATEGY_RATE_LIMIT)
def delete_symbol(strategy_id, mapping_id):
    """Delete symbol mapping"""
    user_id = session.get('user')
    if not user_id:
        return jsonify({'status': 'error', 'error': 'Session expired'}), 401
        
    strategy = get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        return jsonify({'status': 'error', 'error': 'Strategy not found'}), 404
    
    try:
        delete_symbol_mapping(mapping_id)
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f'Error deleting symbol mapping: {str(e)}')
        return jsonify({'status': 'error', 'error': str(e)}), 400

@chartink_bp.route('/<int:strategy_id>/toggle', methods=['POST'])
@check_session_validity
def toggle_strategy_route(strategy_id):
    """Toggle strategy active status"""
    user_id = session.get('user')
    if not user_id:
        flash('Session expired. Please login again.', 'error')
        return redirect(url_for('auth.login'))
        
    strategy = get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        abort(404)
    
    try:
        strategy = toggle_strategy(strategy_id)
        if strategy:
            status = 'activated' if strategy.is_active else 'deactivated'
            flash(f'Strategy {status} successfully', 'success')
        else:
            flash('Error toggling strategy', 'error')
    except Exception as e:
        logger.error(f'Error toggling strategy: {str(e)}')
        flash('Error toggling strategy', 'error')
    
    return redirect(url_for('chartink_bp.view_strategy', strategy_id=strategy_id))

@chartink_bp.route('/search')
@check_session_validity
def search_symbols():
    """Search symbols endpoint"""
    query = request.args.get('q', '').strip()
    exchange = request.args.get('exchange')
    
    if not query:
        return jsonify({'results': []})
    
    results = enhanced_search_symbols(query, exchange)
    return jsonify({
        'results': [{
            'symbol': result.symbol,
            'name': result.name,
            'exchange': result.exchange
        } for result in results]
    })

@chartink_bp.route('/webhook/<webhook_id>', methods=['POST'])
@limiter.limit(WEBHOOK_RATE_LIMIT)
def webhook(webhook_id):
    """Handle webhook from Chartink"""
    try:
        # Get strategy by webhook ID
        strategy = get_strategy_by_webhook_id(webhook_id)
        if not strategy:
            logger.error(f'Strategy not found for webhook ID: {webhook_id}')
            return jsonify({'status': 'error', 'error': 'Invalid webhook ID'}), 404
        
        if not strategy.is_active:
            logger.info(f'Strategy {strategy.id} is inactive, ignoring webhook')
            return jsonify({'status': 'success', 'message': 'Strategy is inactive'})
        
        # Parse webhook data
        data = request.get_json()
        if not data:
            logger.error(f'No data received in webhook for strategy {strategy.id}')
            return jsonify({'status': 'error', 'error': 'No data received'}), 400
        
        logger.info(f'Received webhook data: {data}')
        
        # Determine action from scan name first to apply correct time checks
        scan_name = data.get('scan_name', '').upper()
        if 'BUY' in scan_name:
            action = 'BUY'
            use_smart_order = False
            is_entry_order = True
        elif 'SELL' in scan_name:
            action = 'SELL'
            use_smart_order = True
            is_entry_order = False
        elif 'SHORT' in scan_name:
            action = 'SELL'  # For short entry
            use_smart_order = False
            is_entry_order = True
        elif 'COVER' in scan_name:
            action = 'BUY'   # For short cover
            use_smart_order = True
            is_entry_order = False
        else:
            error_msg = 'No valid action keyword (BUY/SELL/SHORT/COVER) found in scan name'
            logger.error(error_msg)
            return jsonify({'status': 'error', 'error': error_msg}), 400
            
        # Time validations for intraday strategies
        if strategy.is_intraday:
            current_time = datetime.now(pytz.timezone('Asia/Kolkata')).time()
            
            # Convert strategy times to time objects
            start_time = datetime.strptime(strategy.start_time, '%H:%M').time()
            end_time = datetime.strptime(strategy.end_time, '%H:%M').time()
            squareoff_time = datetime.strptime(strategy.squareoff_time, '%H:%M').time()
            
            # Check if before start time for all orders
            if current_time < start_time:
                logger.info(f'Strategy {strategy.id} received webhook before start time, ignoring')
                return jsonify({
                    'status': 'error',
                    'error': 'Cannot place orders before start time'
                }), 400
            
            # Check if after squareoff time for all orders
            if current_time >= squareoff_time:
                logger.info(f'Strategy {strategy.id} received webhook after squareoff time, ignoring')
                return jsonify({
                    'status': 'error',
                    'error': 'Cannot place orders after squareoff time'
                }), 400
            
            # For entry orders (BUY/SHORT), check end time
            if is_entry_order and current_time >= end_time:
                logger.info(f'Strategy {strategy.id} received entry order after end time, ignoring')
                return jsonify({
                    'status': 'error',
                    'error': 'Cannot place entry orders after end time'
                }), 400
        
        # Get symbols and trigger prices
        symbols = data.get('stocks', '').split(',')
        trigger_prices = data.get('trigger_prices', '').split(',')
        
        if not symbols:
            logger.error('No symbols received in webhook')
            return jsonify({'status': 'error', 'error': 'No symbols received'}), 400
        
        # Get symbol mappings
        mappings = get_symbol_mappings(strategy.id)
        if not mappings:
            logger.error(f'No symbol mappings found for strategy {strategy.id}')
            return jsonify({'status': 'error', 'error': 'No symbol mappings configured'}), 400
        
        mapping_dict = {m.chartink_symbol: m for m in mappings}
        
        # Get API key from database
        api_key = get_api_key_for_tradingview(strategy.user_id)
        if not api_key:
            logger.error(f'No API key found for user {strategy.user_id}')
            return jsonify({'status': 'error', 'error': 'No API key found'}), 401
        
        # Process each symbol
        processed_symbols = []
        for symbol in symbols:
            symbol = symbol.strip()
            if not symbol:
                continue
                
            mapping = mapping_dict.get(symbol)
            if not mapping:
                logger.warning(f'No mapping found for symbol {symbol} in strategy {strategy.id}')
                continue
            
            # Prepare base payload
            payload = {
                'apikey': api_key,
                'strategy': strategy.name,
                'symbol': mapping.chartink_symbol,
                'exchange': mapping.exchange,
                'action': action,
                'product': mapping.product_type,
                'pricetype': 'MARKET'
            }
            
            # Add quantity based on order type
            if use_smart_order:
                # For SELL and COVER, use smart order with quantity=0 and position_size=0
                payload.update({
                    'quantity': '0',
                    'position_size': '0',
                    'price': '0',
                    'trigger_price': '0',
                    'disclosed_quantity': '0'
                })
                endpoint = 'placesmartorder'
            else:
                # For BUY and SHORT, use regular order with configured quantity
                payload.update({
                    'quantity': str(mapping.quantity)
                })
                endpoint = 'placeorder'
            
            logger.info(f'Queueing {endpoint} with payload: {payload}')
            
            # Queue the order instead of executing directly
            queue_order(endpoint, payload)
            processed_symbols.append(symbol)
        
        if processed_symbols:
            return jsonify({
                'status': 'success',
                'message': f'Orders queued for symbols: {", ".join(processed_symbols)}'
            })
        else:
            return jsonify({
                'status': 'warning',
                'message': 'No orders were queued'
            })
        
    except Exception as e:
        logger.error(f'Error processing webhook: {str(e)}')
        return jsonify({'status': 'error', 'error': str(e)}), 500
