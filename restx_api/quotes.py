from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from limiter import limiter
import os

from .data_schemas import QuotesSchema
from services.quotes_service import get_quotes
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('quotes', description='Real-time Quotes API')

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
quotes_schema = QuotesSchema()

@api.route('/', strict_slashes=False)
class Quotes(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get real-time quotes for given symbol"""
        try:
            # Validate request data
            quotes_data = quotes_schema.load(request.json)

            api_key = quotes_data['apikey']
            symbol = quotes_data['symbol']
            exchange = quotes_data['exchange']
            
            # Call the service function to get quotes data with API key
            success, response_data, status_code = get_quotes(
                symbol=symbol,
                exchange=exchange,
                api_key=api_key
            )
            
            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            return make_response(jsonify({
                'status': 'error',
                'message': err.messages
            }), 400)
        except Exception as e:
            logger.exception(f"Unexpected error in quotes endpoint: {e}")
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)
