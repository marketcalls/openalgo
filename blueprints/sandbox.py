from flask import Blueprint, render_template, jsonify, request, flash, redirect, url_for, session
from database.sandbox_db import (
    get_config, set_config, get_all_configs,
    SandboxOrders, SandboxTrades, SandboxPositions,
    SandboxHoldings, SandboxFunds, db_session
)
from utils.session import check_session_validity
from utils.logging import get_logger
from limiter import limiter
import traceback
import os

logger = get_logger(__name__)

# Use existing rate limits from .env (same as API endpoints)
API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "50 per second")

sandbox_bp = Blueprint('sandbox_bp', __name__, url_prefix='/sandbox')

@sandbox_bp.errorhandler(429)
def ratelimit_handler(e):
    """Handle rate limit exceeded errors"""
    return jsonify({
        'status': 'error',
        'message': 'Rate limit exceeded. Please try again later.'
    }), 429

@sandbox_bp.route('/')
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def sandbox_config():
    """Render the sandbox configuration page"""
    try:
        # Get all current configuration values
        configs = get_all_configs()

        # Organize configs into categories for better UI presentation
        organized_configs = {
            'capital': {
                'title': 'Capital Settings',
                'configs': {
                    'starting_capital': configs.get('starting_capital', {}),
                    'reset_day': configs.get('reset_day', {}),
                    'reset_time': configs.get('reset_time', {})
                }
            },
            'leverage': {
                'title': 'Leverage Settings',
                'configs': {
                    'equity_mis_leverage': configs.get('equity_mis_leverage', {}),
                    'equity_cnc_leverage': configs.get('equity_cnc_leverage', {}),
                    'futures_leverage': configs.get('futures_leverage', {}),
                    'option_buy_leverage': configs.get('option_buy_leverage', {}),
                    'option_sell_leverage': configs.get('option_sell_leverage', {})
                }
            },
            'square_off': {
                'title': 'Square-Off Times (IST)',
                'configs': {
                    'nse_bse_square_off_time': configs.get('nse_bse_square_off_time', {}),
                    'cds_bcd_square_off_time': configs.get('cds_bcd_square_off_time', {}),
                    'mcx_square_off_time': configs.get('mcx_square_off_time', {}),
                    'ncdex_square_off_time': configs.get('ncdex_square_off_time', {})
                }
            },
            'intervals': {
                'title': 'Update Intervals (seconds)',
                'configs': {
                    'order_check_interval': configs.get('order_check_interval', {}),
                    'mtm_update_interval': configs.get('mtm_update_interval', {})
                }
            }
        }

        return render_template('sandbox.html', configs=organized_configs)
    except Exception as e:
        logger.error(f"Error rendering sandbox config: {str(e)}\n{traceback.format_exc()}")
        flash('Error loading sandbox configuration', 'error')
        return redirect(url_for('core_bp.home'))

