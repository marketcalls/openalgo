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
api = Namespace('cancel_all_orders', description='Cancel All Orders API')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Marshmallow schema
from restx_api.schemas import CancelAllOrderSchema
cancel_all_orders_schema = CancelAllOrderSchema()

def import_broker_module(broker_name):
    try:
        module_path = f'broker.{broker_name}.api.order_api'
        broker_module = importlib.import_module(module_path)
        return broker_module
    except ImportError as error:
        logger.error(f"Error importing broker module '{module_path}': {error}")
        return None

@api.route('/', strict_slashes=False)
class CancelAllOrders(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        try:
            data = request.json
            order_request_data = copy.deepcopy(data)
            order_request_data.pop('apikey', None)
            # Validate and deserialize input
            order_data = cancel_all_orders_schema.load(data)

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
                # Use the dynamically imported module's function to cancel all orders
                canceled_orders, failed_cancellations = broker_module.cancel_all_orders_api(order_data, AUTH_TOKEN)
            except Exception as e:
                logger.error(f"Error in broker_module.cancel_all_orders_api: {e}")
                traceback.print_exc()
                return make_response(jsonify({
                    'status': 'error',
                    'message': 'Failed to cancel all orders due to internal error'
                }), 500)

            # Emit events for each canceled order
            for orderid in canceled_orders:
                socketio.emit('cancel_order_event', {'status': 'success', 'orderid': orderid})

            try:
                # Log the action asynchronously
                executor.submit(async_log_order, 'cancelallorder', order_request_data, {
                    'canceled_orders': canceled_orders,
                    'failed_cancellations': failed_cancellations
                })
            except Exception as e:
                logger.error(f"Error submitting async_log_order task: {e}")
                traceback.print_exc()

            message = f'Canceled {len(canceled_orders)} orders. Failed to cancel {len(failed_cancellations)} orders.'
            response_data = {
                'status': 'success',
                'message': message
            }
            return make_response(jsonify(response_data), 200)

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
            logger.error("An unexpected error occurred in CancelAllOrders endpoint.")
            traceback.print_exc()
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)