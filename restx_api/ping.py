from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from limiter import limiter
import os
import traceback

from .account_schema import PingSchema
from services.ping_service import get_ping
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('ping', description='Ping API to check connectivity and authentication')

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
ping_schema = PingSchema()

@api.route('/', strict_slashes=False)
class Ping(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Check API connectivity and authentication"""
        try:
            # Validate request data
            ping_data = ping_schema.load(request.json)

            api_key = ping_data['apikey']
            
            # Call the service function to get ping response with API key
            success, response_data, status_code = get_ping(api_key=api_key)
            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            return make_response(jsonify({
                'status': 'error',
                'message': err.messages
            }), 400)
        except Exception as e:
            logger.error(f"Unexpected error in ping endpoint: {e}")
            traceback.print_exc()
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)