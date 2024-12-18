from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from database.auth_db import get_auth_token_broker
from database.apilog_db import async_log_order, executor as log_executor
from database.settings_db import get_analyze_mode
from database.analyzer_db import async_log_analyzer
from extensions import socketio
from limiter import limiter
from utils.api_analyzer import analyze_request, generate_order_id
from utils.constants import (
    VALID_EXCHANGES,
    VALID_ACTIONS,
    VALID_PRICE_TYPES,
    VALID_PRODUCT_TYPES,
    REQUIRED_ORDER_FIELDS
)
import os
import importlib
import traceback
import logging
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('split_order', description='Split Order API')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Marshmallow schema
from restx_api.schemas import SplitOrderSchema
split_schema = SplitOrderSchema()

MAX_ORDERS = 100  # Maximum number of orders allowed

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
    analyzer_request['api_type'] = 'splitorder'
    
    # Log to analyzer database
    log_executor.submit(async_log_analyzer, analyzer_request, error_response, 'splitorder')
    
    # Emit socket event
    socketio.emit('analyzer_update', {
        'request': analyzer_request,
        'response': error_response
    })
    
    return error_response

def import_broker_module(broker_name):
    try:
        module_path = f'broker.{broker_name}.api.order_api'
        broker_module = importlib.import_module(module_path)
        return broker_module
    except ImportError as error:
        logger.error(f"Error importing broker module '{module_path}': {error}")
        return None

def place_single_order(order_data, broker_module, AUTH_TOKEN, order_num, total_orders):
    """Place a single order and emit event"""
    try:
        # Place the order using place_order_api
        res, response_data, order_id = broker_module.place_order_api(order_data, AUTH_TOKEN)

        if res.status == 200:
            # Emit order event for toast notification with batch info
            socketio.emit('order_event', {
                'symbol': order_data['symbol'],
                'action': order_data['action'],
                'orderid': order_id,
                'exchange': order_data.get('exchange', 'Unknown'),
                'price_type': order_data.get('pricetype', 'Unknown'),
                'product_type': order_data.get('product', 'Unknown'),
                'mode': 'live',
                'order_num': order_num,
                'quantity': int(order_data['quantity']),
                'batch_order': True,
                'is_last_order': order_num == total_orders
            })

            # Return response without batch info
            return {
                'order_num': order_num,
                'quantity': int(order_data['quantity']),
                'status': 'success',
                'orderid': order_id
            }
        else:
            message = response_data.get('message', 'Failed to place order') if isinstance(response_data, dict) else 'Failed to place order'
            return {
                'order_num': order_num,
                'quantity': int(order_data['quantity']),
                'status': 'error',
                'message': message
            }

    except Exception as e:
        logger.error(f"Error placing order {order_num}: {e}")
        return {
            'order_num': order_num,
            'quantity': int(order_data['quantity']),
            'status': 'error',
            'message': 'Failed to place order due to internal error'
        }

