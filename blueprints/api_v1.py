from flask import Blueprint, request, jsonify, Response, session
from database.auth_db import get_api_key, get_auth_token_broker
from database.apilog_db import async_log_order, executor
# Removed static import of broker-specific APIs
from extensions import socketio  # Import SocketIO
from limiter import limiter  # Import the limiter instance
import copy
import os
from dotenv import load_dotenv
import importlib  # Import importlib for dynamic imports

load_dotenv()

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")

api_v1_bp = Blueprint('api_v1', __name__, url_prefix='/api/v1')

# Additional helper function for dynamic import
def import_broker_module(broker_name):
    try:
        module_path = f'broker.{broker_name}.api.order_api'
        broker_module = importlib.import_module(module_path)
        return broker_module
    except ImportError as error:
        print(f"Error importing {module_path}: {error}")
        return None

@api_v1_bp.errorhandler(429)
def ratelimit_handler(e):
    return jsonify(error="Rate limit exceeded"), 429


@api_v1_bp.route('/placeorder', methods=['POST'])
@limiter.limit(API_RATE_LIMIT)
def place_order():
    try:
        data = request.json
        order_request_data = copy.deepcopy(data)
        order_request_data.pop('apikey', None)

        mandatory_fields = ['apikey', 'strategy', 'exchange', 'symbol', 'action', 'quantity']
        missing_fields = [field for field in mandatory_fields if field not in data]

        if missing_fields:
            return jsonify({'status': 'error', 'message': f'Missing mandatory field(s): {", ".join(missing_fields)}'}), 400

        api_key = data['apikey']
        AUTH_TOKEN, broker = get_auth_token_broker(api_key)

        if AUTH_TOKEN is None:
            return jsonify({'status': 'error', 'message': 'Invalid openalgo apikey'}), 403

        broker_module = import_broker_module(broker)
        if broker_module is None:
            return jsonify({'status': 'error', 'message': 'Broker-specific module not found'}), 404

        # Use the dynamically imported module's functions
        res, response_data, order_id = broker_module.place_order_api(data, AUTH_TOKEN)

        if res.status == 200:
            socketio.emit('order_event', {'symbol': data['symbol'], 'action': data['action'], 'orderid': order_id})
            order_response_data = {'status': 'success', 'orderid': order_id}
            # executor.submit(async_log_order, 'placeorder', order_request_data, order_response_data) # Assuming executor exists and is configured
            return jsonify(order_response_data)
        else:
            message = response_data.get('message', 'Failed to place order')
            return jsonify({'status': 'error', 'message': message}), res.status if res.status != 200 else 500
    except KeyError as e:
        print(e)
        return jsonify({'status': 'error', 'message': 'A required field is missing from the request'}), 400
    except Exception as e:
        print(e)
        return jsonify({'status': 'error', 'message': 'An unexpected error occurred'}), 500


@api_v1_bp.route('/placesmartorder', methods=['POST'])
@limiter.limit(API_RATE_LIMIT)
def place_smart_order():
    try:
        data = request.json
        order_request_data = copy.deepcopy(data)
        order_request_data.pop('apikey', None)

        mandatory_fields = ['apikey', 'strategy', 'exchange', 'symbol', 'action', 'quantity', 'position_size']
        missing_fields = [field for field in mandatory_fields if field not in data]

        if missing_fields:
            return jsonify({'status': 'error', 'message': f'Missing mandatory field(s): {", ".join(missing_fields)}'}), 400

        api_key = data['apikey']
        AUTH_TOKEN, broker = get_auth_token_broker(api_key)

        if AUTH_TOKEN is None:
            return jsonify({'status': 'error', 'message': 'Invalid openalgo apikey'}), 403

        broker_module = import_broker_module(broker)
        if broker_module is None:
            return jsonify({'status': 'error', 'message': 'Broker-specific module not found'}), 404

        # Use the dynamically imported module's functions
        res, response_data, order_id = broker_module.place_smartorder_api(data, AUTH_TOKEN)

        if res and res.status == 200:
            socketio.emit('order_event', {'symbol': data['symbol'], 'action': data['action'], 'orderid': order_id})
            order_response_data = {'status': 'success', 'orderid': order_id}
            # executor.submit(async_log_order, 'placesmartorder', order_request_data, order_response_data) # Assuming executor exists and is configured
            return jsonify(order_response_data)
        else:
            message = response_data.get('message', 'Failed to place smart order')
            return jsonify({'status': 'error', 'message': message}), res.status if res else 500
    except KeyError as e:
        print(e)
        return jsonify({'status': 'error', 'message': 'A required field is missing from the request'}), 400
    except Exception as e:
        print(e)
        return jsonify({'status': 'error', 'message': 'An unexpected error occurred'}), 500


