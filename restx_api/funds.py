from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from database.auth_db import get_auth_token_broker
from limiter import limiter
import os
import traceback

from .account_schema import FundsSchema
from services.funds_service import get_funds
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('funds', description='Account Funds API')

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
funds_schema = FundsSchema()

@api.route('/', strict_slashes=False)
class Funds(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get account funds and margin details"""
        try:
            # Validate request data
            funds_data = funds_schema.load(request.json)

            api_key = funds_data['apikey']
            
            # Call the service function to get funds data with API key
            success, response_data, status_code = get_funds(api_key=api_key)
            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            return make_response(jsonify({
                'status': 'error',
                'message': err.messages
            }), 400)
        except Exception as e:
            logger.error(f"Unexpected error in funds endpoint: {e}")
            traceback.print_exc()
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)
