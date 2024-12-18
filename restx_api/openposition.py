from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from database.auth_db import get_auth_token_broker
from database.apilog_db import async_log_order, executor as log_executor
from database.settings_db import get_analyze_mode
from database.analyzer_db import async_log_analyzer
from extensions import socketio
from limiter import limiter
import os
from dotenv import load_dotenv
import importlib
import traceback
import logging
import copy
import requests

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('openposition', description='Open Position API')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Marshmallow schema
from restx_api.account_schema import OpenPositionSchema, PositionbookSchema
openposition_schema = OpenPositionSchema()
positionbook_schema = PositionbookSchema()

def emit_analyzer_error(request_data, error_message):
    """Helper function to emit analyzer error events"""
    error_response = {
        'mode': 'analyze',
        'status': 'error',
        'message': error_message
    }
    
    # Store complete request data without apikey
    analyzer_request = request_data.copy()
    if 'apikey' in analyzer_request:
        del analyzer_request['apikey']
    analyzer_request['api_type'] = 'openposition'
    
    # Log to analyzer database
    log_executor.submit(async_log_analyzer, analyzer_request, error_response, 'openposition')
    
    # Emit socket event
    socketio.emit('analyzer_update', {
        'request': analyzer_request,
        'response': error_response
    })
    
    return error_response

@api.route('/', strict_slashes=False)
class OpenPosition(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get quantity of an open position"""
        try:
            data = request.json
            request_data = copy.deepcopy(data)
            request_data.pop('apikey', None)

            # Validate and deserialize input using OpenPositionSchema
            try:
                position_data = openposition_schema.load(data)
            except ValidationError as err:
                error_message = str(err.messages)
                if get_analyze_mode():
                    return make_response(jsonify(emit_analyzer_error(data, error_message)), 400)
                error_response = {'status': 'error', 'message': error_message}
                log_executor.submit(async_log_order, 'openposition', data, error_response)
                return make_response(jsonify(error_response), 400)

            # If in analyze mode, return simulated response
            if get_analyze_mode():
                response_data = {
                    'quantity': 0,
                    'status': 'success'
                }

                # Store complete request data without apikey
                analyzer_request = request_data.copy()
                analyzer_request['api_type'] = 'openposition'
                
                # Log to analyzer database
                log_executor.submit(async_log_analyzer, analyzer_request, response_data, 'openposition')
                
                # Emit socket event for toast notification
                socketio.emit('analyzer_update', {
                    'request': analyzer_request,
                    'response': response_data
                })
                
                return make_response(jsonify(response_data), 200)

            # Live mode - get position from positionbook
            try:
                # Prepare positionbook request with just apikey
                positionbook_request = {'apikey': position_data['apikey']}
                
                # Validate positionbook request
                try:
                    positionbook_data = positionbook_schema.load(positionbook_request)
                except ValidationError as err:
                    error_response = {
                        'status': 'error',
                        'message': 'Invalid positionbook request'
                    }
                    log_executor.submit(async_log_order, 'openposition', data, error_response)
                    return make_response(jsonify(error_response), 400)

                # Make request to positionbook API
                positionbook_response = requests.post('http://127.0.0.1:5000/api/v1/positionbook', json=positionbook_data)
                
                if positionbook_response.status_code != 200:
                    error_response = {
                        'status': 'error',
                        'message': 'Failed to fetch positionbook'
                    }
                    log_executor.submit(async_log_order, 'openposition', data, error_response)
                    return make_response(jsonify(error_response), positionbook_response.status_code)

                positionbook_data = positionbook_response.json()
                if positionbook_data.get('status') != 'success':
                    error_response = {
                        'status': 'error',
                        'message': positionbook_data.get('message', 'Error fetching positionbook')
                    }
                    log_executor.submit(async_log_order, 'openposition', data, error_response)
                    return make_response(jsonify(error_response), 500)

                # Find the specific position
                position_found = None
                for position in positionbook_data['data']:
                    if (position.get('symbol') == position_data['symbol'] and
                        position.get('exchange') == position_data['exchange'] and
                        position.get('product') == position_data['product']):
                        position_found = position
                        break

                # Return 0 quantity if position not found
                if not position_found:
                    response_data = {
                        'quantity': 0,
                        'status': 'success'
                    }
                    log_executor.submit(async_log_order, 'openposition', request_data, response_data)
                    return make_response(jsonify(response_data), 200)

                # Return the position quantity
                response_data = {
                    'quantity': position_found['quantity'],
                    'status': 'success'
                }
                log_executor.submit(async_log_order, 'openposition', request_data, response_data)

                return make_response(jsonify(response_data), 200)

            except Exception as e:
                logger.error(f"Error processing open position: {e}")
                traceback.print_exc()
                error_response = {
                    'status': 'error',
                    'message': str(e)
                }
                log_executor.submit(async_log_order, 'openposition', data, error_response)
                return make_response(jsonify(error_response), 500)

        except Exception as e:
            logger.error("An unexpected error occurred in OpenPosition endpoint.")
            traceback.print_exc()
            error_message = 'An unexpected error occurred'
            if get_analyze_mode():
                return make_response(jsonify(emit_analyzer_error(data, error_message)), 500)
            error_response = {'status': 'error', 'message': error_message}
            log_executor.submit(async_log_order, 'openposition', data, error_response)
            return make_response(jsonify(error_response), 500)
