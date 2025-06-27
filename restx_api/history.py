from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from limiter import limiter
import os
import traceback

from .data_schemas import HistorySchema
from services.history_service import get_history
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('history', description='Historical Data API')

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
history_schema = HistorySchema()

@api.route('/', strict_slashes=False)
class History(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get historical data for given symbol"""
        try:
            # Validate request data
            history_data = history_schema.load(request.json)

            api_key = history_data['apikey']
            symbol = history_data['symbol']
            exchange = history_data['exchange']
            interval = history_data['interval']
            start_date = history_data['start_date']
            end_date = history_data['end_date']
            
            # Call the service function to get historical data with API key
            success, response_data, status_code = get_history(
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                start_date=start_date,
                end_date=end_date,
                api_key=api_key
            )
            
            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            return make_response(jsonify({
                'status': 'error',
                'message': err.messages
            }), 400)
        except Exception as e:
            logger.exception(f"Unexpected error in history endpoint: {e}")
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)
