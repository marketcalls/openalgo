from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from limiter import limiter
import os
import traceback
import copy

from restx_api.schemas import BasketOrderSchema
from services.basket_order_service import place_basket_order
from database.apilog_db import async_log_order, executor as log_executor
from database.settings_db import get_analyze_mode
from services.basket_order_service import emit_analyzer_error
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('basket_order', description='Basket Order API')

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
basket_schema = BasketOrderSchema()

@api.route('/', strict_slashes=False)
class BasketOrder(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Place multiple orders in a basket"""
        try:
            data = request.json
            
            # Validate and deserialize input
            try:
                basket_data = basket_schema.load(data)
            except ValidationError as err:
                error_message = str(err.messages)
                if get_analyze_mode():
                    return make_response(jsonify(emit_analyzer_error(data, error_message)), 400)
                error_response = {'status': 'error', 'message': error_message}
                log_executor.submit(async_log_order, 'basketorder', data, error_response)
                return make_response(jsonify(error_response), 400)

            # Extract API key
            api_key = basket_data.pop('apikey', None)
            
            # Call the service function to place the basket order
            success, response_data, status_code = place_basket_order(
                basket_data=basket_data,
                api_key=api_key
            )
            
            return make_response(jsonify(response_data), status_code)
            
        except Exception as e:
            logger.error("An unexpected error occurred in BasketOrder endpoint.")
            traceback.print_exc()
            error_message = 'An unexpected error occurred'
            if get_analyze_mode():
                return make_response(jsonify(emit_analyzer_error(data, error_message)), 500)
            error_response = {'status': 'error', 'message': error_message}
            log_executor.submit(async_log_order, 'basketorder', data, error_response)
            return make_response(jsonify(error_response), 500)