@sandbox_bp.route('/update', methods=['POST'])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def update_config():
    """Update sandbox configuration values"""
    try:
        data = request.get_json()
        config_key = data.get('config_key')
        config_value = data.get('config_value')

        if not config_key or config_value is None:
            return jsonify({
                'status': 'error',
                'message': 'Missing config_key or config_value'
            }), 400

        # Validate config value based on key
        validation_error = validate_config(config_key, config_value)
        if validation_error:
            return jsonify({
                'status': 'error',
                'message': validation_error
            }), 400

        # Update the configuration
        success = set_config(config_key, config_value)

        if success:
            logger.info(f"Sandbox config updated: {config_key} = {config_value}")

            # If starting_capital was updated, update all user funds immediately
            if config_key == 'starting_capital':
                try:
                    from database.sandbox_db import SandboxFunds, db_session
                    from decimal import Decimal

                    new_capital = Decimal(str(config_value))

                    # Update all user funds with new starting capital
                    # This resets their balance to the new capital value
                    funds = SandboxFunds.query.all()
                    for fund in funds:
                        # Calculate what the new available balance should be
                        # New available = new_capital - used_margin + total_pnl
                        fund.total_capital = new_capital
                        fund.available_balance = new_capital - fund.used_margin + fund.total_pnl

                    db_session.commit()
                    logger.info(f"Updated {len(funds)} user funds with new starting capital: ₹{new_capital}")
                except Exception as e:
                    logger.error(f"Error updating user funds with new capital: {e}")
                    db_session.rollback()

            # If square-off time was updated, reload the schedule automatically
            if config_key.endswith('square_off_time'):
                try:
                    from services.sandbox_service import sandbox_reload_squareoff_schedule
                    reload_success, reload_response, reload_status = sandbox_reload_squareoff_schedule()
                    if reload_success:
                        logger.info(f"Square-off schedule reloaded after {config_key} update")
                    else:
                        logger.warning(f"Failed to reload square-off schedule: {reload_response.get('message')}")
                except Exception as e:
                    logger.error(f"Error auto-reloading square-off schedule: {e}")

            # If reset day or reset time was updated, reload the schedule automatically
            if config_key in ['reset_day', 'reset_time']:
                try:
                    from services.sandbox_service import sandbox_reload_squareoff_schedule
                    reload_success, reload_response, reload_status = sandbox_reload_squareoff_schedule()
                    if reload_success:
                        logger.info(f"Schedule reloaded after {config_key} update")
                    else:
                        logger.warning(f"Failed to reload schedule: {reload_response.get('message')}")
                except Exception as e:
                    logger.error(f"Error auto-reloading schedule: {e}")

            return jsonify({
                'status': 'success',
                'message': f'Configuration {config_key} updated successfully'
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to update configuration'
            }), 500

    except Exception as e:
        logger.error(f"Error updating sandbox config: {str(e)}\n{traceback.format_exc()}")
        return jsonify({
            'status': 'error',
            'message': f'Error updating configuration: {str(e)}'
        }), 500

@sandbox_bp.route('/reset', methods=['POST'])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def reset_config():
    """Reset sandbox configuration to defaults and clear all sandbox data"""
    try:
        user_id = session.get('user')

        # Default configurations
        default_configs = {
            'starting_capital': '10000000.00',
            'reset_day': 'Sunday',
            'reset_time': '00:00',
            'order_check_interval': '5',
            'mtm_update_interval': '5',
            'nse_bse_square_off_time': '15:15',
            'cds_bcd_square_off_time': '16:45',
            'mcx_square_off_time': '23:30',
            'ncdex_square_off_time': '17:00',
            'equity_mis_leverage': '5',
            'equity_cnc_leverage': '1',
            'futures_leverage': '10',
            'option_buy_leverage': '1',
            'option_sell_leverage': '1'
        }

        # Reset all configurations
        for key, value in default_configs.items():
            set_config(key, value)

        # Clear all sandbox data for the current user
        try:
            # Delete all orders
            deleted_orders = SandboxOrders.query.filter_by(user_id=user_id).delete()
            logger.info(f"Deleted {deleted_orders} sandbox orders for user {user_id}")

            # Delete all trades
            deleted_trades = SandboxTrades.query.filter_by(user_id=user_id).delete()
            logger.info(f"Deleted {deleted_trades} sandbox trades for user {user_id}")

            # Delete all positions
            deleted_positions = SandboxPositions.query.filter_by(user_id=user_id).delete()
            logger.info(f"Deleted {deleted_positions} sandbox positions for user {user_id}")

            # Delete all holdings
            deleted_holdings = SandboxHoldings.query.filter_by(user_id=user_id).delete()
            logger.info(f"Deleted {deleted_holdings} sandbox holdings for user {user_id}")

            # Reset funds to starting capital
            from decimal import Decimal
            from datetime import datetime
            import pytz

            fund = SandboxFunds.query.filter_by(user_id=user_id).first()
            starting_capital = Decimal(default_configs['starting_capital'])

            if fund:
                # Reset existing fund
                fund.total_capital = starting_capital
                fund.available_balance = starting_capital
                fund.used_margin = Decimal('0.00')
                fund.unrealized_pnl = Decimal('0.00')
                fund.realized_pnl = Decimal('0.00')
                fund.total_pnl = Decimal('0.00')
                fund.last_reset_date = datetime.now(pytz.timezone('Asia/Kolkata'))
                fund.reset_count = (fund.reset_count or 0) + 1
                logger.info(f"Reset sandbox funds for user {user_id}")
            else:
                # Create new fund record
                fund = SandboxFunds(
                    user_id=user_id,
                    total_capital=starting_capital,
                    available_balance=starting_capital,
                    used_margin=Decimal('0.00'),
                    unrealized_pnl=Decimal('0.00'),
                    realized_pnl=Decimal('0.00'),
                    total_pnl=Decimal('0.00'),
                    last_reset_date=datetime.now(pytz.timezone('Asia/Kolkata')),
                    reset_count=1
                )
                db_session.add(fund)
                logger.info(f"Created new sandbox funds for user {user_id}")

            db_session.commit()
            logger.info(f"Successfully reset all sandbox data for user {user_id}")

        except Exception as e:
            db_session.rollback()
            logger.error(f"Error clearing sandbox data: {str(e)}\n{traceback.format_exc()}")
            raise

        logger.info("Sandbox configuration and data reset to defaults")
        return jsonify({
            'status': 'success',
            'message': 'Configuration and data reset to defaults successfully. All orders, trades, positions, and holdings have been cleared.'
        })

    except Exception as e:
        logger.error(f"Error resetting sandbox config: {str(e)}\n{traceback.format_exc()}")
        return jsonify({
            'status': 'error',
            'message': f'Error resetting configuration: {str(e)}'
        }), 500

