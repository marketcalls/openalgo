# Chart Preferences Service
# Business logic for chart preferences API

from typing import Dict, Any, Tuple
from database.chart_prefs_db import get_chart_prefs, update_chart_prefs
from database.auth_db import verify_api_key
from utils.logging import get_logger

logger = get_logger(__name__)


def get_chart_preferences(api_key: str) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get all chart preferences for the user associated with the API key.
    
    Args:
        api_key: OpenAlgo API key for authentication
        
    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    if not api_key:
        logger.warning("[ChartService] get_chart_preferences: Missing API Key")
        return False, {'status': 'error', 'message': 'Missing API Key'}, 401
    
    # Verify the API key first
    user_id = verify_api_key(api_key)
    if not user_id:
        logger.warning("[ChartService] get_chart_preferences: Invalid API Key")
        return False, {'status': 'error', 'message': 'Invalid openalgo apikey'}, 403
    
    prefs = get_chart_prefs(api_key)
    
    if prefs is None:
        logger.warning("[ChartService] get_chart_preferences: DB error")
        return False, {'status': 'error', 'message': 'Server Error'}, 500
    
    logger.debug(f"[ChartService] get_chart_preferences: Returning {len(prefs)} preferences")
    return True, {
        'status': 'success',
        'data': prefs
    }, 200


def update_chart_preferences(api_key: str, data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], int]:
    """
    Update chart preferences for the user associated with the API key.
    
    Args:
        api_key: OpenAlgo API key for authentication
        data: Dictionary of preference key-value pairs to update
        
    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    if not api_key:
        logger.warning("[ChartService] update_chart_preferences: Missing API Key")
        return False, {'status': 'error', 'message': 'Missing API Key'}, 401
    
    # Verify the API key first
    user_id = verify_api_key(api_key)
    if not user_id:
        logger.warning("[ChartService] update_chart_preferences: Invalid API Key")
        return False, {'status': 'error', 'message': 'Invalid openalgo apikey'}, 403
    
    if not data:
        logger.warning("[ChartService] update_chart_preferences: No data provided")
        return False, {'status': 'error', 'message': 'No data provided'}, 400
    
    if not isinstance(data, dict):
        logger.warning(f"[ChartService] update_chart_preferences: Invalid data type: {type(data).__name__}")
        return False, {'status': 'error', 'message': 'Invalid data format: expected JSON object'}, 400
    
    logger.info(f"[ChartService] update_chart_preferences: Saving {len(data)} preferences: {list(data.keys())}")
    
    success = update_chart_prefs(api_key, data)
    
    if success:
        logger.info("[ChartService] update_chart_preferences: Preferences saved successfully")
        return True, {
            'status': 'success',
            'message': 'Preferences updated successfully'
        }, 200
    else:
        logger.error("[ChartService] update_chart_preferences: Failed to update preferences")
        return False, {'status': 'error', 'message': 'Failed to update preferences'}, 500
