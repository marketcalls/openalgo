from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from limiter import limiter
import os
import logging
import traceback

from .data_schemas import IntervalsSchema
from services.intervals_service import get_intervals

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('intervals', description='Supported Intervals API')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize schema
intervals_schema = IntervalsSchema()

@api.route('/', strict_slashes=False)
class Intervals(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get supported intervals for the broker"""
        try:
            # Validate request data
            intervals_data = intervals_schema.load(request.json)

            api_key = intervals_data['apikey']
            
            # Call the service function to get intervals data with API key
            success, response_data, status_code = get_intervals(api_key=api_key)
            
            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            return make_response(jsonify({
                'status': 'error',
                'message': err.messages
            }), 400)
        except Exception as e:
            logger.error(f"Unexpected error in intervals endpoint: {e}")
            traceback.print_exc()
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)
