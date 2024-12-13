from flask import Blueprint, render_template, request, jsonify, session, flash, redirect, url_for, abort
from database.chartink_db import (
    ChartinkStrategy, ChartinkSymbolMapping, db_session,
    create_strategy, add_symbol_mapping, get_strategy_by_webhook_id,
    get_symbol_mappings, get_all_strategies, delete_strategy,
    update_strategy_times, delete_symbol_mapping, bulk_add_symbol_mappings
)
from database.symbol import enhanced_search_symbols
from utils.session import check_session_validity
from database.auth_db import get_api_key_for_tradingview, get_auth_token_broker
from database.user_db import User
import json
from datetime import datetime
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
import logging
import requests
import os

logger = logging.getLogger(__name__)

chartink_bp = Blueprint('chartink_bp', __name__, url_prefix='/chartink')

# Initialize scheduler for time-based controls
scheduler = BackgroundScheduler(timezone=pytz.timezone('Asia/Kolkata'))
scheduler.start()

# Get base URL from environment or default to localhost
BASE_URL = os.getenv('HOST_SERVER', 'http://127.0.0.1:5000')

# Valid exchanges
VALID_EXCHANGES = ['NSE', 'BSE']

def schedule_squareoff(strategy_id):
    """Schedule squareoff for a strategy"""
    strategy = ChartinkStrategy.query.get(strategy_id)
    if not strategy:
        return
    
    # Parse squareoff time
    try:
        hours, minutes, seconds = map(int, strategy.squareoff_time.split(':'))
        # Remove existing job if any
        job_id = f'squareoff_{strategy_id}'
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
        # Add new job
        scheduler.add_job(
            squareoff_positions,
            'cron',
            hour=hours,
            minute=minutes,
            second=seconds,
            args=[strategy_id],
            id=job_id
        )
        logger.info(f"Scheduled squareoff for strategy {strategy_id} at {strategy.squareoff_time}")
    except Exception as e:
        logger.error(f"Error scheduling squareoff for strategy {strategy_id}: {str(e)}")

def squareoff_positions(strategy_id):
    """Square off all positions for a strategy"""
    try:
        strategy = ChartinkStrategy.query.get(strategy_id)
        if not strategy:
            return
            
        # Get API key for orders
        api_key = get_api_key_for_tradingview(strategy.user_id)
        if not api_key:
            logger.error("API key not found")
            return
            
        # Get all symbol mappings
        mappings = get_symbol_mappings(strategy_id)
        
        # Place smart orders with quantity 0 to close positions
        for mapping in mappings:
            try:
                # Make API request to place smart order
                response = requests.post(
                    f"{BASE_URL}/api/v1/placesmartorder",
                    json={
                        "apikey": api_key,
                        "strategy": strategy.name,
                        "symbol": mapping.chartink_symbol,
                        "exchange": mapping.exchange,
                        "action": "SELL",  # Direction doesn't matter when closing positions
                        "product": mapping.product_type,
                        "quantity": 0,
                        "position_size": 0,
                        "pricetype": "MARKET"
                    }
                )
                if not response.ok:
                    logger.error(f"Error squaring off position for {mapping.chartink_symbol}: {response.text}")
            except Exception as e:
                logger.error(f"Error squaring off position for {mapping.chartink_symbol}: {str(e)}")
                
    except Exception as e:
        logger.error(f"Error in squareoff_positions: {str(e)}")

@chartink_bp.route('/')
@check_session_validity
def index():
    """Show list of strategies"""
    strategies = get_all_strategies()
    return render_template('chartink/index.html', strategies=strategies)

@chartink_bp.route('/new', methods=['GET', 'POST'])
@check_session_validity
def new_strategy():
    """Create new strategy"""
    if request.method == 'POST':
        try:
            name = request.form['name']
            is_intraday = request.form.get('is_intraday', 'true') == 'true'
            
            # Get trading times
            start_time = request.form.get('start_time', '09:30:00')
            end_time = request.form.get('end_time', '15:00:00')
            squareoff_time = request.form.get('squareoff_time', '15:15:00')
            
            # Validate time format
            for time_str in [start_time, end_time, squareoff_time]:
                try:
                    datetime.strptime(time_str, '%H:%M:%S')
                except ValueError:
                    flash('Invalid time format. Use HH:MM:SS', 'error')
                    return redirect(url_for('chartink_bp.new_strategy'))
            
            strategy = create_strategy(
                name=name,
                base_url=BASE_URL,
                user_id=session['user'],  # Store user ID with strategy
                is_intraday=is_intraday,
                start_time=start_time,
                end_time=end_time,
                squareoff_time=squareoff_time
            )
            
            # Schedule squareoff if intraday
            if is_intraday:
                schedule_squareoff(strategy.id)
                
            flash('Strategy created successfully', 'success')
            return redirect(url_for('chartink_bp.configure_symbols', strategy_id=strategy.id))
            
        except Exception as e:
            logger.error(f"Error creating strategy: {str(e)}")
            flash(f'Error creating strategy: {str(e)}', 'error')
            return redirect(url_for('chartink_bp.new_strategy'))
            
    return render_template('chartink/new_strategy.html')

