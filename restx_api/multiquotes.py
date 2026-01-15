from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from limiter import limiter
import os

from .data_schemas import MultiQuotesSchema
from services.quotes_service import get_multiquotes
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('multiquotes', description='Real-time Multiple Quotes API')

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
multiquotes_schema = MultiQuotesSchema()

@api.route('/', strict_slashes=False)
class MultiQuotes(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get real-time quotes for multiple symbols"""
        try:
            # Validate request data
            multiquotes_data = multiquotes_schema.load(request.json)

            api_key = multiquotes_data['apikey']
            symbols = multiquotes_data['symbols']

            # Call the service function to get multiquotes data with API key
            success, response_data, status_code = get_multiquotes(
                symbols=symbols,
                api_key=api_key
            )

            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            return make_response(jsonify({
                'status': 'error',
                'message': err.messages
            }), 400)
        except Exception as e:
            logger.exception(f"Unexpected error in multiquotes endpoint: {e}")
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)
