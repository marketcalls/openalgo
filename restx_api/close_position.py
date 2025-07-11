from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from limiter import limiter
import os
import traceback

from restx_api.schemas import ClosePositionSchema
from services.close_position_service import close_position, emit_analyzer_error
from database.apilog_db import async_log_order, executor
from database.settings_db import get_analyze_mode
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('close_position', description='Close Position API')

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
close_position_schema = ClosePositionSchema()

@api.route('/', strict_slashes=False)
class ClosePosition(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Close all open positions"""
        try:
            data = request.json
            
            # Validate and deserialize input
            try:
                position_data = close_position_schema.load(data)
            except ValidationError as err:
                error_message = str(err.messages)
                if get_analyze_mode():
                    return make_response(jsonify(emit_analyzer_error(data, error_message)), 400)
                error_response = {'status': 'error', 'message': error_message}
                executor.submit(async_log_order, 'closeposition', data, error_response)
                return make_response(jsonify(error_response), 400)

            # Extract API key
            api_key = position_data.pop('apikey', None)
            
            # Call the service function to close all positions
            success, response_data, status_code = close_position(
                position_data=position_data,
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
            executor.submit(async_log_order, 'closeposition', data, error_response)
            return make_response(jsonify(error_response), 400)
            
        except Exception as e:
            logger.error("An unexpected error occurred in ClosePosition endpoint.")
            traceback.print_exc()
            error_message = 'An unexpected error occurred'
            if get_analyze_mode():
                return make_response(jsonify(emit_analyzer_error(data, error_message)), 500)
            error_response = {'status': 'error', 'message': error_message}
            executor.submit(async_log_order, 'closeposition', data, error_response)
            return make_response(jsonify(error_response), 500)
