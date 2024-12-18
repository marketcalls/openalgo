from flask_restx import Namespace, Resource, fields
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from database.auth_db import get_auth_token_broker
from database.apilog_db import async_log_order, executor
from database.settings_db import get_analyze_mode
from database.analyzer_db import async_log_analyzer
from extensions import socketio
from limiter import limiter
from utils.api_analyzer import analyze_request, generate_order_id
import os
import importlib
import logging
import traceback
import copy

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('cancel_all_order', description='Cancel All Orders API')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Marshmallow schema
from restx_api.schemas import CancelAllOrderSchema
cancel_all_order_schema = CancelAllOrderSchema()

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
    analyzer_request['api_type'] = 'cancelallorder'
    
    # Log to analyzer database
    executor.submit(async_log_analyzer, analyzer_request, error_response, 'cancelallorder')
    
    # Emit socket event
    socketio.emit('analyzer_update', {
        'request': analyzer_request,
        'response': error_response
    })
    
    return error_response

@api.route('/', strict_slashes=False)
class CancelAllOrder(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        try:
            data = request.json
            order_request_data = copy.deepcopy(data)
            order_request_data.pop('apikey', None)
            
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

            api_key = order_data['apikey']
            AUTH_TOKEN, broker = get_auth_token_broker(api_key)
            if AUTH_TOKEN is None:
                error_response = {
                    'status': 'error',
                    'message': 'Invalid openalgo apikey'
                }
                if not get_analyze_mode():
                    executor.submit(async_log_order, 'cancelallorder', data, error_response)
                return make_response(jsonify(error_response), 403)

            # If in analyze mode, analyze the request and return
            if get_analyze_mode():
                _, analysis = analyze_request(order_data, 'cancelallorder', True)
                
                # Store complete request data without apikey
                analyzer_request = order_request_data.copy()
                analyzer_request['api_type'] = 'cancelallorder'
                
                if analysis.get('status') == 'success':
                    response_data = {
                        'mode': 'analyze',
                        'status': 'success',
                        'message': 'All open orders will be cancelled',
                        'canceled_orders': [],
                        'failed_cancellations': []
                    }
                else:
                    response_data = {
                        'mode': 'analyze',
                        'status': 'error',
                        'message': analysis.get('message', 'Analysis failed')
                    }
                
                # Log to analyzer database with complete request and response
                executor.submit(async_log_analyzer, analyzer_request, response_data, 'cancelallorder')
                
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
                executor.submit(async_log_order, 'cancelallorder', data, error_response)
                return make_response(jsonify(error_response), 404)

            try:
                # Use the dynamically imported module's function to cancel all orders
                canceled_orders, failed_cancellations = broker_module.cancel_all_orders_api(order_data, AUTH_TOKEN)
            except Exception as e:
                logger.error(f"Error in broker_module.cancel_all_orders_api: {e}")
                traceback.print_exc()
                error_response = {
                    'status': 'error',
                    'message': 'Failed to cancel all orders due to internal error'
                }
                executor.submit(async_log_order, 'cancelallorder', data, error_response)
                return make_response(jsonify(error_response), 500)

            # Emit events for each canceled order
            for orderid in canceled_orders:
                socketio.emit('cancel_order_event', {
                    'status': 'success', 
                    'orderid': orderid,
                    'mode': 'live'
                })

            # Prepare response data
            response_data = {
                'status': 'success',
                'canceled_orders': canceled_orders,
                'failed_cancellations': failed_cancellations,
                'message': f'Canceled {len(canceled_orders)} orders. Failed to cancel {len(failed_cancellations)} orders.'
            }

            # Log the action asynchronously
            executor.submit(async_log_order, 'cancelallorder', order_request_data, response_data)

            return make_response(jsonify(response_data), 200)

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
