from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from limiter import limiter
import os

from restx_api.schemas import SmartOrderSchema
from services.place_smart_order_service import place_smart_order, emit_analyzer_error
from database.apilog_db import async_log_order, executor
from database.settings_db import get_analyze_mode
from utils.logging import get_logger

SMART_ORDER_RATE_LIMIT = os.getenv("SMART_ORDER_RATE_LIMIT", "2 per second")
SMART_ORDER_DELAY = os.getenv("SMART_ORDER_DELAY", "0.5")
api = Namespace('place_smart_order', description='Place Smart Order API')

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
smart_order_schema = SmartOrderSchema()

@api.route('/', strict_slashes=False)
class SmartOrder(Resource):
    @limiter.limit(SMART_ORDER_RATE_LIMIT)
    def post(self):
        """Place a smart order"""
        try:
            data = request.json

            # Validate and deserialize input
            try:
                order_data = smart_order_schema.load(data)
            except ValidationError as err:
                error_message = str(err.messages)
                if get_analyze_mode():
                    return make_response(jsonify(emit_analyzer_error(data, error_message)), 400)
                error_response = {'status': 'error', 'message': error_message}
                executor.submit(async_log_order, 'placesmartorder', data, error_response)
                return make_response(jsonify(error_response), 400)

            # Extract API key
            api_key = order_data.pop('apikey', None)
            
            # Call the service function to place the smart order
            success, response_data, status_code = place_smart_order(
                order_data=order_data,
                api_key=api_key,
                smart_order_delay=SMART_ORDER_DELAY
            )
            
            return make_response(jsonify(response_data), status_code)

        except Exception as e:
            logger.exception("An unexpected error occurred in SmartOrder endpoint.")
            error_message = 'An unexpected error occurred'
            if get_analyze_mode():
                return make_response(jsonify(emit_analyzer_error(data, error_message)), 500)
            error_response = {'status': 'error', 'message': error_message}
            executor.submit(async_log_order, 'placesmartorder', data, error_response)
            return make_response(jsonify(error_response), 500)