@chartink_bp.route('/<int:strategy_id>/configure', methods=['GET', 'POST'])
@check_session_validity
def configure_symbols(strategy_id):
    """Configure symbol mappings for a strategy"""
    strategy = ChartinkStrategy.query.get(strategy_id)
    if not strategy:
        abort(404)
    
    # Check ownership
    if strategy.user_id != session['user']:
        abort(403)
    
    if request.method == 'POST':
        try:
            # Check if bulk add
            if 'symbols' in request.form:
                symbols_data = request.form['symbols'].strip()
                if symbols_data:
                    symbols = []
                    for line in symbols_data.split('\n'):
                        parts = line.strip().split(',')
                        if len(parts) >= 4:
                            symbol, exchange, quantity, product_type = [p.strip() for p in parts[:4]]
                            if exchange in VALID_EXCHANGES:
                                symbols.append({
                                    'symbol': symbol,
                                    'exchange': exchange,
                                    'quantity': int(quantity),
                                    'product_type': product_type
                                })
                    
                    if symbols:
                        bulk_add_symbol_mappings(strategy_id, symbols)
                        flash(f'Added {len(symbols)} symbols successfully', 'success')
                    else:
                        flash('No valid symbols found', 'error')
            else:
                # Single symbol add
                chartink_symbol = request.form['symbol']
                exchange = request.form['exchange']
                quantity = int(request.form['quantity'])
                product_type = request.form['product_type']
                
                if exchange not in VALID_EXCHANGES:
                    flash('Invalid exchange', 'error')
                    return redirect(url_for('chartink_bp.configure_symbols', strategy_id=strategy_id))
                
                add_symbol_mapping(
                    strategy_id=strategy_id,
                    chartink_symbol=chartink_symbol,
                    exchange=exchange,
                    quantity=quantity,
                    product_type=product_type
                )
                flash('Symbol mapping added successfully', 'success')
            
            return redirect(url_for('chartink_bp.configure_symbols', strategy_id=strategy_id))
            
        except Exception as e:
            flash(f'Error adding symbol mapping: {str(e)}', 'error')
            
    symbol_mappings = get_symbol_mappings(strategy_id)
    return render_template('chartink/configure_symbols.html', 
                         strategy=strategy,
                         symbol_mappings=symbol_mappings,
                         exchanges=VALID_EXCHANGES)

@chartink_bp.route('/<int:strategy_id>/symbol/<int:mapping_id>/delete', methods=['POST'])
@check_session_validity
def delete_symbol(strategy_id, mapping_id):
    """Delete a symbol mapping"""
    try:
        strategy = ChartinkStrategy.query.get(strategy_id)
        if not strategy or strategy.user_id != session['user']:
            abort(403)
            
        if delete_symbol_mapping(strategy_id, mapping_id):
            flash('Symbol mapping deleted successfully', 'success')
        else:
            flash('Symbol mapping not found', 'error')
    except Exception as e:
        flash(f'Error deleting symbol mapping: {str(e)}', 'error')
        
    return redirect(url_for('chartink_bp.configure_symbols', strategy_id=strategy_id))

@chartink_bp.route('/<int:strategy_id>/times', methods=['POST'])
@check_session_validity
def update_times(strategy_id):
    """Update strategy trading times"""
    try:
        strategy = ChartinkStrategy.query.get(strategy_id)
        if not strategy or strategy.user_id != session['user']:
            abort(403)
            
        start_time = request.form.get('start_time')
        end_time = request.form.get('end_time')
        squareoff_time = request.form.get('squareoff_time')
        
        # Validate time format
        for time_str in [start_time, end_time, squareoff_time]:
            if time_str:
                try:
                    datetime.strptime(time_str, '%H:%M:%S')
                except ValueError:
                    return jsonify({'error': 'Invalid time format. Use HH:MM:SS'}), 400
        
        if update_strategy_times(strategy_id, start_time, end_time, squareoff_time):
            # Update squareoff schedule if time changed
            if squareoff_time:
                schedule_squareoff(strategy_id)
            return jsonify({'status': 'success'})
        return jsonify({'error': 'Strategy not found'}), 404
        
    except Exception as e:
        logger.error(f"Error updating strategy times: {str(e)}")
        return jsonify({'error': str(e)}), 500

