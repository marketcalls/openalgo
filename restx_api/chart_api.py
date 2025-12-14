from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from limiter import limiter
import os
import traceback

from .account_schema import ChartSchema
from services.chart_service import get_chart_preferences, update_chart_preferences
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('chart', description='Chart Preferences and Cloud Workspace Sync')

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
chart_schema = ChartSchema()

@api.route('', strict_slashes=False)
class ChartPreferencesResource(Resource):
    @limiter.limit(API_RATE_LIMIT)
    @api.doc(params={'apikey': 'API Key for authentication'})
    def get(self):
        """
        Get chart preferences.
        
        Pass apikey as query parameter: /api/v1/chart?apikey=your-api-key
        Returns all saved chart preferences for the user.
        """
        try:
            # Get apikey from query parameter
            api_key = request.args.get('apikey')
            
            if not api_key:
                return make_response(jsonify({
                    'status': 'error',
                    'message': 'Missing apikey parameter'
                }), 400)
            
            logger.info(f"[ChartAPI] GET preferences request. API Key present: {bool(api_key)}")
            success, response_data, status_code = get_chart_preferences(api_key)
            
            return make_response(jsonify(response_data), status_code)

        except Exception as e:
            logger.error(f"Unexpected error in chart GET endpoint: {e}")
            traceback.print_exc()
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)

    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """
        Update chart preferences.
        
        Send apikey and preferences in JSON body:
        {"apikey": "your-api-key", "tv_theme": "dark", "tv_chart_layout": "{...}"}
        """
        try:
            data = request.json
            if not data:
                return make_response(jsonify({
                    'status': 'error',
                    'message': 'No data provided'
                }), 400)
            
            # Validate that apikey is present
            chart_data = chart_schema.load(data)
            api_key = chart_data['apikey']
            
            # Extract preferences (all keys except apikey)
            preferences = {k: v for k, v in data.items() if k != 'apikey'}
            
            if not preferences:
                return make_response(jsonify({
                    'status': 'error',
                    'message': 'No preferences provided to update'
                }), 400)
            
            logger.info(f"[ChartAPI] POST update request. Keys: {list(preferences.keys())}")
            success, response_data, status_code = update_chart_preferences(api_key, preferences)
            
            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            return make_response(jsonify({
                'status': 'error',
                'message': err.messages
            }), 400)
        except Exception as e:
            logger.error(f"Unexpected error in chart POST endpoint: {e}")
            traceback.print_exc()
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)