from flask import Blueprint, request, jsonify
import copy
from database.auth_db import get_auth_token_broker
from extensions import socketio
from limiter import limiter
import importlib
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")

# Assuming api_v1_bp is already defined as in the previous examples

# Helper function for dynamic import, as defined previously
def import_broker_module(broker_name):
    try:
        module_path = f'broker.{broker_name}.api.order_api'
        broker_module = importlib.import_module(module_path)
        return broker_module
    except ImportError as error:
        print(f"Error importing {module_path}: {error}")
        return None

@api_v1_bp.route('/closeposition', methods=['POST'])
@limiter.limit(API_RATE_LIMIT)
def close_position():
    try:
        data = request.json
        sqoff_request_data = copy.deepcopy(data)
        sqoff_request_data.pop('apikey', None)

        mandatory_fields = ['apikey', 'strategy']
        missing_fields = [field for field in mandatory_fields if field not in data]

        if missing_fields:
            return jsonify({'status': 'error', 'message': f'Missing mandatory field(s): {", ".join(missing_fields)}'}), 400

        api_key = data['apikey']
        AUTH_TOKEN, broker = get_auth_token_broker(api_key)

        if AUTH_TOKEN is None:
            return jsonify({'status': 'error', 'message': 'Invalid openalgo apikey'}), 403

        broker_module = import_broker_module(broker)
        if broker_module is None:
            return jsonify({'status': 'error', 'message': 'Broker-specific module not found'}), 404

        # Use the dynamically imported module's functions to close all positions
        response_code, status_code = broker_module.close_all_positions(api_key, AUTH_TOKEN)

        socketio.emit('close_position', {'status': 'success', 'message': 'All Open Positions Squared Off'})
        
        # Assuming executor and async_log_order are properly defined and set up
        # executor.submit(async_log_order, 'squareoff', sqoff_request_data, "All Open Positions Squared Off")

        return jsonify(response_code), status_code

    except KeyError as e:
        print(e)
        return jsonify({'status': 'error', 'message': 'A required field is missing from the request'}), 400
    except Exception as e:
        print(e)
        return jsonify({'status': 'error', 'message': f"Failed to close positions"}), 500

    

@api_v1_bp.route('/cancelorder', methods=['POST'])
@limiter.limit(API_RATE_LIMIT)
def cancel_order_route():
    try:
        data = request.json
        order_request_data = copy.deepcopy(data)
        order_request_data.pop('apikey', None)

        mandatory_fields = ['apikey', 'strategy', 'orderid']
        missing_fields = [field for field in mandatory_fields if field not in data]

        if missing_fields:
            return jsonify({'status': 'error', 'message': f'Missing mandatory field(s): {", ".join(missing_fields)}'}), 400

        api_key = data['apikey']
        AUTH_TOKEN, broker = get_auth_token_broker(api_key)

        if AUTH_TOKEN is None:
            return jsonify({'status': 'error', 'message': 'Invalid openalgo apikey'}), 403

        broker_module = import_broker_module(broker)
        if broker_module is None:
            return jsonify({'status': 'error', 'message': 'Broker-specific module not found'}), 404

        # Use the dynamically imported module's function to cancel the order
        response_message, status_code = broker_module.cancel_order(data['orderid'], AUTH_TOKEN)

        socketio.emit('cancel_order_event', {'status': response_message['status'], 'orderid': data['orderid']})
        
        # Assuming executor and async_log_order are properly defined and set up
        # executor.submit(async_log_order, 'cancelorder', order_request_data, response_message)

        return jsonify(response_message), status_code

    except KeyError as e:
        print(e)
        return jsonify({'status': 'error', 'message': 'A required field is missing from the request'}), 400
    except Exception as e:
        print(e)
        socketio.emit('cancel_order_event', {'message': 'Failed to cancel order'})
        return jsonify({'status': 'error', 'message': f"Order cancellation failed"}), 500
  


