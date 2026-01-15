from flask_restx import Namespace, Resource, fields
from flask import request, jsonify, make_response
from limiter import limiter
import os

from services.place_order_service import place_order
from utils.logging import get_logger

ORDER_RATE_LIMIT = os.getenv("ORDER_RATE_LIMIT", "10 per second")
api = Namespace('place_order', description='Place Order API')

# Initialize logger
logger = get_logger(__name__)

# All functionality moved to place_order_service.py

@api.route('/', strict_slashes=False)
class PlaceOrder(Resource):
    @limiter.limit(ORDER_RATE_LIMIT)
    def post(self):
        """Place an order with the broker"""
        try:
            # Get the request data
            data = request.json
            
            # Extract API key without removing it from the original data
            api_key = data.get('apikey', None)
            
            # Call the service function to place the order
            success, response_data, status_code = place_order(
                order_data=data,
                api_key=api_key
            )
            
            return make_response(jsonify(response_data), status_code)
            
        except Exception as e:
            logger.exception("An unexpected error occurred in PlaceOrder endpoint.")
            error_response = {
                'status': 'error',
                'message': 'An unexpected error occurred in the API endpoint'
            }
            return make_response(jsonify(error_response), 500)
