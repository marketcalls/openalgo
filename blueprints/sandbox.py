from flask import Blueprint, render_template, jsonify, request, flash, redirect, url_for
from database.sandbox_db import get_config, set_config, get_all_configs
from utils.session import check_session_validity
from utils.logging import get_logger
import traceback

logger = get_logger(__name__)

sandbox_bp = Blueprint('sandbox_bp', __name__, url_prefix='/sandbox')

@sandbox_bp.route('/')
@check_session_validity
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
            },
            'rate_limits': {
                'title': 'Rate Limits',
                'configs': {
                    'order_rate_limit': configs.get('order_rate_limit', {}),
                    'api_rate_limit': configs.get('api_rate_limit', {}),
                    'smart_order_rate_limit': configs.get('smart_order_rate_limit', {}),
                    'smart_order_delay': configs.get('smart_order_delay', {})
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
def reset_config():
    """Reset sandbox configuration to defaults"""
    try:
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
            'option_sell_leverage': '10',
            'order_rate_limit': '10',
            'api_rate_limit': '50',
            'smart_order_rate_limit': '2',
            'smart_order_delay': '0.5'
        }

        # Reset all configurations
        for key, value in default_configs.items():
            set_config(key, value)

        logger.info("Sandbox configuration reset to defaults")
        return jsonify({
            'status': 'success',
            'message': 'Configuration reset to defaults successfully'
        })

    except Exception as e:
        logger.error(f"Error resetting sandbox config: {str(e)}\n{traceback.format_exc()}")
        return jsonify({
            'status': 'error',
            'message': f'Error resetting configuration: {str(e)}'
        }), 500

def validate_config(config_key, config_value):
    """Validate configuration values"""
    try:
        # Validate numeric values
        if config_key in ['starting_capital', 'equity_mis_leverage', 'equity_cnc_leverage',
                          'futures_leverage', 'option_buy_leverage', 'option_sell_leverage',
                          'order_check_interval', 'mtm_update_interval', 'order_rate_limit',
                          'api_rate_limit', 'smart_order_rate_limit', 'smart_order_delay']:
            try:
                value = float(config_value)
                if value < 0:
                    return f'{config_key} must be a positive number'

                # Additional validations
                if config_key == 'starting_capital' and value < 1000:
                    return 'Starting capital must be at least ₹1000'

                if config_key.endswith('_leverage') and value < 1:
                    return 'Leverage must be at least 1'

                if config_key.endswith('_interval') and value < 1:
                    return 'Interval must be at least 1 second'

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
