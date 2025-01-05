from flask import Blueprint, render_template, request, jsonify, session, flash, redirect, url_for, abort
from database.strategy_db import (
    Strategy, StrategySymbolMapping, db_session,
    create_strategy, add_symbol_mapping, get_strategy_by_webhook_id,
    get_symbol_mappings, get_all_strategies, delete_strategy,
    update_strategy_times, delete_symbol_mapping, bulk_add_symbol_mappings,
    toggle_strategy, get_strategy, get_user_strategies
)
from database.symbol import enhanced_search_symbols
from database.auth_db import get_api_key_for_tradingview
from utils.session import check_session_validity
import json
from datetime import datetime, time
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
import logging
import requests
import os
import uuid
import time as time_module
import queue
import threading
from collections import deque
from time import time

logger = logging.getLogger(__name__)

strategy_bp = Blueprint('strategy_bp', __name__, url_prefix='/strategy')

# Initialize scheduler for time-based controls
scheduler = BackgroundScheduler(timezone=pytz.timezone('Asia/Kolkata'))
scheduler.start()

# Get base URL from environment or default to localhost
BASE_URL = os.getenv('HOST_SERVER', 'http://127.0.0.1:5000')

# Valid trading modes
VALID_MODES = ['LONG', 'SHORT', 'BOTH']

# Valid platforms
VALID_PLATFORMS = ['AMIBroker', 'Python', 'Tradingview', 'Metatrader']

# Valid actions for each mode
MODE_ACTIONS = {
    'LONG': ['BUY', 'SELL'],
    'SHORT': ['SHORT', 'COVER'],
    'BOTH': ['BUY', 'SELL', 'SHORT', 'COVER']
}

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
                continue
                
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
                    pass  # No regular orders
                    
            time_module.sleep(0.1)  # Small sleep to prevent CPU spinning
            
        except Exception as e:
            logger.error(f'Error in order processor: {str(e)}')
            time_module.sleep(1)  # Sleep on error to prevent rapid retries

def ensure_order_processor():
    """Ensure the order processor is running"""
    global order_processor_running
    with order_processor_lock:
        if not order_processor_running:
            threading.Thread(target=process_orders, daemon=True).start()
            order_processor_running = True

def queue_order(endpoint, payload):
    """Add order to appropriate processing queue"""
    if endpoint == 'placesmartorder':
        smart_order_queue.put({'payload': payload})
    else:
        regular_order_queue.put({'payload': payload})

def validate_strategy_times(start_time, end_time, squareoff_time):
    """Validate strategy time settings"""
    try:
        if start_time:
            datetime.strptime(start_time, '%H:%M')
        if end_time:
            datetime.strptime(end_time, '%H:%M')
        if squareoff_time:
            datetime.strptime(squareoff_time, '%H:%M')
        return True
    except ValueError:
        return False

def validate_strategy_name(name):
    """Validate strategy name format"""
    if not name:
        return False
    
    # Check length
    if len(name) < 3 or len(name) > 50:
        return False
    
    # Check for valid characters (alphanumeric, underscore, hyphen)
    import re
    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        return False
    
    return True

def schedule_squareoff(strategy_id):
    """Schedule squareoff for intraday strategy"""
    strategy = get_strategy(strategy_id)
    if not strategy or not strategy.is_intraday or not strategy.squareoff_time:
        return
    
    try:
        # Parse squareoff time
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
        if not strategy or not strategy.is_active:
            return
        
        symbol_mappings = get_symbol_mappings(strategy_id)
        
        for mapping in symbol_mappings:
            # Determine exit action based on strategy mode
            if strategy.mode == 'LONG':
                exit_action = 'SELL'
            elif strategy.mode == 'SHORT':
                exit_action = 'COVER'
            else:  # BOTH mode
                # Need to check current position to determine exit action
                # This would require position tracking which is not implemented here
                continue
            
            payload = {
                'strategy': strategy.name,
                'symbol': mapping.symbol,
                'exchange': mapping.exchange,
                'action': exit_action,
                'quantity': mapping.quantity,
                'product_type': mapping.product_type
            }
            
            queue_order('placeorder', payload)
            
        logger.info(f'Executed squareoff for strategy {strategy_id}')
        
    except Exception as e:
        logger.error(f'Error in squareoff for strategy {strategy_id}: {str(e)}')

