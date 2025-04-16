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
import importlib
import traceback
import logging
import copy
import requests

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('orderstatus', description='Order Status API')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Marshmallow schema
from restx_api.account_schema import OrderStatusSchema, OrderbookSchema
orderstatus_schema = OrderStatusSchema()
orderbook_schema = OrderbookSchema()

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
    analyzer_request['api_type'] = 'orderstatus'
    
    # Log to analyzer database
    log_executor.submit(async_log_analyzer, analyzer_request, error_response, 'orderstatus')
    
    # Emit socket event
    socketio.emit('analyzer_update', {
        'request': analyzer_request,
        'response': error_response
    })
    
    return error_response

@api.route('/', strict_slashes=False)
class OrderStatus(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get status of a specific order"""
        try:
            data = request.json
            request_data = copy.deepcopy(data)
            request_data.pop('apikey', None)

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

            # If in analyze mode, return simulated response
            if get_analyze_mode():
                response_data = {
                    'mode': 'analyze',
                    'status': 'success',
                    'data': {
                        'action': 'BUY',
                        'exchange': 'NSE',
                        'order_status': 'COMPLETE',
                        'orderid': status_data['orderid'],
                        'price': 100.0,
                        'pricetype': 'MARKET',
                        'product': 'MIS',
                        'quantity': 10,
                        'symbol': 'SBIN',
                        'timestamp': '09-Dec-2024 10:00:00',
                        'trigger_price': 0
                    }
                }

                # Store complete request data without apikey
                analyzer_request = request_data.copy()
                analyzer_request['api_type'] = 'orderstatus'
                
                # Log to analyzer database
                log_executor.submit(async_log_analyzer, analyzer_request, response_data, 'orderstatus')
                
                # Emit socket event for toast notification
                socketio.emit('analyzer_update', {
                    'request': analyzer_request,
                    'response': response_data
                })
                
                return make_response(jsonify(response_data), 200)

            # Live mode - get order status from orderbook
            try:
                # Prepare orderbook request with just apikey
                orderbook_request = {'apikey': status_data['apikey']}
                
                # Validate orderbook request
                try:
                    orderbook_data = orderbook_schema.load(orderbook_request)
                except ValidationError as err:
                    error_response = {
                        'status': 'error',
                        'message': 'Invalid orderbook request'
                    }
                    log_executor.submit(async_log_order, 'orderstatus', data, error_response)
                    return make_response(jsonify(error_response), 400)

                # Make request to orderbook API
                orderbook_response = requests.post('http://127.0.0.1:5000/api/v1/orderbook', json=orderbook_data)
                
                if orderbook_response.status_code != 200:
                    error_response = {
                        'status': 'error',
                        'message': 'Failed to fetch orderbook'
                    }
                    log_executor.submit(async_log_order, 'orderstatus', data, error_response)
                    return make_response(jsonify(error_response), orderbook_response.status_code)

                orderbook_data = orderbook_response.json()
                if orderbook_data.get('status') != 'success':
                    error_response = {
                        'status': 'error',
                        'message': orderbook_data.get('message', 'Error fetching orderbook')
                    }
                    log_executor.submit(async_log_order, 'orderstatus', data, error_response)
                    return make_response(jsonify(error_response), 500)

                # Find the specific order in the orderbook
                order_found = None
                for order in orderbook_data['data']['orders']:
                    if str(order.get('orderid')) == str(status_data['orderid']):
                        order_found = order
                        break

                if not order_found:
                    error_response = {
                        'status': 'error',
                        'message': f'Order {status_data["orderid"]} not found'
                    }
                    log_executor.submit(async_log_order, 'orderstatus', data, error_response)
                    return make_response(jsonify(error_response), 404)

                # Return the found order
                response_data = {
                    'status': 'success',
                    'data': order_found
                }
                log_executor.submit(async_log_order, 'orderstatus', request_data, response_data)

                return make_response(jsonify(response_data), 200)

            except Exception as e:
                logger.error(f"Error processing order status: {e}")
                traceback.print_exc()
                error_response = {
                    'status': 'error',
                    'message': str(e)
                }
                log_executor.submit(async_log_order, 'orderstatus', data, error_response)
                return make_response(jsonify(error_response), 500)

        except Exception as e:
            logger.error("An unexpected error occurred in OrderStatus endpoint.")
            traceback.print_exc()
            error_message = 'An unexpected error occurred'
            if get_analyze_mode():
                return make_response(jsonify(emit_analyzer_error(data, error_message)), 500)
            error_response = {'status': 'error', 'message': error_message}
            log_executor.submit(async_log_order, 'orderstatus', data, error_response)
            return make_response(jsonify(error_response), 500)
