from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from limiter import limiter
import os

from .account_schema import PositionbookSchema
from services.positionbook_service import get_positionbook
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('positionbook', description='Position Book API')

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
positionbook_schema = PositionbookSchema()

@api.route('/', strict_slashes=False)
class Positionbook(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get position book details"""
        try:
            # Validate request data
            positionbook_data = positionbook_schema.load(request.json)

            api_key = positionbook_data['apikey']
            
            # Call the service function to get positionbook data with API key
            success, response_data, status_code = get_positionbook(api_key=api_key)
            
            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            return make_response(jsonify({
                'status': 'error',
                'message': err.messages
            }), 400)
        except Exception as e:
            logger.exception(f"Unexpected error in positionbook endpoint: {e}")
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)