@strategy_bp.route('/')
@check_session_validity
def index():
    """List all strategies"""
    user_id = session.get('user')
    strategies = get_user_strategies(user_id)
    return render_template('strategy/index.html', strategies=strategies)

@strategy_bp.route('/new', methods=['GET', 'POST'])
@check_session_validity
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

            name = request.form.get('name')
            platform = request.form.get('platform')
            mode = request.form.get('mode')
            is_intraday = request.form.get('is_intraday') == 'true'
            start_time = request.form.get('start_time')
            end_time = request.form.get('end_time')
            squareoff_time = request.form.get('squareoff_time')
            
            if not validate_strategy_name(name):
                flash('Invalid strategy name. Use only alphanumeric characters, underscore, and hyphen.', 'error')
                return redirect(url_for('strategy_bp.new_strategy'))
            
            if platform not in VALID_PLATFORMS:
                flash('Invalid platform selected.', 'error')
                return redirect(url_for('strategy_bp.new_strategy'))
            
            if mode not in VALID_MODES:
                flash('Invalid mode selected.', 'error')
                return redirect(url_for('strategy_bp.new_strategy'))
            
            if is_intraday and not validate_strategy_times(start_time, end_time, squareoff_time):
                flash('Invalid time format. Use HH:MM format.', 'error')
                return redirect(url_for('strategy_bp.new_strategy'))
            
            webhook_id = str(uuid.uuid4())
            
            strategy = create_strategy(
                name=name,
                webhook_id=webhook_id,
                user_id=user_id,
                platform=platform,
                mode=mode,
                is_intraday=is_intraday,
                start_time=start_time if is_intraday else None,
                end_time=end_time if is_intraday else None,
                squareoff_time=squareoff_time if is_intraday else None
            )
            
            if strategy:
                if is_intraday and squareoff_time:
                    schedule_squareoff(strategy.id)
                flash('Strategy created successfully!', 'success')
                return redirect(url_for('strategy_bp.configure_symbols', strategy_id=strategy.id))
            else:
                flash('Error creating strategy.', 'error')
        except Exception as e:
            logger.error(f'Error creating strategy: {str(e)}')
            flash('Error creating strategy.', 'error')
        
        return redirect(url_for('strategy_bp.new_strategy'))
    
    return render_template('strategy/new_strategy.html', platforms=VALID_PLATFORMS, modes=VALID_MODES)

@strategy_bp.route('/<int:strategy_id>')
@check_session_validity
def view_strategy(strategy_id):
    """View strategy details"""
    strategy = get_strategy(strategy_id)
    if not strategy or strategy.user_id != session.get('user'):
        abort(404)
    
    symbol_mappings = get_symbol_mappings(strategy_id)
    webhook_url = f'{BASE_URL}/strategy/webhook/{strategy.webhook_id}'
    
    return render_template('strategy/view_strategy.html',
                         strategy=strategy,
                         symbol_mappings=symbol_mappings,
                         webhook_url=webhook_url)

@strategy_bp.route('/<int:strategy_id>/delete', methods=['POST'])
@check_session_validity
def delete_strategy_route(strategy_id):
    """Delete a strategy"""
    strategy = get_strategy(strategy_id)
    if not strategy or strategy.user_id != session.get('user'):
        abort(404)
    
    # Remove squareoff job if exists
    job_id = f'squareoff_{strategy_id}'
    try:
        scheduler.remove_job(job_id)
    except:
        pass
    
    if delete_strategy(strategy_id):
        flash('Strategy deleted successfully!', 'success')
    else:
        flash('Error deleting strategy.', 'error')
    
    return redirect(url_for('strategy_bp.index'))

@strategy_bp.route('/<int:strategy_id>/configure', methods=['GET', 'POST'])
@check_session_validity
def configure_symbols(strategy_id):
    """Configure symbols for strategy"""
    strategy = get_strategy(strategy_id)
    if not strategy or strategy.user_id != session.get('user'):
        abort(404)
    
    if request.method == 'POST':
        try:
            data = request.get_json()
            mappings = []
            
            for item in data['symbols']:
                mapping_data = {
                    'symbol': item['symbol'],
                    'exchange': item['exchange'],
                    'segment': item['segment'],
                    'quantity': int(item['quantity']),
                    'product_type': item['product_type']
                }
                mappings.append(mapping_data)
            
            if bulk_add_symbol_mappings(strategy_id, mappings):
                return jsonify({'status': 'success'})
            else:
                return jsonify({'status': 'error', 'message': 'Error adding symbols'}), 400
                
        except Exception as e:
            logger.error(f'Error in configure_symbols: {str(e)}')
            return jsonify({'status': 'error', 'message': str(e)}), 400
    
    symbol_mappings = get_symbol_mappings(strategy_id)
    return render_template('strategy/configure_symbols.html',
                         strategy=strategy,
                         symbol_mappings=symbol_mappings)