@chartink_bp.route('/webhook/<webhook_id>', methods=['POST'])
def webhook(webhook_id):
    """Handle incoming webhooks from Chartink"""
    try:
        data = request.json
        
        # Get strategy for this webhook
        strategy = get_strategy_by_webhook_id(webhook_id)
        if not strategy:
            return jsonify({'error': 'Invalid webhook ID'}), 404
            
        # Check if within trading hours for intraday
        if strategy.is_intraday:
            now = datetime.now(pytz.timezone('Asia/Kolkata'))
            current_time = now.strftime('%H:%M:%S')
            
            if current_time < strategy.start_time:
                return jsonify({'error': 'Before signal start time'}), 400
                
            if current_time > strategy.end_time:
                return jsonify({'error': 'After trading end time'}), 400
        
        # Get API key for orders using strategy's user_id
        api_key = get_api_key_for_tradingview(strategy.user_id)
        if not api_key:
            logger.error(f"API key not found for user {strategy.user_id}")
            return jsonify({'error': 'API key not found'}), 401
            
        # Process each symbol from webhook
        stocks = data.get('stocks', '').split(',')
        trigger_prices = data.get('trigger_prices', '').split(',')
        
        # Get all configured symbols for this strategy
        symbol_mappings = {
            mapping.chartink_symbol: mapping 
            for mapping in get_symbol_mappings(strategy.id)
        }
        
        # If no symbols configured, return error
        if not symbol_mappings:
            return jsonify({'error': 'No symbols configured for strategy'}), 400
        
        for stock, price in zip(stocks, trigger_prices):
            # Find mapping for this symbol
            mapping = symbol_mappings.get(stock)
            
            if not mapping:
                logger.warning(f"No mapping found for symbol {stock}")
                continue
                
            try:
                # For entry orders (BUY/SHORT)
                if data.get('scan_name', '').lower().endswith('buy'):
                    response = requests.post(
                        f"{BASE_URL}/api/v1/placeorder",
                        json={
                            "apikey": api_key,
                            "strategy": strategy.name,
                            "symbol": mapping.chartink_symbol,
                            "exchange": mapping.exchange,
                            "action": "BUY",
                            "product": mapping.product_type,
                            "quantity": str(mapping.quantity),
                            "pricetype": "MARKET"
                        }
                    )
                elif data.get('scan_name', '').lower().endswith('short'):
                    response = requests.post(
                        f"{BASE_URL}/api/v1/placeorder",
                        json={
                            "apikey": api_key,
                            "strategy": strategy.name,
                            "symbol": mapping.chartink_symbol,
                            "exchange": mapping.exchange,
                            "action": "SELL",
                            "product": mapping.product_type,
                            "quantity": str(mapping.quantity),
                            "pricetype": "MARKET"
                        }
                    )
                # For exit orders (SELL/COVER)
                elif data.get('scan_name', '').lower().endswith('sell'):
                    response = requests.post(
                        f"{BASE_URL}/api/v1/placesmartorder",
                        json={
                            "apikey": api_key,
                            "strategy": strategy.name,
                            "symbol": mapping.chartink_symbol,
                            "exchange": mapping.exchange,
                            "action": "SELL",
                            "product": mapping.product_type,
                            "quantity": "0",
                            "position_size": "0",
                            "pricetype": "MARKET"
                        }
                    )
                elif data.get('scan_name', '').lower().endswith('cover'):
                    response = requests.post(
                        f"{BASE_URL}/api/v1/placesmartorder",
                        json={
                            "apikey": api_key,
                            "strategy": strategy.name,
                            "symbol": mapping.chartink_symbol,
                            "exchange": mapping.exchange,
                            "action": "BUY",
                            "product": mapping.product_type,
                            "quantity": "0",
                            "position_size": "0",
                            "pricetype": "MARKET"
                        }
                    )
                
                if not response.ok:
                    logger.error(f"Error placing order for {stock}: {response.text}")
                    
            except Exception as e:
                logger.error(f"Error placing order for {stock}: {str(e)}")
                
        return jsonify({'status': 'success'})
        
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return jsonify({'error': str(e)}), 500

@chartink_bp.route('/<int:strategy_id>/delete', methods=['POST'])
@check_session_validity
def delete(strategy_id):
    """Delete a strategy"""
    try:
        strategy = ChartinkStrategy.query.get(strategy_id)
        if not strategy or strategy.user_id != session['user']:
            abort(403)
            
        if delete_strategy(strategy_id):
            # Remove scheduled squareoff job if exists
            job_id = f'squareoff_{strategy_id}'
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
            flash('Strategy deleted successfully', 'success')
        else:
            flash('Strategy not found', 'error')
    except Exception as e:
        flash(f'Error deleting strategy: {str(e)}', 'error')
        
    return redirect(url_for('chartink_bp.index'))

@chartink_bp.route('/search')
@check_session_validity
def search():
    """Search symbols endpoint"""
    query = request.args.get('q', '').strip()
    exchange = request.args.get('exchange')
    
    if not query:
        return jsonify({'results': []})
        
    if exchange and exchange not in VALID_EXCHANGES:
        return jsonify({'error': 'Invalid exchange'}), 400
        
    results = enhanced_search_symbols(query, exchange)
    results_list = [{
        'symbol': result.symbol,
        'exchange': result.exchange,
        'name': result.name
    } for result in results]
    
    return jsonify({'results': results_list})
