from flask_restx import Namespace, Resource, fields
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from database.auth_db import get_auth_token_broker
from database.apilog_db import async_log_order, executor
from database.settings_db import get_analyze_mode
from database.analyzer_db import async_log_analyzer
from extensions import socketio
from limiter import limiter
import os
from dotenv import load_dotenv
import importlib
import logging
import traceback
import copy

load_dotenv()

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('cancel_order', description='Cancel Order API')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Marshmallow schema
from restx_api.schemas import CancelOrderSchema
cancel_order_schema = CancelOrderSchema()

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
    
    analyzer_request = {
        'api_type': 'cancelorder',
        'strategy': request_data.get('strategy', 'Unknown'),
        'orderid': request_data.get('orderid')
    }
    
    # Log to analyzer database
    executor.submit(async_log_analyzer, analyzer_request, error_response, 'cancelorder')
    
    # Emit socket event
    socketio.emit('analyzer_update', {
        'request': analyzer_request,
        'response': error_response
    })
    
    return error_response

@api.route('/', strict_slashes=False)
class CancelOrder(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        try:
            data = request.json
            
            # Validate and deserialize input
            try:
                order_data = cancel_order_schema.load(data)
            except ValidationError as err:
                error_message = str(err.messages)
                if get_analyze_mode():
                    return make_response(jsonify(emit_analyzer_error(data, error_message)), 400)
                error_response = {'status': 'error', 'message': error_message}
                executor.submit(async_log_order, 'cancelorder', data, error_response)
                return make_response(jsonify(error_response), 400)

            api_key = order_data['apikey']
            AUTH_TOKEN, broker = get_auth_token_broker(api_key)
            if AUTH_TOKEN is None:
                error_response = {
                    'status': 'error',
                    'message': 'Invalid openalgo apikey'
                }
                if not get_analyze_mode():
                    executor.submit(async_log_order, 'cancelorder', data, error_response)
                return make_response(jsonify(error_response), 403)

            # Extract the order ID from order_data
            orderid = order_data.get('orderid')
            if not orderid:
                error_message = 'Order ID is missing'
                if get_analyze_mode():
                    return make_response(jsonify(emit_analyzer_error(data, error_message)), 400)
                error_response = {'status': 'error', 'message': error_message}
                executor.submit(async_log_order, 'cancelorder', data, error_response)
                return make_response(jsonify(error_response), 400)

            # If in analyze mode, return success response
            if get_analyze_mode():
                response_data = {
                    'mode': 'analyze',
                    'orderid': orderid,
                    'status': 'success'
                }
                
                # Format request data for analyzer log
                analyzer_request = {
                    'api_type': 'cancelorder',
                    'strategy': order_data.get('strategy', 'Unknown'),
                    'orderid': orderid
                }
                
                # Log to analyzer database
                executor.submit(async_log_analyzer, analyzer_request, response_data, 'cancelorder')
                
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
                executor.submit(async_log_order, 'cancelorder', data, error_response)
                return make_response(jsonify(error_response), 404)

            try:
                # Use the dynamically imported module's function to cancel the order
                response_message, status_code = broker_module.cancel_order(orderid, AUTH_TOKEN)
            except Exception as e:
                logger.error(f"Error in broker_module.cancel_order: {e}")
                traceback.print_exc()
                error_response = {
                    'status': 'error',
                    'message': 'Failed to cancel order due to internal error'
                }
                executor.submit(async_log_order, 'cancelorder', data, error_response)
                return make_response(jsonify(error_response), 500)

            if status_code == 200:
                socketio.emit('cancel_order_event', {
                    'status': response_message.get('status'),
                    'orderid': orderid,
                    'mode': 'live'
                })
                order_response_data = {
                    'status': 'success',
                    'orderid': orderid
                }
                executor.submit(async_log_order, 'cancelorder', order_data, order_response_data)
                return make_response(jsonify(order_response_data), 200)
            else:
                message = response_message.get('message', 'Failed to cancel order') if isinstance(response_message, dict) else 'Failed to cancel order'
                error_response = {
                    'status': 'error',
                    'message': message
                }
                executor.submit(async_log_order, 'cancelorder', data, error_response)
                return make_response(jsonify(error_response), status_code)

        except KeyError as e:
            missing_field = str(e)
            logger.error(f"KeyError: Missing field {missing_field}")
            error_message = f"A required field is missing: {missing_field}"
            if get_analyze_mode():
                return make_response(jsonify(emit_analyzer_error(data, error_message)), 400)
            error_response = {'status': 'error', 'message': error_message}
            executor.submit(async_log_order, 'cancelorder', data, error_response)
            return make_response(jsonify(error_response), 400)

        except Exception as e:
            logger.error("An unexpected error occurred in CancelOrder endpoint.")
            traceback.print_exc()
            error_message = 'An unexpected error occurred'
            if get_analyze_mode():
                return make_response(jsonify(emit_analyzer_error(data, error_message)), 500)
            error_response = {'status': 'error', 'message': error_message}
            executor.submit(async_log_order, 'cancelorder', data, error_response)
            return make_response(jsonify(error_response), 500)
