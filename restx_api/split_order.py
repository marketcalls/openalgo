from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from limiter import limiter
import os

from restx_api.schemas import SplitOrderSchema
from services.split_order_service import split_order, emit_analyzer_error
from database.apilog_db import async_log_order, executor as log_executor
from database.settings_db import get_analyze_mode
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('split_order', description='Split Order API')

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
split_schema = SplitOrderSchema()

@api.route('/', strict_slashes=False)
class SplitOrder(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Split a large order into multiple orders of specified size"""
        try:
            data = request.json

            # Validate and deserialize input
            try:
                split_data = split_schema.load(data)
            except ValidationError as err:
                error_message = str(err.messages)
                if get_analyze_mode():
                    return make_response(jsonify(emit_analyzer_error(data, error_message)), 400)
                error_response = {'status': 'error', 'message': error_message}
                log_executor.submit(async_log_order, 'splitorder', data, error_response)
                return make_response(jsonify(error_response), 400)

            # Extract API key
            api_key = split_data.pop('apikey', None)
            
            # Call the service function to split the order
            success, response_data, status_code = split_order(
                split_data=split_data,
                api_key=api_key
            )
            
            return make_response(jsonify(response_data), status_code)

        except Exception as e:
            logger.exception("An unexpected error occurred in SplitOrder endpoint.")
            error_message = 'An unexpected error occurred'
            if get_analyze_mode():
                return make_response(jsonify(emit_analyzer_error(data, error_message)), 500)
            error_response = {'status': 'error', 'message': error_message}
            log_executor.submit(async_log_order, 'splitorder', data, error_response)
            return make_response(jsonify(error_response), 500)
