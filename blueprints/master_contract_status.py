from flask import Blueprint, jsonify, session, request
from database.master_contract_status_db import get_status, check_if_ready
from utils.session import check_session_validity
from utils.logging import get_logger

logger = get_logger(__name__)

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

@master_contract_status_bp.route('/cache/status', methods=['GET'])
@check_session_validity
def get_cache_status():
    """Get the current symbol cache status and statistics"""
    try:
        from database.token_db_enhanced import get_cache_stats
        
        cache_info = get_cache_stats()
        return jsonify(cache_info), 200
        
    except ImportError:
        # Fallback if enhanced cache not available yet
        return jsonify({
            'status': 'not_available',
            'message': 'Enhanced cache module not available'
        }), 200
    except Exception as e:
        logger.error(f"Error getting cache status: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Failed to get cache status: {str(e)}'
        }), 500

@master_contract_status_bp.route('/cache/health', methods=['GET'])
@check_session_validity
def get_cache_health():
    """Get cache health metrics and recommendations"""
    try:
        from database.master_contract_cache_hook import get_cache_health
        
        health_info = get_cache_health()
        return jsonify(health_info), 200
        
    except ImportError:
        return jsonify({
            'health_score': 0,
            'status': 'not_available',
            'message': 'Cache health monitoring not available'
        }), 200
    except Exception as e:
        logger.error(f"Error getting cache health: {str(e)}")
        return jsonify({
            'health_score': 0,
            'status': 'error',
            'message': f'Failed to get cache health: {str(e)}'
        }), 500

@master_contract_status_bp.route('/cache/reload', methods=['POST'])
@check_session_validity
def reload_cache():
    """Manually trigger cache reload"""
    try:
        broker = session.get('broker')
        if not broker:
            return jsonify({
                'status': 'error',
                'message': 'No broker session found'
            }), 401
        
        from database.master_contract_cache_hook import load_symbols_to_cache
        
        success = load_symbols_to_cache(broker)
        
        if success:
            return jsonify({
                'status': 'success',
                'message': f'Cache reloaded successfully for broker: {broker}'
            }), 200
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to reload cache'
            }), 500
            
    except ImportError:
        return jsonify({
            'status': 'error',
            'message': 'Cache reload functionality not available'
        }), 501
    except Exception as e:
        logger.error(f"Error reloading cache: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Failed to reload cache: {str(e)}'
        }), 500

@master_contract_status_bp.route('/cache/clear', methods=['POST'])
@check_session_validity
def clear_cache():
    """Manually clear the cache"""
    try:
        from database.token_db_enhanced import clear_cache as clear_symbol_cache
        
        clear_symbol_cache()
        
        return jsonify({
            'status': 'success',
            'message': 'Cache cleared successfully'
        }), 200
        
    except ImportError:
        return jsonify({
            'status': 'error',
            'message': 'Cache clear functionality not available'
        }), 501
    except Exception as e:
        logger.error(f"Error clearing cache: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Failed to clear cache: {str(e)}'
        }), 500