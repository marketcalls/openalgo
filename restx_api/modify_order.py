from flask_restx import Namespace, Resource, fields
from flask import request, jsonify, make_response
from database.auth_db import get_auth_token_broker
from database.apilog_db import async_log_order, executor
from extensions import socketio
from limiter import limiter
import os
import copy
from dotenv import load_dotenv
import importlib
import logging
import traceback

load_dotenv()

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('modify_order', description='Modify Order API')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def import_broker_module(broker_name):
    try:
        module_path = f'broker.{broker_name}.api.order_api'
        broker_module = importlib.import_module(module_path)
        return broker_module
    except ImportError as error:
        logger.error(f"Error importing broker module '{module_path}': {error}")
        return None

@api.route('/', strict_slashes=False)
class ModifyOrder(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        try:
            data = request.json
            order_request_data = copy.deepcopy(data)
            order_request_data.pop('apikey', None)

            mandatory_fields = [
                'apikey', 'strategy', 'exchange', 'symbol', 'orderid',
                'action', 'product', 'pricetype', 'price', 'quantity',
                'disclosed_quantity', 'trigger_price'
            ]
            missing_fields = [field for field in mandatory_fields if field not in data]

            if missing_fields:
                logger.warning(f"Missing mandatory fields: {', '.join(missing_fields)}")
                return make_response(jsonify({
                    'status': 'error',
                    'message': f"Missing mandatory field(s): {', '.join(missing_fields)}"
                }), 400)

            api_key = data['apikey']
            AUTH_TOKEN, broker = get_auth_token_broker(api_key)

            if AUTH_TOKEN is None:
                logger.error("Invalid openalgo apikey")
                return make_response(jsonify({
                    'status': 'error',
                    'message': 'Invalid openalgo apikey'
                }), 403)

            broker_module = import_broker_module(broker)
            if broker_module is None:
                logger.error("Broker-specific module not found")
                return make_response(jsonify({
                    'status': 'error',
                    'message': 'Broker-specific module not found'
                }), 404)

            try:
                # Use the dynamically imported module's function to modify the order
                response_message, status_code = broker_module.modify_order(data, AUTH_TOKEN)
            except Exception as e:
                logger.error(f"Error in broker_module.modify_order: {e}")
                traceback.print_exc()
                return make_response(jsonify({
                    'status': 'error',
                    'message': 'Failed to modify order due to internal error'
                }), 500)

            socketio.emit('modify_order_event', {
                'status': response_message.get('status'),
                'orderid': data.get('orderid')
            })

            try:
                # Assuming executor and async_log_order are properly defined and set up
                executor.submit(async_log_order, 'modifyorder', order_request_data, response_message)
            except Exception as e:
                logger.error(f"Error submitting async_log_order task: {e}")
                traceback.print_exc()

            return make_response(jsonify(response_message), status_code)

        except KeyError as e:
            missing_field = str(e)
            logger.error(f"KeyError: Missing field {missing_field}")
            return make_response(jsonify({
                'status': 'error',
                'message': f'A required field is missing from the request: {missing_field}'
            }), 400)
        except Exception as e:
            logger.error("An unexpected error occurred in ModifyOrder endpoint.")
            traceback.print_exc()
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)