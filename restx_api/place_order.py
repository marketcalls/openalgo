from flask_restx import Namespace, Resource, fields
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from database.auth_db import get_auth_token_broker
from database.apilog_db import async_log_order, executor
from database.settings_db import get_analyze_mode
from extensions import socketio
from limiter import limiter
from utils.api_analyzer import analyze_request
from utils.constants import (
    VALID_EXCHANGES,
    VALID_ACTIONS,
    VALID_PRICE_TYPES,
    VALID_PRODUCT_TYPES,
    REQUIRED_ORDER_FIELDS
)
import os
from dotenv import load_dotenv
import importlib
import traceback
import logging

load_dotenv()

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('place_order', description='Place Order API')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Marshmallow schema
from restx_api.schemas import OrderSchema
order_schema = OrderSchema()

def import_broker_module(broker_name):
    try:
        module_path = f'broker.{broker_name}.api.order_api'
        broker_module = importlib.import_module(module_path)
        return broker_module
    except ImportError as error:
        logger.error(f"Error importing broker module '{module_path}': {error}")
        return None

@api.route('/', strict_slashes=False)
class PlaceOrder(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        try:
            data = request.json
            # Validate and deserialize input
            order_data = order_schema.load(data)

            # Check for missing mandatory fields
            missing_fields = [field for field in REQUIRED_ORDER_FIELDS if field not in data]
            if missing_fields:
                error_response = {
                    'status': 'error',
                    'message': f'Missing mandatory field(s): {", ".join(missing_fields)}'
                }
                if not get_analyze_mode():
                    executor.submit(async_log_order, 'placeorder', data, error_response)
                return make_response(jsonify(error_response), 400)

            # Validate exchange
            if 'exchange' in data and data['exchange'] not in VALID_EXCHANGES:
                error_response = {
                    'status': 'error',
                    'message': f'Invalid exchange. Must be one of: {", ".join(VALID_EXCHANGES)}'
                }
                if not get_analyze_mode():
                    executor.submit(async_log_order, 'placeorder', data, error_response)
                return make_response(jsonify(error_response), 400)

            # Validate action
            if 'action' in data and data['action'] not in VALID_ACTIONS:
                error_response = {
                    'status': 'error',
                    'message': f'Invalid action. Must be one of: {", ".join(VALID_ACTIONS)}'
                }
                if not get_analyze_mode():
                    executor.submit(async_log_order, 'placeorder', data, error_response)
                return make_response(jsonify(error_response), 400)

            # Validate price type if provided
            if 'price_type' in data and data['price_type'] not in VALID_PRICE_TYPES:
                error_response = {
                    'status': 'error',
                    'message': f'Invalid price type. Must be one of: {", ".join(VALID_PRICE_TYPES)}'
                }
                if not get_analyze_mode():
                    executor.submit(async_log_order, 'placeorder', data, error_response)
                return make_response(jsonify(error_response), 400)

            # Validate product type if provided
            if 'product_type' in data and data['product_type'] not in VALID_PRODUCT_TYPES:
                error_response = {
                    'status': 'error',
                    'message': f'Invalid product type. Must be one of: {", ".join(VALID_PRODUCT_TYPES)}'
                }
                if not get_analyze_mode():
                    executor.submit(async_log_order, 'placeorder', data, error_response)
                return make_response(jsonify(error_response), 400)

            api_key = order_data['apikey']
            AUTH_TOKEN, broker = get_auth_token_broker(api_key)
            if AUTH_TOKEN is None:
                error_response = {
                    'status': 'error',
                    'message': 'Invalid openalgo apikey'
                }
                if not get_analyze_mode():
                    executor.submit(async_log_order, 'placeorder', data, error_response)
                return make_response(jsonify(error_response), 403)

            # If in analyze mode, analyze the request and store in analyzer_logs
            if get_analyze_mode():
                _, analysis = analyze_request(order_data)
                response_data = {
                    'status': analysis.get('status', 'error'),
                    'message': analysis.get('message', 'Analysis failed'),
                    'warnings': analysis.get('warnings', []),
                    'broker': broker,
                    'mode': 'analyze'
                }
                return make_response(jsonify(response_data), 200)

            # If not in analyze mode, proceed with actual order placement and store in order_logs
            broker_module = import_broker_module(broker)
            if broker_module is None:
                error_response = {
                    'status': 'error',
                    'message': 'Broker-specific module not found'
                }
                executor.submit(async_log_order, 'placeorder', data, error_response)
                return make_response(jsonify(error_response), 404)

            try:
                # Call the broker's place_order_api function
                res, response_data, order_id = broker_module.place_order_api(order_data, AUTH_TOKEN)
            except Exception as e:
                logger.error(f"Error in broker_module.place_order_api: {e}")
                traceback.print_exc()
                error_response = {
                    'status': 'error',
                    'message': 'Failed to place order due to internal error'
                }
                executor.submit(async_log_order, 'placeorder', data, error_response)
                return make_response(jsonify(error_response), 500)

            if res.status == 200:
                socketio.emit('order_event', {
                    'symbol': order_data['symbol'],
                    'action': order_data['action'],
                    'orderid': order_id,
                    'exchange': order_data.get('exchange', 'Unknown'),
                    'price_type': order_data.get('price_type', 'Unknown'),
                    'product_type': order_data.get('product_type', 'Unknown'),
                    'mode': 'live'
                })
                order_response_data = {'status': 'success', 'orderid': order_id}
                executor.submit(async_log_order, 'placeorder', order_data, order_response_data)
                return make_response(jsonify(order_response_data), 200)
            else:
                message = response_data.get('message', 'Failed to place order') if isinstance(response_data, dict) else 'Failed to place order'
                error_response = {
                    'status': 'error',
                    'message': message
                }
                executor.submit(async_log_order, 'placeorder', data, error_response)
                return make_response(jsonify(error_response), res.status if res.status != 200 else 500)

        except ValidationError as err:
            logger.warning(f"Validation error: {err.messages}")
            error_response = {'status': 'error', 'message': err.messages}
            if not get_analyze_mode():
                executor.submit(async_log_order, 'placeorder', data, error_response)
            return make_response(jsonify(error_response), 400)

        except KeyError as e:
            missing_field = str(e)
            logger.error(f"KeyError: Missing field {missing_field}")
            error_response = {
                'status': 'error',
                'message': f"A required field is missing: {missing_field}"
            }
            if not get_analyze_mode():
                executor.submit(async_log_order, 'placeorder', data, error_response)
            return make_response(jsonify(error_response), 400)

        except Exception as e:
            logger.error("An unexpected error occurred in PlaceOrder endpoint.")
            traceback.print_exc()
            error_response = {
                'status': 'error',
                'message': 'An unexpected error occurred'
            }
            if not get_analyze_mode():
                executor.submit(async_log_order, 'placeorder', data, error_response)
            return make_response(jsonify(error_response), 500)
