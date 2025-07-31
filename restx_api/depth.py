from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from limiter import limiter
import os
import traceback

from .data_schemas import DepthSchema
from services.depth_service import get_depth
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('depth', description='Market Depth API')

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
depth_schema = DepthSchema()

@api.route('/', strict_slashes=False)
class Depth(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get market depth for given symbol"""
        try:
            # Validate request data
            depth_data = depth_schema.load(request.json)

            api_key = depth_data['apikey']
            symbol = depth_data['symbol']
            exchange = depth_data['exchange']
            
            # Call the service function to get depth data with API key
            success, response_data, status_code = get_depth(
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
            logger.error(f"Unexpected error in depth endpoint: {e}")
            traceback.print_exc()
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)
