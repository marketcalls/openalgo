from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from database.auth_db import get_auth_token_broker
from database.apilog_db import async_log_order, executor
from extensions import socketio
from limiter import limiter
import os
from dotenv import load_dotenv
import importlib
import logging
import traceback
import copy
import time

load_dotenv()

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
SMART_ORDER_DELAY = os.getenv("SMART_ORDER_DELAY", "0.5")
api = Namespace('place_smart_order', description='Place Smart Order API')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Marshmallow schema
from restx_api.schemas import SmartOrderSchema
smart_order_schema = SmartOrderSchema()

def import_broker_module(broker_name):
    try:
        module_path = f'broker.{broker_name}.api.order_api'
        broker_module = importlib.import_module(module_path)
        return broker_module
    except ImportError as error:
        logger.error(f"Error importing broker module '{module_path}': {error}")
        return None

@api.route('/', strict_slashes=False)
class PlaceSmartOrder(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        try:
            data = request.json
            order_request_data = copy.deepcopy(data)
            order_request_data.pop('apikey', None)
            # Validate and deserialize input
            order_data = smart_order_schema.load(data)

            api_key = order_data['apikey']
            AUTH_TOKEN, broker = get_auth_token_broker(api_key)
            if AUTH_TOKEN is None:
                logger.error("Invalid openalgo apikey")
                return make_response(jsonify({'status': 'error', 'message': 'Invalid openalgo apikey'}), 403)

            broker_module = import_broker_module(broker)
            if broker_module is None:
                logger.error("Broker-specific module not found")
                return make_response(jsonify({'status': 'error', 'message': 'Broker-specific module not found'}), 404)

            try:
                # Use the dynamically imported module's function to place the smart order
                res, response_data, order_id = broker_module.place_smartorder_api(order_data, AUTH_TOKEN)
            except Exception as e:
                logger.error(f"Error in broker_module.place_smartorder_api: {e}")
                traceback.print_exc()
                return make_response(jsonify({
                    'status': 'error',
                    'message': 'Failed to place smart order due to internal error'
                }), 500)

            # Add delay if needed
            try:
                time.sleep(float(SMART_ORDER_DELAY))
            except Exception as e:
                logger.error(f"Invalid SMART_ORDER_DELAY value: {SMART_ORDER_DELAY}")
                traceback.print_exc()
                # Proceed without delay if there's an error

            if res and res.status == 200:
                socketio.emit('order_event', {
                    'symbol': order_data.get('symbol'),
                    'action': order_data.get('action'),
                    'orderid': order_id
                })
                order_response_data = {'status': 'success', 'orderid': order_id}
                try:
                    executor.submit(async_log_order, 'placesmartorder', order_request_data, order_response_data)
                except Exception as e:
                    logger.error(f"Error submitting async_log_order task: {e}")
                    traceback.print_exc()
                return make_response(jsonify(order_response_data), 200)
            else:
                message = response_data.get('message', 'Failed to place smart order') if isinstance(response_data, dict) else 'Failed to place smart order'
                status_code = res.status if res and res.status != 200 else 500
                return make_response(jsonify({'status': 'error', 'message': message}), status_code)
        except ValidationError as err:
            logger.warning(f"Validation error: {err.messages}")
            return make_response(jsonify({'status': 'error', 'message': err.messages}), 400)
        except KeyError as e:
            missing_field = str(e)
            logger.error(f"KeyError: Missing field {missing_field}")
            return make_response(jsonify({
                'status': 'error',
                'message': f"A required field is missing: {missing_field}"
            }), 400)
        except Exception as e:
            logger.error("An unexpected error occurred in PlaceSmartOrder endpoint.")
            traceback.print_exc()
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)