@strategy_bp.route('/<int:strategy_id>/symbol/<int:mapping_id>/delete', methods=['POST'])
@check_session_validity
def delete_symbol(strategy_id, mapping_id):
    """Delete symbol mapping"""
    strategy = get_strategy(strategy_id)
    if not strategy or strategy.user_id != session.get('user'):
        abort(404)
    
    if delete_symbol_mapping(mapping_id):
        return jsonify({'status': 'success'})
    else:
        return jsonify({'status': 'error', 'message': 'Error deleting symbol mapping'}), 400

@strategy_bp.route('/<int:strategy_id>/toggle', methods=['POST'])
@check_session_validity
def toggle_strategy_route(strategy_id):
    """Toggle strategy active status"""
    strategy = get_strategy(strategy_id)
    if not strategy or strategy.user_id != session.get('user'):
        abort(404)
    
    if toggle_strategy(strategy_id):
        status = 'activated' if strategy.is_active else 'deactivated'
        flash(f'Strategy {status} successfully!', 'success')
    else:
        flash('Error toggling strategy status.', 'error')
    
    return redirect(url_for('strategy_bp.view_strategy', strategy_id=strategy_id))

@strategy_bp.route('/search_symbols')
@check_session_validity
def search_symbols():
    """Search symbols endpoint"""
    query = request.args.get('q', '')
    if len(query) < 2:
        return jsonify([])
    
    symbols = enhanced_search_symbols(query)
    return jsonify(symbols)

@strategy_bp.route('/webhook/<webhook_id>', methods=['POST'])
def webhook(webhook_id):
    """Handle webhook from trading platforms"""
    try:
        strategy = get_strategy_by_webhook_id(webhook_id)
        if not strategy:
            return jsonify({'status': 'error', 'message': 'Invalid webhook ID'}), 404
        
        if not strategy.is_active:
            return jsonify({'status': 'error', 'message': 'Strategy is not active'}), 400
        
        # Check trading hours for intraday strategies
        if strategy.is_intraday and strategy.start_time and strategy.end_time:
            current_time = datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%H:%M')
            if current_time < strategy.start_time or current_time > strategy.end_time:
                return jsonify({'status': 'error', 'message': 'Outside trading hours'}), 400
        
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['Strategy', 'symbol', 'exchange', 'action', 'quantity']
        for field in required_fields:
            if field not in data:
                return jsonify({'status': 'error', 'message': f'Missing required field: {field}'}), 400
        
        # Validate strategy name
        if data['Strategy'] != strategy.name:
            return jsonify({'status': 'error', 'message': 'Invalid strategy name'}), 400
        
        # Validate action based on strategy mode
        action = data['action'].upper()
        if action not in MODE_ACTIONS[strategy.mode]:
            return jsonify({'status': 'error', 'message': f'Invalid action for {strategy.mode} mode'}), 400
        
        # Find matching symbol mapping
        symbol_mappings = get_symbol_mappings(strategy.id)
        matching_mapping = None
        
        for mapping in symbol_mappings:
            if (mapping.symbol == data['symbol'] and 
                mapping.exchange == data['exchange']):
                matching_mapping = mapping
                break
        
        if not matching_mapping:
            return jsonify({'status': 'error', 'message': 'Symbol not configured for strategy'}), 400
        
        # Prepare order payload
        payload = {
            'strategy': strategy.name,
            'symbol': matching_mapping.symbol,
            'exchange': matching_mapping.exchange,
            'segment': matching_mapping.segment,
            'action': action,
            'quantity': matching_mapping.quantity,
            'product_type': matching_mapping.product_type
        }
        
        # Queue the order
        queue_order('placeorder', payload)
        
        return jsonify({'status': 'success', 'message': 'Order queued successfully'})
        
    except Exception as e:
        logger.error(f'Error processing webhook: {str(e)}')
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Ensure order processor is running
ensure_order_processor()
