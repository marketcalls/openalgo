from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from limiter import limiter
import os

from .data_schemas import SymbolSchema
from services.symbol_service import get_symbol_info
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('symbol', description='Symbol information API')

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
symbol_schema = SymbolSchema()

@api.route('/', strict_slashes=False)
class Symbol(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get symbol information for a given symbol and exchange"""
        try:
            # Validate request data
            symbol_data = symbol_schema.load(request.json)

            # Extract parameters
            api_key = symbol_data.pop('apikey', None)
            symbol = symbol_data['symbol']
            exchange = symbol_data['exchange']
            
            # Call the service function to get symbol information
            success, response_data, status_code = get_symbol_info(
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
            logger.exception(f"Unexpected error in symbol endpoint: {e}")
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)
