from flask_restx import Namespace, Resource, fields
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from database.auth_db import get_auth_token_broker
from database.apilog_db import async_log_order, executor
from database.settings_db import get_analyze_mode
from database.analyzer_db import async_log_analyzer
from extensions import socketio
from limiter import limiter
from utils.api_analyzer import analyze_request
import os
from dotenv import load_dotenv
import importlib
import logging
import traceback
import copy

load_dotenv()

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('close_position', description='Close Position API')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Marshmallow schema
from restx_api.schemas import ClosePositionSchema
close_position_schema = ClosePositionSchema()

def import_broker_module(broker_name):
    try:
        module_path = f'broker.{broker_name}.api.order_api'
        broker_module = importlib.import_module(module_path)
        return broker_module
    except ImportError as error:
        logger.error(f"Error importing broker module '{module_path}': {error}")
        return None

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
    analyzer_request['api_type'] = 'closeposition'
    
    # Log to analyzer database
    executor.submit(async_log_analyzer, analyzer_request, error_response, 'closeposition')
    
    # Emit socket event
    socketio.emit('analyzer_update', {
        'request': analyzer_request,
        'response': error_response
    })
    
    return error_response

@api.route('/', strict_slashes=False)
class ClosePosition(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        try:
            data = request.json
            position_request_data = copy.deepcopy(data)
            position_request_data.pop('apikey', None)
            
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

            api_key = position_data['apikey']
            AUTH_TOKEN, broker = get_auth_token_broker(api_key)
            if AUTH_TOKEN is None:
                error_response = {
                    'status': 'error',
                    'message': 'Invalid openalgo apikey'
                }
                if not get_analyze_mode():
                    executor.submit(async_log_order, 'closeposition', data, error_response)
                return make_response(jsonify(error_response), 403)

            # If in analyze mode, analyze the request and return
            if get_analyze_mode():
                _, analysis = analyze_request(position_data, 'closeposition', True)
                
                # Store complete request data without apikey
                analyzer_request = position_request_data.copy()
                analyzer_request['api_type'] = 'closeposition'
                
                if analysis.get('status') == 'success':
                    response_data = {
                        'mode': 'analyze',
                        'status': 'success',
                        'message': 'All Open Positions will be Squared Off'
                    }
                else:
                    response_data = {
                        'mode': 'analyze',
                        'status': 'error',
                        'message': analysis.get('message', 'Analysis failed')
                    }
                
                # Log to analyzer database with complete request and response
                executor.submit(async_log_analyzer, analyzer_request, response_data, 'closeposition')
                
                # Emit socket event for toast notification
                socketio.emit('analyzer_update', {
                    'request': analyzer_request,
                    'response': response_data
                })
                
                return make_response(jsonify(response_data), 200)

            broker_module = import_broker_module(broker)
            if broker_module is None:
                error_response = {
                    'status': 'error',
                    'message': 'Broker-specific module not found'
                }
                executor.submit(async_log_order, 'closeposition', data, error_response)
                return make_response(jsonify(error_response), 404)

            try:
                # Use the dynamically imported module's function to close all positions
                response_code, status_code = broker_module.close_all_positions(api_key, AUTH_TOKEN)
            except Exception as e:
                logger.error(f"Error in broker_module.close_all_positions: {e}")
                traceback.print_exc()
                error_response = {
                    'status': 'error',
                    'message': 'Failed to close positions due to internal error'
                }
                executor.submit(async_log_order, 'closeposition', data, error_response)
                return make_response(jsonify(error_response), 500)

            if status_code == 200:
                response_data = {
                    'status': 'success',
                    'message': 'All Open Positions Squared Off'
                }
                socketio.emit('close_position_event', {
                    'status': 'success',
                    'message': 'All Open Positions Squared Off',
                    'mode': 'live'
                })
                executor.submit(async_log_order, 'closeposition', position_request_data, response_data)
                return make_response(jsonify(response_data), 200)
            else:
                message = response_code.get('message', 'Failed to close positions') if isinstance(response_code, dict) else 'Failed to close positions'
                error_response = {
                    'status': 'error',
                    'message': message
                }
                executor.submit(async_log_order, 'closeposition', data, error_response)
                return make_response(jsonify(error_response), status_code)

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