@api_v1_bp.route('/cancelallorder', methods=['POST'])
@limiter.limit(API_RATE_LIMIT)
def cancel_all_orders():
    try:
        data = request.json
        order_request_data = copy.deepcopy(data)
        order_request_data.pop('apikey', None)

        mandatory_fields = ['apikey', 'strategy']
        missing_fields = [field for field in mandatory_fields if field not in data]

        if missing_fields:
            return jsonify({'status': 'error', 'message': f'Missing mandatory field(s): {", ".join(missing_fields)}'}), 400

        api_key = data['apikey']
        AUTH_TOKEN, broker = get_auth_token_broker(api_key)

        if AUTH_TOKEN is None:
            return jsonify({'status': 'error', 'message': 'Invalid openalgo apikey'}), 403

        broker_module = import_broker_module(broker)
        if broker_module is None:
            return jsonify({'status': 'error', 'message': 'Broker-specific module not found'}), 404

        # Use the dynamically imported module's function to cancel all orders
        canceled_orders, failed_cancellations = broker_module.cancel_all_orders_api(data, AUTH_TOKEN)

        # Emit events for each canceled order
        for orderid in canceled_orders:
            socketio.emit('cancel_order_event', {'status': 'success', 'orderid': orderid})
        
        # Optionally, emit events for failed cancellations

        # Assuming executor and async_log_order are properly defined and set up
        # executor.submit(async_log_order, 'cancelallorder', order_request_data, {
        #     'canceled_orders': canceled_orders,
        #     'failed_cancellations': failed_cancellations
        # })

        message = f'Canceled {len(canceled_orders)} orders. Failed to cancel {len(failed_cancellations)} orders.'
        return jsonify({
            'status': 'success',
            'message': message
        })

    except KeyError as e:
        print(e)
        return jsonify({'status': 'error', 'message': 'A required field is missing from the request'}), 400
    except Exception as e:
        print(e)
        socketio.emit('cancel_order_event', {'message': 'Failed to cancel orders'})
        return jsonify({'status': 'error', 'message': f"Failed to cancel orders"}), 500


@api_v1_bp.route('/modifyorder', methods=['POST'])
@limiter.limit(API_RATE_LIMIT)
def modify_order_route():
    try:
        data = request.json
        order_request_data = copy.deepcopy(data)
        order_request_data.pop('apikey', None)

        mandatory_fields = ['apikey', 'strategy', 'exchange', 'symbol', 'orderid', 'action', 'product', 'pricetype', 'price', 'quantity', 'disclosed_quantity', 'trigger_price']
        missing_fields = [field for field in mandatory_fields if field not in data]

        if missing_fields:
            return jsonify({'status': 'error', 'message': f'Missing mandatory field(s): {", ".join(missing_fields)}'}), 400

        api_key = data['apikey']
        AUTH_TOKEN, broker = get_auth_token_broker(api_key)

        if AUTH_TOKEN is None:
            return jsonify({'status': 'error', 'message': 'Invalid openalgo apikey'}), 403

        broker_module = import_broker_module(broker)
        if broker_module is None:
            return jsonify({'status': 'error', 'message': 'Broker-specific module not found'}), 404

        # Use the dynamically imported module's function to modify the order
        response_message, status_code = broker_module.modify_order(data, AUTH_TOKEN)

        socketio.emit('modify_order_event', {'status': response_message['status'], 'orderid': data['orderid']})
        
        # Assuming executor and async_log_order are properly defined and set up
        # executor.submit(async_log_order, 'modifyorder', order_request_data, response_message)

        return jsonify(response_message), status_code

    except KeyError as e:
        print(e)
        return jsonify({'status': 'error', 'message': 'A required field is missing from the request'}), 400
    except Exception as e:
        print(e)
        socketio.emit('modify_order_event', {'message': 'Failed to modify order'})
        return jsonify({'status': 'error', 'message': f"Order modification failed"}), 500