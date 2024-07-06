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

load_dotenv()

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('modify_order', description='Modify Order API')

# Marshmallow schema
from restx_api.schemas import ModifyOrderSchema
modify_order_schema = ModifyOrderSchema()

def import_broker_module(broker_name):
    try:
        module_path = f'broker.{broker_name}.api.order_api'
        broker_module = importlib.import_module(module_path)
        return broker_module
    except ImportError as error:
        return None

@api.route('/', strict_slashes=False)
class ModifyOrder(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        try:
            data = request.json
            # Validate and deserialize input
            order_data = modify_order_schema.load(data)

            api_key = order_data['apikey']
            AUTH_TOKEN, broker = get_auth_token_broker(api_key)
            if AUTH_TOKEN is None:
                return make_response(jsonify({'status': 'error', 'message': 'Invalid openalgo apikey'}), 403)

            broker_module = import_broker_module(broker)
            if broker_module is None:
                return make_response(jsonify({'status': 'error', 'message': 'Broker-specific module not found'}), 404)

            res, response_data, order_id = broker_module.modify_order_api(order_data, AUTH_TOKEN)

            if res.status == 200:
                socketio.emit('modify_order_event', {'symbol': order_data['symbol'], 'action': order_data['action'], 'orderid': order_id})
                order_response_data = {'status': 'success', 'orderid': order_id}
                executor.submit(async_log_order, 'modifyorder', order_data, order_response_data)
                return make_response(jsonify(order_response_data), 200)
            else:
                message = response_data.get('message', 'Failed to modify order') if isinstance(response_data, dict) else 'Failed to modify order'
                return make_response(jsonify({'status': 'error', 'message': message}), res.status if res.status != 200 else 500)
        except ValidationError as err:
            return make_response(jsonify({'status': 'error', 'message': err.messages}), 400)
        except KeyError as e:
            return make_response(jsonify({'status': 'error', 'message': 'A required field is missing from the request'}), 400)
        except Exception as e:
            return make_response(jsonify({'status': 'error', 'message': 'An unexpected error occurred'}), 500)
