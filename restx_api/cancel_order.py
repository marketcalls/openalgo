from flask_restx import Namespace, Resource, fields
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

@api.route('/', strict_slashes=False)
class CancelOrder(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        try:
            data = request.json
            order_request_data = copy.deepcopy(data)
            order_request_data.pop('apikey', None)
            # Validate and deserialize input
            order_data = cancel_order_schema.load(data)

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
                # Extract the order ID from order_data
                orderid = order_data.get('orderid')
                if not orderid:
                    logger.error("Order ID is missing in the request data")
                    return make_response(jsonify({'status': 'error', 'message': 'Order ID is missing'}), 400)

                # Use the dynamically imported module's function to cancel the order
                response_message, status_code = broker_module.cancel_order(orderid, AUTH_TOKEN)
            except Exception as e:
                logger.error(f"Error in broker_module.cancel_order: {e}")
                traceback.print_exc()
                return make_response(jsonify({
                    'status': 'error',
                    'message': 'Failed to cancel order due to internal error'
                }), 500)

            if status_code == 200:
                socketio.emit('cancel_order_event', {
                    'status': response_message.get('status'),
                    'orderid': orderid
                })
                try:
                    executor.submit(async_log_order, 'cancelorder', order_request_data, response_message)
                except Exception as e:
                    logger.error(f"Error submitting async_log_order task: {e}")
                    traceback.print_exc()
                return make_response(jsonify(response_message), 200)
            else:
                message = response_message.get('message', 'Failed to cancel order') if isinstance(response_message, dict) else 'Failed to cancel order'
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
            logger.error("An unexpected error occurred in CancelOrder endpoint.")
            traceback.print_exc()
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)