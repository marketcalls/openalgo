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

def convert_timestamp_to_ist(df, symbol=""):
    """
    Convert timestamp to IST with robust handling for different formats.
    Returns the dataframe with datetime index in IST timezone.
    """
    ist = pytz.timezone('Asia/Kolkata')
    
    try:
        # Try different timestamp formats
        if 'timestamp' in df.columns:
            # Try as Unix timestamp first (seconds)
            try:
                df['datetime'] = pd.to_datetime(df['timestamp'], unit='s', utc=True)
                df['datetime'] = df['datetime'].dt.tz_convert(ist)
            except:
                # Try as milliseconds
                try:
                    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
                    df['datetime'] = df['datetime'].dt.tz_convert(ist)
                except:
                    # Try as string datetime
                    df['datetime'] = pd.to_datetime(df['timestamp'])
                    if df['datetime'].dt.tz is None:
                        df['datetime'] = df['datetime'].dt.tz_localize('UTC').dt.tz_convert(ist)
                    else:
                        df['datetime'] = df['datetime'].dt.tz_convert(ist)
        elif 'datetime' in df.columns:
            df['datetime'] = pd.to_datetime(df['datetime'])
            if df['datetime'].dt.tz is None:
                df['datetime'] = df['datetime'].dt.tz_localize('UTC').dt.tz_convert(ist)
            else:
                df['datetime'] = df['datetime'].dt.tz_convert(ist)
        else:
            logger.warning(f"No timestamp field found for {symbol}")
            return None
        
        df.set_index('datetime', inplace=True)
        df = df.sort_index()
        return df
    except Exception as e:
        logger.warning(f"Error converting timestamps for {symbol}: {e}")
        return None

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
                    # Convert string values to float if needed
                    try:
                        qty = float(pos.get('quantity', 0))
                        avg_price = float(pos.get('average_price', 0))
                        ltp = float(pos.get('ltp', 0))
                        pnl = float(pos.get('pnl', 0))
                    except (ValueError, TypeError):
                        logger.warning(f"Error converting position values to float for {key}")
                        qty = 0
                        avg_price = 0
                        ltp = 0
                        pnl = 0
                    
                    current_positions[key] = {
                        'quantity': qty,
                        'average_price': avg_price,
                        'ltp': ltp,
                        'pnl': pnl
                    }
                    logger.info(f"Position {key}: qty={qty}, avg={avg_price}, ltp={ltp}, pnl={pnl}")
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
        first_trade_time = None
        
        # Find the earliest trade time
        for trade in trades:
            # Try to parse trade timestamp - prioritize timestamp field which appears to be in HH:MM:SS format
            trade_timestamp = trade.get('timestamp') or trade.get('fill_timestamp') or trade.get('fill_time')
            if trade_timestamp:
                try:
                    # Check if it's a time string in HH:MM:SS format
                    if isinstance(trade_timestamp, str) and ':' in trade_timestamp and len(trade_timestamp.split(':')[0]) <= 2:
                        # Parse as time string (e.g., "10:30:52")
                        ist = pytz.timezone('Asia/Kolkata')
                        today = datetime.now(ist).date()
                        time_parts = trade_timestamp.split(':')
                        trade_time = ist.localize(datetime.combine(today, time(
                            int(time_parts[0]), 
                            int(time_parts[1]), 
                            int(time_parts[2]) if len(time_parts) > 2 else 0
                        )))
                    elif isinstance(trade_timestamp, (int, float)):
                        # Unix timestamp
                        trade_time = pd.to_datetime(trade_timestamp, unit='s')
                        ist = pytz.timezone('Asia/Kolkata')
                        if trade_time.tz is None:
                            trade_time = trade_time.tz_localize('UTC').tz_convert(ist)
                        else:
                            trade_time = trade_time.tz_convert(ist)
                    else:
                        # String timestamp in datetime format
                        trade_time = pd.to_datetime(trade_timestamp)
                        ist = pytz.timezone('Asia/Kolkata')
                        if trade_time.tz is None:
                            # Assume it's already in IST
                            trade_time = trade_time.tz_localize(ist)
                        else:
                            trade_time = trade_time.tz_convert(ist)
                    
                    # Track the earliest trade time
                    if first_trade_time is None or trade_time < first_trade_time:
                        first_trade_time = trade_time
                        logger.info(f"Found trade at {trade_time.strftime('%H:%M:%S')} for {trade['symbol']}")
                except Exception as e:
                    logger.warning(f"Could not parse trade timestamp {trade_timestamp}: {e}")
        
        # If we couldn't determine first trade time from timestamps, try from fill_time field
        if first_trade_time is None and trades:
            # Look for fill_time in format HH:MM:SS or timestamp
            for trade in trades:
                fill_time_str = trade.get('fill_time', '')
                if fill_time_str:
                    try:
                        # Try parsing as time string (e.g., "10:30:52")
                        if ':' in str(fill_time_str):
                            ist = pytz.timezone('Asia/Kolkata')
                            today = datetime.now(ist).date()
                            time_parts = str(fill_time_str).split(':')
                            trade_time = ist.localize(datetime.combine(today, time(
                                int(time_parts[0]), 
                                int(time_parts[1]), 
                                int(time_parts[2]) if len(time_parts) > 2 else 0
                            )))
                            if first_trade_time is None or trade_time < first_trade_time:
                                first_trade_time = trade_time
                                logger.info(f"Found trade at {trade_time.strftime('%H:%M:%S')} from fill_time for {trade['symbol']}")
                    except Exception as e:
                        logger.warning(f"Could not parse fill_time {fill_time_str}: {e}")
        
        # Log the first trade time
        if first_trade_time:
            logger.info(f"First trade time: {first_trade_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        else:
            logger.warning("Could not determine first trade time, using market open time")
            ist = pytz.timezone('Asia/Kolkata')
            first_trade_time = datetime.now(ist).replace(hour=9, minute=15, second=0, microsecond=0)
        
        # Group trades by symbol to track entry and exit
        symbol_trades = {}
        for trade in trades:
            try:
                symbol = trade.get('symbol', '')
                exchange = trade.get('exchange', '')
                if not symbol or not exchange:
                    logger.warning(f"Trade missing symbol or exchange: {trade}")
                    continue
                    
                symbol_key = f"{symbol}_{exchange}"
                if symbol_key not in symbol_trades:
                    symbol_trades[symbol_key] = []
                
                # Parse trade time
                trade_timestamp = trade.get('timestamp') or trade.get('fill_timestamp') or trade.get('fill_time')
                trade_time = None
                if trade_timestamp:
                    try:
                        if isinstance(trade_timestamp, str) and ':' in trade_timestamp and len(trade_timestamp.split(':')[0]) <= 2:
                            ist = pytz.timezone('Asia/Kolkata')
                            today = datetime.now(ist).date()
                            time_parts = trade_timestamp.split(':')
                            trade_time = ist.localize(datetime.combine(today, time(
                                int(time_parts[0]), 
                                int(time_parts[1]), 
                                int(time_parts[2]) if len(time_parts) > 2 else 0
                            )))
                        else:
                            trade_time = pd.to_datetime(trade_timestamp)
                            ist = pytz.timezone('Asia/Kolkata')
                            if trade_time.tz is None:
                                trade_time = trade_time.tz_localize(ist)
                            else:
                                trade_time = trade_time.tz_convert(ist)
                    except Exception as e:
                        logger.warning(f"Could not parse trade time for {trade}: {e}")
                
                trade['parsed_time'] = trade_time
                symbol_trades[symbol_key].append(trade)
            except Exception as e:
                logger.error(f"Error processing trade: {e}, trade: {trade}")
                continue
        
        # Process each symbol's trades
        for symbol_key, trades_list in symbol_trades.items():
            if not trades_list:
                logger.warning(f"No trades found for {symbol_key}")
                continue
                
            # Sort trades by time
            trades_list.sort(key=lambda x: x.get('parsed_time') or datetime.min.replace(tzinfo=pytz.UTC))
            
            symbol = trades_list[0].get('symbol', '')
            exchange = trades_list[0].get('exchange', '')
            
            if not symbol or not exchange:
                logger.warning(f"Missing symbol or exchange for {symbol_key}")
                continue
            
            # Track net position and time windows
            net_position = 0
            position_windows = []  # List of (start_time, end_time, qty, price, action)
            
            for trade in trades_list:
                try:
                    executed_price = float(trade.get('average_price', 0))
                    action = trade.get('action', '')
                    trade_time = trade.get('parsed_time')
                    
                    # Calculate quantity
                    qty = float(trade.get('quantity', 0))
                    if qty == 0 and executed_price > 0:
                        trade_value = float(trade.get('trade_value', 0))
                        if trade_value == executed_price:
                            qty = 1
                        elif trade_value > 0:
                            qty = trade_value / executed_price
                    
                    if qty <= 0:
                        logger.warning(f"Skipping trade with zero/negative quantity: {trade}")
                        continue
                except (TypeError, ValueError) as e:
                    logger.warning(f"Error parsing trade values: {e}, trade: {trade}")
                    continue
                
                # Track position windows
                if action == 'BUY':
                    position_windows.append({
                        'start_time': trade_time,
                        'end_time': None,  # Will be filled when position is closed
                        'qty': qty,
                        'price': executed_price,
                        'action': 'BUY',
                        'exit_price': None  # Will be filled when position is closed
                    })
                    net_position += qty
                else:  # SELL
                    # Check if this closes a position
                    if net_position > 0:
                        # This is closing a long position
                        remaining_qty = qty
                        for window in position_windows:
                            if window['action'] == 'BUY' and window['end_time'] is None and remaining_qty > 0:
                                # Close this position window
                                close_qty = min(window['qty'], remaining_qty)
                                if close_qty == window['qty']:
                                    window['end_time'] = trade_time
                                    window['exit_price'] = executed_price  # Store the actual exit price
                                else:
                                    # Partial close - split the window
                                    window['qty'] -= close_qty
                                    # Create a closed window for the partial
                                    closed_window = window.copy()
                                    closed_window['qty'] = close_qty
                                    closed_window['end_time'] = trade_time
                                    closed_window['exit_price'] = executed_price  # Store the actual exit price
                                    position_windows.append(closed_window)
                                remaining_qty -= close_qty
                        net_position -= qty
                    else:
                        # This is a short position
                        position_windows.append({
                            'start_time': trade_time,
                            'end_time': None,
                            'qty': qty,
                            'price': executed_price,
                            'action': 'SELL',
                            'exit_price': None
                        })
                        net_position -= qty
            
            # Now get historical data and calculate PnL for each position window
            try:
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
                        df_hist = convert_timestamp_to_ist(df_hist, symbol)
                        
                        if df_hist is not None:
                            ist = pytz.timezone('Asia/Kolkata')
                            current_time = datetime.now(ist)
                            
                            # Filter to trading hours
                            if first_trade_time:
                                df_hist = df_hist[df_hist.index >= first_trade_time]
                            df_hist = df_hist[df_hist.index <= current_time]
                            
                            df_hist = df_hist[['close']].copy()
                            df_hist.rename(columns={'close': f'{symbol}_price'}, inplace=True)
                            
                            # Initialize PnL column
                            df_hist[f'{symbol}_pnl'] = 0.0
                            
                            # Track cumulative realized PnL
                            cumulative_realized_pnl = 0.0
                            
                            # Sort position windows by start time
                            position_windows_sorted = sorted(position_windows, 
                                                            key=lambda x: x['start_time'] if x['start_time'] else datetime.min.replace(tzinfo=pytz.UTC))
                            
                            # Calculate PnL for each position window
                            for window in position_windows_sorted:
                                if window['start_time'] is None:
                                    continue
                                    
                                # Determine the time range for this position
                                start = window['start_time']
                                end = window['end_time'] if window['end_time'] else current_time
                                
                                # Create mask for this time window
                                mask = (df_hist.index >= start) & (df_hist.index <= end)
                                
                                # Skip if no data points in this window
                                if not mask.any():
                                    logger.warning(f"No data points found for position window from {start} to {end}")
                                    continue
                                
                                # Calculate PnL for this window
                                if window['action'] == 'BUY':
                                    position_pnl = (df_hist.loc[mask, f'{symbol}_price'] - window['price']) * window['qty']
                                    df_hist.loc[mask, f'{symbol}_pnl'] += position_pnl
                                    
                                    # If position is closed, calculate realized PnL using actual exit price
                                    if window['end_time'] and window.get('exit_price'):
                                        realized = (window['exit_price'] - window['price']) * window['qty']
                                        cumulative_realized_pnl += realized
                                        logger.info(f"Closed BUY position: entry={window['price']}, exit={window['exit_price']}, "
                                                  f"qty={window['qty']}, realized PnL={realized}")
                                else:  # SELL
                                    position_pnl = (window['price'] - df_hist.loc[mask, f'{symbol}_price']) * window['qty']
                                    df_hist.loc[mask, f'{symbol}_pnl'] += position_pnl
                                    
                                    # If position is closed, calculate realized PnL using actual exit price
                                    if window['end_time'] and window.get('exit_price'):
                                        realized = (window['price'] - window['exit_price']) * window['qty']
                                        cumulative_realized_pnl += realized
                                        logger.info(f"Closed SELL position: entry={window['price']}, exit={window['exit_price']}, "
                                                  f"qty={window['qty']}, realized PnL={realized}")
                                
                                # After a position is closed, add the cumulative realized PnL to all future timestamps
                                if window['end_time'] and cumulative_realized_pnl != 0:
                                    future_mask = df_hist.index > window['end_time']
                                    df_hist.loc[future_mask, f'{symbol}_pnl'] = cumulative_realized_pnl
                                
                                logger.info(f"Position window for {symbol}: {window['action']} {window['qty']} @ {window['price']}, "
                                          f"from {start.strftime('%H:%M:%S') if start else 'None'} "
                                          f"to {end.strftime('%H:%M:%S') if end else 'current'}")
                            
                            # Add to portfolio
                            if portfolio_pnl is None:
                                portfolio_pnl = df_hist[[f'{symbol}_pnl']].copy()
                            else:
                                portfolio_pnl = portfolio_pnl.join(df_hist[[f'{symbol}_pnl']], how='outer')
                            
                            logger.info(f"Added PnL for {symbol}: {len(df_hist)} data points")
                        else:
                            logger.warning(f"Timestamp conversion failed for {symbol}")
                else:
                    logger.warning(f"Could not get historical data for {symbol}")
                    
            except Exception as e:
                logger.error(f"Error processing trades for {symbol}: {e}")
                continue
        
        # If we have no portfolio data but have positions, fetch historical data for positions
        if portfolio_pnl is None and current_positions:
            logger.info("No trades found, but positions exist. Fetching historical data for positions.")
            
            # Process each position and get its historical data
            for pos_key, pos_data in current_positions.items():
                # Extract symbol and exchange from the key
                parts = pos_key.rsplit('_', 1)
                if len(parts) == 2:
                    symbol, exchange = parts
                else:
                    logger.warning(f"Could not parse position key: {pos_key}")
                    continue
                
                qty = pos_data['quantity']
                avg_price = pos_data['average_price']
                
                if qty == 0:
                    continue
                    
                try:
                    # Get historical data for this position
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
                            # Convert timestamp to IST with robust handling
                            df_hist = convert_timestamp_to_ist(df_hist, symbol)
                            
                            if df_hist is not None:
                                # Filter to show data from first trade time onwards
                                ist = pytz.timezone('Asia/Kolkata')
                                current_time = datetime.now(ist)
                                
                                # For positions without trades, we still need to determine when to start
                                # Use market open time as default
                                today_915am = df_hist.index[0].replace(hour=9, minute=15, second=0, microsecond=0)
                                df_hist = df_hist[df_hist.index >= today_915am]
                                df_hist = df_hist[df_hist.index <= current_time]
                            else:
                                logger.warning(f"Timestamp conversion failed for position {symbol}, skipping")
                                continue
                            
                            df_hist = df_hist[['close']].copy()
                            df_hist.rename(columns={'close': f'{symbol}_price'}, inplace=True)
                            
                            # Calculate MTM PnL for this position
                            # For positions, we use the average price from the position data
                            if qty > 0:  # Long position
                                df_hist[f'{symbol}_pnl'] = (df_hist[f'{symbol}_price'] - avg_price) * qty
                            else:  # Short position
                                df_hist[f'{symbol}_pnl'] = (avg_price - df_hist[f'{symbol}_price']) * abs(qty)
                            
                            # Combine into portfolio
                            if portfolio_pnl is None:
                                portfolio_pnl = df_hist[[f'{symbol}_pnl']].copy()
                            else:
                                portfolio_pnl = portfolio_pnl.join(df_hist[[f'{symbol}_pnl']], how='outer')
                            
                            logger.info(f"Added PnL for position {symbol}: {len(df_hist)} data points")
                    else:
                        logger.warning(f"Could not get historical data for position {symbol}")
                        
                except Exception as e:
                    logger.error(f"Error processing position for {symbol}: {e}")
                    continue
            
            # If we still couldn't get any historical data, create a simple flat line
            if portfolio_pnl is None:
                ist = pytz.timezone('Asia/Kolkata')
                current_time = datetime.now(ist)
                start_time = current_time.replace(hour=9, minute=0, second=0, microsecond=0)
                end_time = current_time
                
                if end_time <= start_time:
                    end_time = start_time + timedelta(minutes=1)
                
                time_range = pd.date_range(start=start_time, end=end_time, freq='1min', tz=ist)
                portfolio_pnl = pd.DataFrame(index=time_range)
                
                # Use current position P&L as constant value
                total_pnl = sum(pos['pnl'] for pos in current_positions.values())
                portfolio_pnl['Total_PnL'] = total_pnl
        elif portfolio_pnl is not None:
            # Add zero PnL data from market open to first trade if needed
            if first_trade_time and trades:
                ist = pytz.timezone('Asia/Kolkata')
                market_open = first_trade_time.replace(hour=9, minute=15, second=0, microsecond=0)
                
                # Only add pre-trade data if first trade is after market open
                if first_trade_time > market_open:
                    # Create a zero PnL series from market open to first trade
                    pre_trade_index = pd.date_range(
                        start=market_open,
                        end=first_trade_time,
                        freq='1min',
                        tz=ist
                    )[:-1]  # Exclude the first trade time itself
                    
                    if len(pre_trade_index) > 0:
                        # Create zero PnL dataframe for pre-trade period
                        pre_trade_df = pd.DataFrame(index=pre_trade_index)
                        for col in portfolio_pnl.columns:
                            pre_trade_df[col] = 0
                        
                        # Combine pre-trade zeros with actual PnL data
                        portfolio_pnl = pd.concat([pre_trade_df, portfolio_pnl]).sort_index()
                        logger.info(f"Added {len(pre_trade_index)} minutes of zero PnL before first trade")
            
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