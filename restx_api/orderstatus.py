from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from limiter import limiter
import os
import traceback

from restx_api.account_schema import OrderStatusSchema
from services.orderstatus_service import get_order_status, emit_analyzer_error
from database.apilog_db import async_log_order, executor as log_executor
from database.settings_db import get_analyze_mode
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('orderstatus', description='Order Status API')

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
orderstatus_schema = OrderStatusSchema()

@api.route('/', strict_slashes=False)
class OrderStatus(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get status of a specific order"""
        try:
            data = request.json

            # Validate and deserialize input using OrderStatusSchema
            try:
                status_data = orderstatus_schema.load(data)
            except ValidationError as err:
                error_message = str(err.messages)
                if get_analyze_mode():
                    return make_response(jsonify(emit_analyzer_error(data, error_message)), 400)
                error_response = {'status': 'error', 'message': error_message}
                log_executor.submit(async_log_order, 'orderstatus', data, error_response)
                return make_response(jsonify(error_response), 400)

            # Extract API key
            api_key = status_data.pop('apikey', None)
            
            # Call the service function to get the order status
            success, response_data, status_code = get_order_status(
                status_data=status_data,
                api_key=api_key
            )
            
            return make_response(jsonify(response_data), status_code)

        except Exception as e:
            logger.exception("An unexpected error occurred in OrderStatus endpoint.")
            error_message = 'An unexpected error occurred'
            if get_analyze_mode():
                return make_response(jsonify(emit_analyzer_error(data, error_message)), 500)
            error_response = {'status': 'error', 'message': error_message}
            log_executor.submit(async_log_order, 'orderstatus', data, error_response)
            return make_response(jsonify(error_response), 500)
