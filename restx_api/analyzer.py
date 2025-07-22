from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from limiter import limiter
import os
import traceback

from restx_api.account_schema import AnalyzerSchema, AnalyzerToggleSchema
from services.analyzer_service import get_analyzer_status, toggle_analyzer_mode
from database.apilog_db import async_log_order, executor as log_executor
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('analyzer', description='Analyzer Mode API')

# Initialize logger
logger = get_logger(__name__)

# Initialize schemas
analyzer_schema = AnalyzerSchema()
analyzer_toggle_schema = AnalyzerToggleSchema()

@api.route('/', strict_slashes=False)
class AnalyzerStatus(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get analyzer mode status and statistics"""
        try:
            data = request.json

            # Validate and deserialize input using AnalyzerSchema
            try:
                analyzer_data = analyzer_schema.load(data)
            except ValidationError as err:
                error_message = str(err.messages)
                error_response = {'status': 'error', 'message': error_message}
                log_executor.submit(async_log_order, 'analyzer_status', data, error_response)
                return make_response(jsonify(error_response), 400)

            # Extract API key
            api_key = analyzer_data.pop('apikey', None)
            
            # Call the service function to get analyzer status
            success, response_data, status_code = get_analyzer_status(
                analyzer_data=analyzer_data,
                api_key=api_key
            )
            
            return make_response(jsonify(response_data), status_code)

        except Exception as e:
            logger.exception("An unexpected error occurred in Analyzer status endpoint.")
            error_message = 'An unexpected error occurred'
            error_response = {'status': 'error', 'message': error_message}
            log_executor.submit(async_log_order, 'analyzer_status', data, error_response)
            return make_response(jsonify(error_response), 500)

@api.route('/toggle', strict_slashes=False)
class AnalyzerToggle(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Toggle analyzer mode on/off"""
        try:
            data = request.json

            # Validate and deserialize input using AnalyzerToggleSchema
            try:
                analyzer_data = analyzer_toggle_schema.load(data)
            except ValidationError as err:
                error_message = str(err.messages)
                error_response = {'status': 'error', 'message': error_message}
                log_executor.submit(async_log_order, 'analyzer_toggle', data, error_response)
                return make_response(jsonify(error_response), 400)

            # Extract API key
            api_key = analyzer_data.pop('apikey', None)
            
            # Call the service function to toggle analyzer mode
            success, response_data, status_code = toggle_analyzer_mode(
                analyzer_data=analyzer_data,
                api_key=api_key
            )
            
            return make_response(jsonify(response_data), status_code)

        except Exception as e:
            logger.exception("An unexpected error occurred in Analyzer toggle endpoint.")
            error_message = 'An unexpected error occurred'
            error_response = {'status': 'error', 'message': error_message}
            log_executor.submit(async_log_order, 'analyzer_toggle', data, error_response)
            return make_response(jsonify(error_response), 500)