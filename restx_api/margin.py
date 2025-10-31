from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from limiter import limiter
import os

from services.margin_service import calculate_margin
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "50 per second")
api = Namespace('margin', description='Margin Calculator API')

# Initialize logger
logger = get_logger(__name__)

@api.route('/', strict_slashes=False)
class MarginCalculator(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Calculate margin requirement for a basket of positions"""
        try:
            # Get the request data
            data = request.json

            # Extract API key without removing it from the original data
            api_key = data.get('apikey', None)

            # Call the service function to calculate margin
            success, response_data, status_code = calculate_margin(
                margin_data=data,
                api_key=api_key
            )

            return make_response(jsonify(response_data), status_code)

        except Exception as e:
            logger.exception("An unexpected error occurred in Margin Calculator endpoint.")
            error_response = {
                'status': 'error',
                'message': 'An unexpected error occurred in the API endpoint'
            }
            return make_response(jsonify(error_response), 500)