@api.route('/', strict_slashes=False)
class SplitOrder(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Split a large order into multiple orders of specified size"""
        try:
            data = request.json
            split_request_data = copy.deepcopy(data)
            split_request_data.pop('apikey', None)

            # Validate and deserialize input
            try:
                split_data = split_schema.load(data)
            except ValidationError as err:
                error_message = str(err.messages)
                if get_analyze_mode():
                    return make_response(jsonify(emit_analyzer_error(data, error_message)), 400)
                error_response = {'status': 'error', 'message': error_message}
                log_executor.submit(async_log_order, 'splitorder', data, error_response)
                return make_response(jsonify(error_response), 400)

            # Validate quantities
            try:
                split_size = int(split_data['splitsize'])
                total_quantity = int(split_data['quantity'])
                if split_size <= 0:
                    error_message = 'Split size must be greater than 0'
                    if get_analyze_mode():
                        return make_response(jsonify(emit_analyzer_error(data, error_message)), 400)
                    error_response = {'status': 'error', 'message': error_message}
                    log_executor.submit(async_log_order, 'splitorder', data, error_response)
                    return make_response(jsonify(error_response), 400)

                # Calculate number of full-size orders and remaining quantity
                num_full_orders = total_quantity // split_size
                remaining_qty = total_quantity % split_size

                # Check if total number of orders exceeds limit
                total_orders = num_full_orders + (1 if remaining_qty > 0 else 0)
                if total_orders > MAX_ORDERS:
                    error_message = f'Total number of orders would exceed maximum limit of {MAX_ORDERS}'
                    if get_analyze_mode():
                        return make_response(jsonify(emit_analyzer_error(data, error_message)), 400)
                    error_response = {'status': 'error', 'message': error_message}
                    log_executor.submit(async_log_order, 'splitorder', data, error_response)
                    return make_response(jsonify(error_response), 400)

            except ValueError:
                error_message = 'Invalid quantity or split size'
                if get_analyze_mode():
                    return make_response(jsonify(emit_analyzer_error(data, error_message)), 400)
                error_response = {'status': 'error', 'message': error_message}
                log_executor.submit(async_log_order, 'splitorder', data, error_response)
                return make_response(jsonify(error_response), 400)

            api_key = split_data['apikey']
            AUTH_TOKEN, broker = get_auth_token_broker(api_key)
            if AUTH_TOKEN is None:
                error_response = {
                    'status': 'error',
                    'message': 'Invalid openalgo apikey'
                }
                if not get_analyze_mode():
                    log_executor.submit(async_log_order, 'splitorder', data, error_response)
                return make_response(jsonify(error_response), 403)

            # If in analyze mode, analyze each order
            if get_analyze_mode():
                analyze_results = []
                
                # Analyze full-size orders
                for i in range(num_full_orders):
                    order_data = copy.deepcopy(split_data)
                    order_data['quantity'] = str(split_size)
                    
                    # Analyze the order
                    _, analysis = analyze_request(order_data, 'splitorder', True)
                    
                    if analysis.get('status') == 'success':
                        analyze_results.append({
                            'order_num': i + 1,
                            'quantity': split_size,
                            'status': 'success',
                            'orderid': generate_order_id()
                        })
                    else:
                        analyze_results.append({
                            'order_num': i + 1,
                            'quantity': split_size,
                            'status': 'error',
                            'message': analysis.get('message', 'Analysis failed')
                        })

                # Analyze remaining quantity if any
                if remaining_qty > 0:
                    order_data = copy.deepcopy(split_data)
                    order_data['quantity'] = str(remaining_qty)
                    
                    _, analysis = analyze_request(order_data, 'splitorder', True)
                    
                    if analysis.get('status') == 'success':
                        analyze_results.append({
                            'order_num': num_full_orders + 1,
                            'quantity': remaining_qty,
                            'status': 'success',
                            'orderid': generate_order_id()
                        })
                    else:
                        analyze_results.append({
                            'order_num': num_full_orders + 1,
                            'quantity': remaining_qty,
                            'status': 'error',
                            'message': analysis.get('message', 'Analysis failed')
                        })

                response_data = {
                    'mode': 'analyze',
                    'status': 'success',
                    'total_quantity': total_quantity,
                    'split_size': split_size,
                    'results': analyze_results
                }

                # Store complete request data without apikey
                analyzer_request = split_request_data.copy()
                analyzer_request['api_type'] = 'splitorder'
                
                # Log to analyzer database
                log_executor.submit(async_log_analyzer, analyzer_request, response_data, 'splitorder')
                
                # Emit socket event for toast notification
                socketio.emit('analyzer_update', {
                    'request': analyzer_request,
                    'response': response_data
                })
                
                return make_response(jsonify(response_data), 200)

            # Live mode - process actual orders
            broker_module = import_broker_module(broker)
            if broker_module is None:
                error_response = {
                    'status': 'error',
                    'message': 'Broker-specific module not found'
                }
                log_executor.submit(async_log_order, 'splitorder', data, error_response)
                return make_response(jsonify(error_response), 404)

            # Process orders concurrently
            results = []
            
            # Create a ThreadPoolExecutor for concurrent order placement
            with ThreadPoolExecutor(max_workers=10) as order_executor:
                # Prepare orders for concurrent execution
                futures = []
                
                # Submit full-size orders
                for i in range(num_full_orders):
                    order_data = copy.deepcopy(split_data)
                    order_data['quantity'] = str(split_size)
                    futures.append(
                        order_executor.submit(
                            place_single_order,
                            order_data,
                            broker_module,
                            AUTH_TOKEN,
                            i + 1,
                            total_orders
                        )
                    )

                # Submit remaining quantity order if any
                if remaining_qty > 0:
                    order_data = copy.deepcopy(split_data)
                    order_data['quantity'] = str(remaining_qty)
                    futures.append(
                        order_executor.submit(
                            place_single_order,
                            order_data,
                            broker_module,
                            AUTH_TOKEN,
                            total_orders,
                            total_orders
                        )
                    )

                # Collect results as they complete
                for future in as_completed(futures):
                    result = future.result()
                    results.append(result)

                # Sort results by order_num to maintain order in response
                results.sort(key=lambda x: x['order_num'])

                # Log the split order results
                response_data = {
                    'status': 'success',
                    'total_quantity': total_quantity,
                    'split_size': split_size,
                    'results': results
                }
                log_executor.submit(async_log_order, 'splitorder', split_request_data, response_data)

                return make_response(jsonify(response_data), 200)

        except Exception as e:
            logger.error("An unexpected error occurred in SplitOrder endpoint.")
            traceback.print_exc()
            error_message = 'An unexpected error occurred'
            if get_analyze_mode():
                return make_response(jsonify(emit_analyzer_error(data, error_message)), 500)
            error_response = {'status': 'error', 'message': error_message}
            log_executor.submit(async_log_order, 'splitorder', data, error_response)
            return make_response(jsonify(error_response), 500)
