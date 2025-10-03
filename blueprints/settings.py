# blueprints/settings.py

from flask import Blueprint, jsonify, request
from database.settings_db import get_analyze_mode, set_analyze_mode
from utils.session import check_session_validity
from utils.logging import get_logger
from sandbox.execution_thread import start_execution_engine, stop_execution_engine

logger = get_logger(__name__)

settings_bp = Blueprint('settings_bp', __name__, url_prefix='/settings')

@settings_bp.route('/analyze-mode')
@check_session_validity
def get_mode():
    """Get current analyze mode setting"""
    try:
        return jsonify({'analyze_mode': get_analyze_mode()})
    except Exception as e:
        logger.error(f"Error getting analyze mode: {str(e)}")
        return jsonify({'error': 'Failed to get analyze mode'}), 500

@settings_bp.route('/analyze-mode/<int:mode>', methods=['POST'])
@check_session_validity
def set_mode(mode):
    """Set analyze mode setting and manage execution engine thread"""
    try:
        set_analyze_mode(bool(mode))
        mode_name = 'Analyze' if mode else 'Live'

        # Start or stop execution engine based on mode
        if mode:
            # Starting Analyze mode - start execution engine
            success, message = start_execution_engine()
            if success:
                logger.info("Execution engine started for Analyze mode")
            else:
                logger.warning(f"Failed to start execution engine: {message}")
        else:
            # Switching to Live mode - stop execution engine
            success, message = stop_execution_engine()
            if success:
                logger.info("Execution engine stopped for Live mode")
            else:
                logger.warning(f"Failed to stop execution engine: {message}")

        return jsonify({
            'success': True,
            'analyze_mode': bool(mode),
            'message': f'Switched to {mode_name} Mode'
        })
    except Exception as e:
        logger.error(f"Error setting analyze mode: {str(e)}")
        return jsonify({'error': 'Failed to set analyze mode'}), 500