@sandbox_bp.route('/reload-squareoff', methods=['POST'])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def reload_squareoff():
    """Manually reload square-off schedule from config"""
    try:
        from services.sandbox_service import sandbox_reload_squareoff_schedule

        success, response, status_code = sandbox_reload_squareoff_schedule()

        if success:
            return jsonify(response), status_code
        else:
            return jsonify(response), status_code

    except Exception as e:
        logger.error(f"Error reloading square-off schedule: {str(e)}\n{traceback.format_exc()}")
        return jsonify({
            'status': 'error',
            'message': f'Error reloading square-off schedule: {str(e)}'
        }), 500


@sandbox_bp.route('/squareoff-status')
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def squareoff_status():
    """Get current square-off scheduler status"""
    try:
        from services.sandbox_service import sandbox_get_squareoff_status

        success, response, status_code = sandbox_get_squareoff_status()

        if success:
            return jsonify(response), status_code
        else:
            return jsonify(response), status_code

    except Exception as e:
        logger.error(f"Error getting square-off status: {str(e)}\n{traceback.format_exc()}")
        return jsonify({
            'status': 'error',
            'message': f'Error getting square-off status: {str(e)}'
        }), 500


def validate_config(config_key, config_value):
    """Validate configuration values"""
    try:
        # Validate numeric values
        if config_key in ['starting_capital', 'equity_mis_leverage', 'equity_cnc_leverage',
                          'futures_leverage', 'option_buy_leverage', 'option_sell_leverage',
                          'order_check_interval', 'mtm_update_interval']:
            try:
                value = float(config_value)
                if value < 0:
                    return f'{config_key} must be a positive number'

                # Additional validations
                if config_key == 'starting_capital':
                    valid_capitals = [100000, 500000, 1000000, 2500000, 5000000, 10000000]
                    if value not in valid_capitals:
                        return 'Starting capital must be one of: ₹1L, ₹5L, ₹10L, ₹25L, ₹50L, or ₹1Cr'

                if config_key.endswith('_leverage'):
                    if value < 1:
                        return 'Leverage must be at least 1x'
                    if value > 50:
                        return 'Leverage cannot exceed 50x'

                # Interval validations
                if config_key == 'order_check_interval':
                    if value < 1 or value > 30:
                        return 'Order check interval must be between 1-30 seconds'

                if config_key == 'mtm_update_interval':
                    if value < 0 or value > 60:
                        return 'MTM update interval must be between 0-60 seconds (0 = manual only)'

            except ValueError:
                return f'{config_key} must be a valid number'

        # Validate time format (HH:MM)
        if config_key.endswith('_time'):
            if ':' not in config_value:
                return 'Time must be in HH:MM format'
            try:
                hours, minutes = config_value.split(':')
                if not (0 <= int(hours) <= 23 and 0 <= int(minutes) <= 59):
                    return 'Invalid time format'
            except:
                return 'Time must be in HH:MM format'

        # Validate day of week
        if config_key == 'reset_day':
            valid_days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            if config_value not in valid_days:
                return f'Reset day must be one of: {", ".join(valid_days)}'

        return None  # No validation error

    except Exception as e:
        logger.error(f"Error validating config: {str(e)}")
        return f'Validation error: {str(e)}'
