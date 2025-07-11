from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from limiter import limiter
import os

from .data_schemas import SearchSchema
from services.search_service import search_symbols
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('search', description='Symbol search API')

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
search_schema = SearchSchema()

@api.route('/', strict_slashes=False)
class Search(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Search for symbols in the database"""
        try:
            # Validate request data
            search_data = search_schema.load(request.json)

            # Extract parameters
            api_key = search_data.pop('apikey', None)
            query = search_data['query']
            exchange = search_data.get('exchange')
            
            # Call the service function to search symbols
            success, response_data, status_code = search_symbols(
                query=query,
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
            logger.exception(f"Unexpected error in search endpoint: {e}")
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)