from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from flask_cors import cross_origin
from datetime import datetime, time, timedelta
import pandas as pd
import numpy as np
from importlib import import_module
from database.auth_db import get_auth_token, get_api_key_for_tradingview
from utils.session import check_session_validity
from utils.logging import get_logger
from services.tradebook_service import get_tradebook
from services.history_service import get_history
import traceback
import pytz

logger = get_logger(__name__)

# Define the blueprint
pnltracker_bp = Blueprint('pnltracker_bp', __name__, url_prefix='/')

def dynamic_import(broker, module_name, function_names):
    module_functions = {}
    try:
        # Import the module based on the broker name
        module = import_module(f'broker.{broker}.{module_name}')
        for name in function_names:
            module_functions[name] = getattr(module, name)
        return module_functions
    except (ImportError, AttributeError) as e:
        logger.error(f"Error importing functions {function_names} from {module_name} for broker {broker}: {e}")
        return None

@pnltracker_bp.route('/pnltracker')
@check_session_validity
def pnltracker():
    """Render the PnL tracker page."""
    return render_template('pnltracker.html')

@pnltracker_bp.route('/test_chart')
def test_chart():
    """Test page for LightWeight Charts."""
    return render_template('test_chart.html')

@pnltracker_bp.route('/pnltracker/api/pnl', methods=['POST'])
@cross_origin()
@check_session_validity
def get_pnl_data():
    """Get intraday PnL data."""
    try:
        broker = session.get('broker')
        if not broker:
            logger.error("Broker not set in session")
            return jsonify({
                'status': 'error',
                'message': 'Broker not set in session'
            }), 400

        # Get auth token from session - same as orders.py
        login_username = session['user']
        auth_token = get_auth_token(login_username)
        
        if auth_token is None:
            logger.warning(f"No auth token found for user {login_username}")
            return jsonify({
                'status': 'error',
                'message': 'Authentication required'
            }), 401

        # Get API key for the user (for services)
        api_key = get_api_key_for_tradingview(login_username)
        if not api_key:
            logger.warning(f"No API key found for user {login_username}")
            return jsonify({
                'status': 'error',
                'message': 'API key not configured. Please generate an API key in /apikey'
            }), 401

        # Get today's date
        today = datetime.now().date()
        today_str = today.strftime("%Y-%m-%d")
        
        # Get tradebook data using the service (with API key)
        success, tradebook_response, status_code = get_tradebook(api_key=api_key)
        
        if not success:
            logger.error(f"Error fetching tradebook: {tradebook_response}")
            return jsonify(tradebook_response), status_code
        
        trades = tradebook_response.get('data', [])
        
        # Log trades for debugging
        logger.info(f"Number of trades: {len(trades)}")
        if trades and len(trades) > 0:
            logger.info(f"Sample trade: {trades[0]}")
        
        # Get positions using dynamic import (same as orders.py)
        api_funcs = dynamic_import(broker, 'api.order_api', ['get_positions'])
        mapping_funcs = dynamic_import(broker, 'mapping.order_data', [
            'map_position_data', 'transform_positions_data'
        ])
        
        if not api_funcs or not mapping_funcs:
            logger.error(f"Error loading broker-specific modules for {broker}")
            return jsonify({
                'status': 'error',
                'message': 'Error loading broker-specific modules'
            }), 500
        
        # Get current positions for real-time P&L
        current_positions = {}
        try:
            get_positions = api_funcs['get_positions']
            positions_data = get_positions(auth_token)
            
            if positions_data and ('status' not in positions_data or positions_data['status'] != 'error'):
                map_position_data = mapping_funcs['map_position_data']
                transform_positions_data = mapping_funcs['transform_positions_data']
                
                positions_data = map_position_data(positions_data)
                positions_data = transform_positions_data(positions_data)
                
                # Store current positions for reference
                logger.info(f"Number of positions: {len(positions_data) if positions_data else 0}")
                for pos in positions_data:
                    key = f"{pos['symbol']}_{pos['exchange']}"
                    current_positions[key] = {
                        'quantity': pos.get('quantity', 0),
                        'average_price': pos.get('average_price', 0),
                        'ltp': pos.get('ltp', 0),
                        'pnl': pos.get('pnl', 0)
                    }
                    logger.info(f"Position {key}: qty={pos.get('quantity', 0)}, avg={pos.get('average_price', 0)}, ltp={pos.get('ltp', 0)}, pnl={pos.get('pnl', 0)}")
        except Exception as e:
            logger.warning(f"Error fetching positions: {e}")
            # Continue without positions data
        
        if not trades and not current_positions:
            # No trades or positions, return zero PnL
            return jsonify({
                'status': 'success',
                'data': {
                    'current_mtm': 0,
                    'max_mtm': 0,
                    'max_mtm_time': None,
                    'min_mtm': 0,
                    'min_mtm_time': None,
                    'max_drawdown': 0,
                    'pnl_series': [],
                    'drawdown_series': []
                }
            }), 200
        
        # Process trades to build portfolio MTM
        portfolio_pnl = None
        
        # Process each trade and get its historical data
        for trade in trades:
            symbol = trade['symbol']
            exchange = trade['exchange']
            executed_price = trade.get('average_price', 0)
            action = trade['action']
            
            # Calculate quantity
            qty = trade.get('quantity', 0)
            if qty == 0 and executed_price > 0:
                # For MCX/commodities, when trade_value equals average_price, it's 1 lot
                if trade.get('trade_value', 0) == executed_price:
                    qty = 1
                else:
                    qty = trade.get('trade_value', 0) / executed_price
            
            if qty <= 0:
                logger.warning(f"Skipping trade with zero/negative quantity: {trade}")
                continue
            
            orderid_suffix = str(trade.get('orderid', ''))[-4:]
            symbol_label = f"{symbol}_{orderid_suffix}"
            
            try:
                # Get historical data for this symbol
                success, hist_response, _ = get_history(
                    symbol=symbol,
                    exchange=exchange,
                    interval='1m',
                    start_date=today_str,
                    end_date=today_str,
                    api_key=api_key
                )
                
                if success and 'data' in hist_response:
                    df_hist = pd.DataFrame(hist_response['data'])
                    if not df_hist.empty:
                        # Convert timestamp to datetime in IST
                        # Timestamps are typically in UTC, convert to IST
                        ist = pytz.timezone('Asia/Kolkata')
                        df_hist['datetime'] = pd.to_datetime(df_hist['timestamp'], unit='s', utc=True)
                        df_hist['datetime'] = df_hist['datetime'].dt.tz_convert(ist)
                        df_hist.set_index('datetime', inplace=True)
                        df_hist = df_hist.sort_index()
                        
                        # Filter to show data from 9 AM IST onwards
                        today_9am = df_hist.index[0].replace(hour=9, minute=0, second=0, microsecond=0)
                        current_time = datetime.now(ist)
                        df_hist = df_hist[df_hist.index >= today_9am]
                        df_hist = df_hist[df_hist.index <= current_time]
                        
                        df_hist = df_hist[['close']].copy()
                        df_hist.rename(columns={'close': f'{symbol_label}_price'}, inplace=True)
                        
                        # Calculate MTM PnL for this trade
                        if action == 'BUY':
                            df_hist[f'{symbol_label}_pnl'] = (df_hist[f'{symbol_label}_price'] - executed_price) * qty
                        else:  # SELL
                            df_hist[f'{symbol_label}_pnl'] = (executed_price - df_hist[f'{symbol_label}_price']) * qty
                        
                        # Combine into portfolio
                        if portfolio_pnl is None:
                            portfolio_pnl = df_hist[[f'{symbol_label}_pnl']].copy()
                        else:
                            portfolio_pnl = portfolio_pnl.join(df_hist[[f'{symbol_label}_pnl']], how='outer')
                        
                        logger.info(f"Added PnL for {symbol_label}: {len(df_hist)} data points")
                else:
                    logger.warning(f"Could not get historical data for {symbol}")
                    
            except Exception as e:
                logger.error(f"Error processing trade for {symbol}: {e}")
                continue
        
        # If we have no portfolio data, create a simple series based on current positions
        if portfolio_pnl is None and current_positions:
            # Create a time series from market open to now in IST
            ist = pytz.timezone('Asia/Kolkata')
            current_time = datetime.now(ist)
            # Start from 9:00 AM IST
            start_time = current_time.replace(hour=9, minute=0, second=0, microsecond=0)
            end_time = current_time
            
            time_range = pd.date_range(start=start_time, end=end_time, freq='1min', tz=ist)
            portfolio_pnl = pd.DataFrame(index=time_range)
            
            # Use current position P&L as constant value
            total_pnl = sum(pos['pnl'] for pos in current_positions.values())
            portfolio_pnl['Total_PnL'] = total_pnl
        elif portfolio_pnl is not None:
            # Calculate total MTM and drawdown
            # Use ffill() instead of fillna(method='ffill') for pandas 2.x compatibility
            portfolio_pnl = portfolio_pnl.ffill().fillna(0)
            portfolio_pnl['Total_PnL'] = portfolio_pnl.sum(axis=1)
        else:
            # No data at all
            return jsonify({
                'status': 'success',
                'data': {
                    'current_mtm': 0,
                    'max_mtm': 0,
                    'max_mtm_time': None,
                    'min_mtm': 0,
                    'min_mtm_time': None,
                    'max_drawdown': 0,
                    'pnl_series': [],
                    'drawdown_series': []
                }
            }), 200
        
        # Calculate drawdown
        portfolio_pnl['Peak'] = portfolio_pnl['Total_PnL'].cummax()
        portfolio_pnl['Drawdown'] = portfolio_pnl['Total_PnL'] - portfolio_pnl['Peak']
        
        # Calculate metrics
        latest_mtm = portfolio_pnl['Total_PnL'].iloc[-1] if not portfolio_pnl.empty else 0
        max_mtm = portfolio_pnl['Total_PnL'].max() if not portfolio_pnl.empty else 0
        min_mtm = portfolio_pnl['Total_PnL'].min() if not portfolio_pnl.empty else 0
        max_drawdown = portfolio_pnl['Drawdown'].min() if not portfolio_pnl.empty else 0
        
        try:
            max_mtm_time = portfolio_pnl['Total_PnL'].idxmax().strftime('%H:%M') if not portfolio_pnl.empty else None
            min_mtm_time = portfolio_pnl['Total_PnL'].idxmin().strftime('%H:%M') if not portfolio_pnl.empty else None
        except:
            max_mtm_time = None
            min_mtm_time = None
        
        # Convert to series format for frontend
        pnl_series = []
        drawdown_series = []
        
        if not portfolio_pnl.empty:
            for idx, row in portfolio_pnl.iterrows():
                try:
                    # Convert to timestamp - handle timezone-aware datetime
                    if hasattr(idx, 'tz') and idx.tz is not None:
                        # Already timezone-aware, convert to UTC then to timestamp
                        timestamp_ms = int(idx.tz_convert('UTC').timestamp() * 1000)
                    else:
                        # Naive datetime, assume it's already in local time
                        timestamp_ms = int(idx.timestamp() * 1000)
                    pnl_value = row.get('Total_PnL', 0)
                    drawdown_value = row.get('Drawdown', 0)
                    
                    # Handle NaN values
                    if pd.isna(pnl_value):
                        pnl_value = 0
                    if pd.isna(drawdown_value):
                        drawdown_value = 0
                    
                    pnl_series.append({
                        'time': timestamp_ms,
                        'value': round(float(pnl_value), 2)
                    })
                    drawdown_series.append({
                        'time': timestamp_ms,
                        'value': round(float(drawdown_value), 2)
                    })
                except Exception as e:
                    logger.warning(f"Error processing row {idx}: {e}")
                    continue
        
        logger.info(f"Final metrics - Current: {latest_mtm}, Max: {max_mtm}, Min: {min_mtm}, Drawdown: {max_drawdown}")
        logger.info(f"PnL series length: {len(pnl_series)}")
        
        return jsonify({
            'status': 'success',
            'data': {
                'current_mtm': round(latest_mtm, 2),
                'max_mtm': round(max_mtm, 2),
                'max_mtm_time': max_mtm_time,
                'min_mtm': round(min_mtm, 2),
                'min_mtm_time': min_mtm_time,
                'max_drawdown': round(max_drawdown, 2),
                'pnl_series': pnl_series,
                'drawdown_series': drawdown_series
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error calculating intraday PnL: {e}")
        traceback.print_exc()
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500