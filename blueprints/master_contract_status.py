from flask import Blueprint, jsonify, session
from database.master_contract_status_db import get_status, check_if_ready
from utils.session import check_session_validity
import logging

logger = logging.getLogger(__name__)

master_contract_status_bp = Blueprint('master_contract_status_bp', __name__, url_prefix='/api')

@master_contract_status_bp.route('/master-contract/status', methods=['GET'])
@check_session_validity
def get_master_contract_status():
    """Get the current master contract download status"""
    try:
        broker = session.get('broker')
        if not broker:
            return jsonify({
                'status': 'error',
                'message': 'No broker session found'
            }), 401
            
        status_data = get_status(broker)
        return jsonify(status_data), 200
        
    except Exception as e:
        logger.error(f"Error getting master contract status: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to get master contract status'
        }), 500

@master_contract_status_bp.route('/master-contract/ready', methods=['GET'])
@check_session_validity
def check_master_contract_ready():
    """Check if master contracts are ready for trading"""
    try:
        broker = session.get('broker')
        if not broker:
            return jsonify({
                'ready': False,
                'message': 'No broker session found'
            }), 401
            
        is_ready = check_if_ready(broker)
        return jsonify({
            'ready': is_ready,
            'message': 'Master contracts are ready' if is_ready else 'Master contracts not ready'
        }), 200
        
    except Exception as e:
        logger.error(f"Error checking master contract readiness: {str(e)}")
        return jsonify({
            'ready': False,
            'message': 'Failed to check master contract readiness'
        }), 500