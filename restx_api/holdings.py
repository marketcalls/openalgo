from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from limiter import limiter
import os
import traceback

from .account_schema import HoldingsSchema
from services.holdings_service import get_holdings
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('holdings', description='Holdings API')

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
holdings_schema = HoldingsSchema()

@api.route('/', strict_slashes=False)
class Holdings(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get holdings details"""
        try:
            # Validate request data
            holdings_data = holdings_schema.load(request.json)

            api_key = holdings_data['apikey']
            
            # Call the service function to get holdings data with API key
            success, response_data, status_code = get_holdings(api_key=api_key)
            
            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            return make_response(jsonify({
                'status': 'error',
                'message': err.messages
            }), 400)
        except Exception as e:
            logger.exception(f"Unexpected error in holdings endpoint: {e}")
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)
