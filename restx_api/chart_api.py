from flask_restx import Namespace, Resource, fields
from flask import request
from database.chart_prefs_db import get_chart_prefs, update_chart_prefs
from utils.logging import get_logger

api = Namespace('chart', description='Chart Preferences and Cloud Workspace Sync')
logger = get_logger(__name__)

# Model for documentation
preference_model = api.model('ChartPreference', {
    'key': fields.String(required=True, description='Preference Key'),
    'value': fields.String(required=True, description='Preference Value (JSON string)')
})

@api.route('')
class ChartPreferencesResource(Resource):
    @api.doc('get_chart_preferences')
    @api.doc(params={'api_key': 'API Key'})
    def get(self):
        """Get all chart preferences for the authenticated user"""
        # Try to get API key from header first, then query param
        api_key = request.headers.get('X-API-KEY') or request.args.get('api_key')
        
        logger.info(f"[ChartAPI] GET request received. API Key present: {bool(api_key)}")
        
        if not api_key:
            logger.warning("[ChartAPI] GET: Missing API Key")
            return {'message': 'Missing API Key'}, 401
            
        prefs = get_chart_prefs(api_key)
        if prefs is None:
            logger.warning("[ChartAPI] GET: Invalid API Key or DB error")
            return {'message': 'Invalid API Key or Server Error'}, 401
        
        logger.debug(f"[ChartAPI] GET: Returning {len(prefs)} preferences")
        return prefs, 200

    @api.doc('update_chart_preferences')
    @api.expect(api.model('ChartPreferencesPayload', {}), validate=False)
    @api.doc(params={'api_key': 'API Key'})
    def post(self):
        """
        Update chart preferences.
        Accepts a JSON object where keys are preference keys and values are the values to save.
        """
        api_key = request.headers.get('X-API-KEY') or request.args.get('api_key')
        
        logger.info(f"[ChartAPI] POST request received. API Key present: {bool(api_key)}")
        
        if not api_key:
            logger.warning("[ChartAPI] POST: Missing API Key")
            return {'message': 'Missing API Key'}, 401

        data = request.json
        if not data:
            logger.warning("[ChartAPI] POST: No data provided")
            return {'message': 'No data provided'}, 400

        if not isinstance(data, dict):
            logger.warning(f"[ChartAPI] POST: Invalid data type: {type(data).__name__}, expected dict")
            return {'message': 'Invalid data format: expected JSON object'}, 400

        logger.info(f"[ChartAPI] POST: Saving {len(data)} preferences: {list(data.keys())}")
        
        success = update_chart_prefs(api_key, data)
        if success:
            logger.info("[ChartAPI] POST: Preferences saved successfully")
            return {'message': 'Preferences updated successfully'}, 200
        else:
            logger.error("[ChartAPI] POST: Failed to update preferences")
            return {'message': 'Failed to update preferences'}, 500
