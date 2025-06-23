from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from limiter import limiter
import os
import traceback

from .account_schema import OrderbookSchema
from services.orderbook_service import get_orderbook
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('orderbook', description='Order Book API')

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
orderbook_schema = OrderbookSchema()

@api.route('/', strict_slashes=False)
class Orderbook(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get order book details"""
        try:
            # Validate request data
            orderbook_data = orderbook_schema.load(request.json)

            api_key = orderbook_data['apikey']
            
            # Call the service function to get orderbook data with API key
            success, response_data, status_code = get_orderbook(api_key=api_key)
            
            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            return make_response(jsonify({
                'status': 'error',
                'message': err.messages
            }), 400)
        except Exception as e:
            logger.exception(f"Unexpected error in orderbook endpoint: {e}")
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)
