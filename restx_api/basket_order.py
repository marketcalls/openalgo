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
api = Namespace('basket_order', description='Basket Order API')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Marshmallow schema
from restx_api.schemas import BasketOrderSchema, OrderSchema
basket_schema = BasketOrderSchema()
order_schema = OrderSchema()

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
    analyzer_request['api_type'] = 'basketorder'
    
    # Log to analyzer database
    log_executor.submit(async_log_analyzer, analyzer_request, error_response, 'basketorder')
    
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

def validate_order(order_data):
    """Validate individual order data"""
    # Check for missing mandatory fields
    missing_fields = [field for field in REQUIRED_ORDER_FIELDS if field not in order_data]
    if missing_fields:
        return False, f'Missing mandatory field(s): {", ".join(missing_fields)}'

    # Validate exchange
    if order_data.get('exchange') not in VALID_EXCHANGES:
        return False, f'Invalid exchange. Must be one of: {", ".join(VALID_EXCHANGES)}'

    # Validate action
    if order_data.get('action') not in VALID_ACTIONS:
        return False, f'Invalid action. Must be one of: {", ".join(VALID_ACTIONS)}'

    # Validate price type
    if 'pricetype' in order_data and order_data['pricetype'] not in VALID_PRICE_TYPES:
        return False, f'Invalid price type. Must be one of: {", ".join(VALID_PRICE_TYPES)}'

    # Validate product type
    if 'product' in order_data and order_data['product'] not in VALID_PRODUCT_TYPES:
        return False, f'Invalid product type. Must be one of: {", ".join(VALID_PRODUCT_TYPES)}'

    return True, None

def place_single_order(order_data, broker_module, AUTH_TOKEN, total_orders, order_index):
    """Place a single order and emit event"""
    try:
        # Place the order
        res, response_data, order_id = broker_module.place_order_api(order_data, AUTH_TOKEN)

        if res.status == 200:
            # Emit order event for toast notification
            socketio.emit('order_event', {
                'symbol': order_data['symbol'],
                'action': order_data['action'],
                'orderid': order_id,
                'exchange': order_data.get('exchange', 'Unknown'),
                'price_type': order_data.get('pricetype', 'Unknown'),
                'product_type': order_data.get('product', 'Unknown'),
                'mode': 'live',
                'batch_order': True,
                'is_last_order': order_index == total_orders - 1
            })

            return {
                'symbol': order_data['symbol'],
                'status': 'success',
                'orderid': order_id
            }
        else:
            message = response_data.get('message', 'Failed to place order') if isinstance(response_data, dict) else 'Failed to place order'
            return {
                'symbol': order_data['symbol'],
                'status': 'error',
                'message': message
            }

    except Exception as e:
        logger.error(f"Error placing order for {order_data.get('symbol', 'Unknown')}: {e}")
        return {
            'symbol': order_data.get('symbol', 'Unknown'),
            'status': 'error',
            'message': 'Failed to place order due to internal error'
        }

@api.route('/', strict_slashes=False)
class BasketOrder(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Place multiple orders in a basket"""
        try:
            data = request.json
            basket_request_data = copy.deepcopy(data)
            basket_request_data.pop('apikey', None)

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

            api_key = basket_data['apikey']
            AUTH_TOKEN, broker = get_auth_token_broker(api_key)
            if AUTH_TOKEN is None:
                error_response = {
                    'status': 'error',
                    'message': 'Invalid openalgo apikey'
                }
                if not get_analyze_mode():
                    log_executor.submit(async_log_order, 'basketorder', data, error_response)
                return make_response(jsonify(error_response), 403)

            # If in analyze mode, analyze each order and return
            if get_analyze_mode():
                analyze_results = []
                total_orders = len(basket_data['orders'])
                
                for i, order in enumerate(basket_data['orders']):
                    # Add common fields from basket order
                    order['apikey'] = api_key
                    order['strategy'] = basket_data['strategy']
                    
                    # Validate order
                    is_valid, error_message = validate_order(order)
                    if not is_valid:
                        analyze_results.append({
                            'symbol': order.get('symbol', 'Unknown'),
                            'status': 'error',
                            'message': error_message
                        })
                        continue

                    # Analyze the order
                    _, analysis = analyze_request(order, 'basketorder', True)
                    
                    if analysis.get('status') == 'success':
                        analyze_results.append({
                            'symbol': order.get('symbol', 'Unknown'),
                            'status': 'success',
                            'orderid': generate_order_id(),
                            'batch_order': True,
                            'is_last_order': i == total_orders - 1
                        })
                    else:
                        analyze_results.append({
                            'symbol': order.get('symbol', 'Unknown'),
                            'status': 'error',
                            'message': analysis.get('message', 'Analysis failed')
                        })

                response_data = {
                    'mode': 'analyze',
                    'status': 'success',
                    'results': analyze_results
                }

                # Store complete request data without apikey
                analyzer_request = basket_request_data.copy()
                analyzer_request['api_type'] = 'basketorder'
                
                # Log to analyzer database
                log_executor.submit(async_log_analyzer, analyzer_request, response_data, 'basketorder')
                
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
                log_executor.submit(async_log_order, 'basketorder', data, error_response)
                return make_response(jsonify(error_response), 404)

            # Sort orders to prioritize BUY orders before SELL orders
            buy_orders = [order for order in basket_data['orders'] if order.get('action', '').upper() == 'BUY']
            sell_orders = [order for order in basket_data['orders'] if order.get('action', '').upper() == 'SELL']
            sorted_orders = buy_orders + sell_orders
            
            results = []
            total_orders = len(sorted_orders)
            
            # Process BUY orders first
            with ThreadPoolExecutor(max_workers=10) as executor:
                # Process all BUY orders first
                buy_futures = []
                for i, order in enumerate(buy_orders):
                    order['strategy'] = basket_data['strategy']
                    buy_futures.append(
                        executor.submit(
                            place_single_order,
                            {**order, 'apikey': api_key},
                            broker_module,
                            AUTH_TOKEN,
                            total_orders,
                            i
                        )
                    )
                
                # Wait for all BUY orders to complete
                for future in as_completed(buy_futures):
                    result = future.result()
                    if result:
                        results.append(result)
                
                # Then process SELL orders
                sell_futures = []
                for i, order in enumerate(sell_orders, start=len(buy_orders)):
                    order['strategy'] = basket_data['strategy']
                    sell_futures.append(
                        executor.submit(
                            place_single_order,
                            {**order, 'apikey': api_key},
                            broker_module,
                            AUTH_TOKEN,
                            total_orders,
                            i
                        )
                    )
                
                # Wait for all SELL orders to complete
                for future in as_completed(sell_futures):
                    result = future.result()
                    if result:
                        results.append(result)

            # Sort results to maintain order consistency
            results.sort(key=lambda x: 0 if x.get('action', '').upper() == 'BUY' else 1)

            # Log the basket order results
            response_data = {
                'status': 'success',
                'results': results
            }
            log_executor.submit(async_log_order, 'basketorder', basket_request_data, response_data)

            return make_response(jsonify(response_data), 200)

        except Exception as e:
            logger.error("An unexpected error occurred in BasketOrder endpoint.")
            traceback.print_exc()
            error_message = 'An unexpected error occurred'
            if get_analyze_mode():
                return make_response(jsonify(emit_analyzer_error(data, error_message)), 500)
            error_response = {'status': 'error', 'message': error_message}
            log_executor.submit(async_log_order, 'basketorder', data, error_response)
            return make_response(jsonify(error_response), 500)
