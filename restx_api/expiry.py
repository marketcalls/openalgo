from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from limiter import limiter
import os

from .data_schemas import ExpirySchema
from services.expiry_service import get_expiry_dates
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('expiry', description='Expiry dates API for F&O instruments')

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
expiry_schema = ExpirySchema()

@api.route('/', strict_slashes=False)
class Expiry(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get expiry dates for F&O symbols (futures or options) for a given underlying symbol"""
        try:
            # Validate request data
            expiry_data = expiry_schema.load(request.json)

            # Extract parameters
            api_key = expiry_data.pop('apikey', None)
            symbol = expiry_data['symbol']
            exchange = expiry_data['exchange']
            instrumenttype = expiry_data['instrumenttype']
            
            # Call the service function to get expiry dates
            success, response_data, status_code = get_expiry_dates(
                symbol=symbol,
                exchange=exchange,
                instrumenttype=instrumenttype,
                api_key=api_key
            )
            
            return make_response(jsonify(response_data), status_code)
                
        except ValidationError as err:
            return make_response(jsonify({
                'status': 'error',
                'message': err.messages
            }), 400)
            
        except Exception as e:
            logger.exception(f"Unexpected error in expiry endpoint: {e}")
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)