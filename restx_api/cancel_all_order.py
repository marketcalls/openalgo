from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from limiter import limiter
import os
import traceback

from restx_api.schemas import CancelAllOrderSchema
from services.cancel_all_order_service import cancel_all_orders, emit_analyzer_error
from database.apilog_db import async_log_order, executor
from database.settings_db import get_analyze_mode
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('cancel_all_order', description='Cancel All Orders API')

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
cancel_all_order_schema = CancelAllOrderSchema()

@api.route('/', strict_slashes=False)
class CancelAllOrder(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Cancel all open orders"""
        try:
            data = request.json
            
            # Validate and deserialize input
            try:
                order_data = cancel_all_order_schema.load(data)
            except ValidationError as err:
                error_message = str(err.messages)
                if get_analyze_mode():
                    return make_response(jsonify(emit_analyzer_error(data, error_message)), 400)
                error_response = {'status': 'error', 'message': error_message}
                executor.submit(async_log_order, 'cancelallorder', data, error_response)
                return make_response(jsonify(error_response), 400)

            # Extract API key
            api_key = order_data.pop('apikey', None)
            
            # Call the service function to cancel all orders
            success, response_data, status_code = cancel_all_orders(
                order_data=order_data,
                api_key=api_key
            )
            
            return make_response(jsonify(response_data), status_code)
            
        except KeyError as e:
            missing_field = str(e)
            logger.error(f"KeyError: Missing field {missing_field}")
            error_message = f"A required field is missing: {missing_field}"
            if get_analyze_mode():
                return make_response(jsonify(emit_analyzer_error(data, error_message)), 400)
            error_response = {'status': 'error', 'message': error_message}
            executor.submit(async_log_order, 'cancelallorder', data, error_response)
            return make_response(jsonify(error_response), 400)
            
        except Exception as e:
            logger.error("An unexpected error occurred in CancelAllOrder endpoint.")
            traceback.print_exc()
            error_message = 'An unexpected error occurred'
            if get_analyze_mode():
                return make_response(jsonify(emit_analyzer_error(data, error_message)), 500)
            error_response = {'status': 'error', 'message': error_message}
            executor.submit(async_log_order, 'cancelallorder', data, error_response)
            return make_response(jsonify(error_response), 500)
