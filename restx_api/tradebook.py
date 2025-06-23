from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from limiter import limiter
import os
from .account_schema import TradebookSchema
from services.tradebook_service import get_tradebook
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('tradebook', description='Trade Book API')

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
tradebook_schema = TradebookSchema()

@api.route('/', strict_slashes=False)
class Tradebook(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get trade book details"""
        try:
            # Validate request data
            tradebook_data = tradebook_schema.load(request.json)

            api_key = tradebook_data['apikey']
            
            # Call the service function to get tradebook data with API key
            success, response_data, status_code = get_tradebook(api_key=api_key)
            
            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            return make_response(jsonify({
                'status': 'error',
                'message': err.messages
            }), 400)
        except Exception as e:
            logger.exception(f"Unexpected error in tradebook endpoint: {e}")
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)
