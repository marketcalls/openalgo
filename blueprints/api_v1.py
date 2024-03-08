from flask import Blueprint, request, jsonify
from database.auth_db import get_api_key
from database.apilog_db import async_log_order, executor
from api.order_api import place_order_api, place_smartorder_api , close_all_positions , cancel_order , modify_order, get_order_book
from extensions import socketio  # Import SocketIO
from limiter import limiter  # Import the limiter instance
import copy
import os 
from dotenv import load_dotenv
load_dotenv()

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")


# Create a Blueprint for version 1 of the API
api_v1_bp = Blueprint('api_v1', __name__, url_prefix='/api/v1')

@api_v1_bp.errorhandler(429)
def ratelimit_handler(e):
    return jsonify(error="Rate limit exceeded"), 429

@api_v1_bp.route('/placeorder', methods=['POST'])
@limiter.limit(API_RATE_LIMIT)
def place_order():
    try:
        # Extracting JSON data from the POST request
        data = request.json
        order_request_data = copy.deepcopy(request.json)
        # Remove 'apikey' from the copy
        order_request_data.pop('apikey', None)

        # Mandatory fields list
        mandatory_fields = ['apikey', 'strategy', 'exchange', 'symbol', 'action', 'quantity']
        missing_fields = [field for field in mandatory_fields if field not in data or not data[field]]

        # Check if there are any missing mandatory fields
        if missing_fields:
            return jsonify({
                'status': 'error',
                'message': f'Missing mandatory field(s): {", ".join(missing_fields)}'
            }), 400

        login_username = os.getenv('LOGIN_USERNAME')
        current_api_key = get_api_key(login_username)
               
        

        # Check if the provided Placeorder Request API key matches the Current App API Key
        if current_api_key != data['apikey']:
            return jsonify({'status': 'error', 'message': 'Invalid openalgo apikey'}), 403

        
        res, response_data = place_order_api(data)
        #print(f'placeorder response : {place_order_api(data)}')

        # Check if the 'data' field is not null and the order was successfully placed
              
        
        if res.status == 200 and response_data.get('data'):
            order_id = response_data['data'].get('orderid')  # Extracting the orderid from response
            socketio.emit('order_event', {'symbol': data['symbol'], 'action': data['action'], 'orderid': order_id})
            
            if order_id:
                order_response_data = {
                       'status': 'success',
                        'orderid': order_id
                        }
                # Call the asynchronous log function
                executor.submit(async_log_order,'placeorder',order_request_data, order_response_data)
                return jsonify(order_response_data)
                
            else:
                # In case 'orderid' is not in the 'data'
                return jsonify({
                    'status': 'error',
                    'message': 'Order placed but order ID not found in response',
                    'details': response_data
                }), 500
        else:
            # If 'data' is null or status is not 200, extract the message and return as error
            message = response_data.get('message', 'Failed to place order')
            return jsonify({
                'status': 'error',
                'message': message,
                
            }), res.status if res.status != 200 else 500  # Use the API's status code, unless it's 200 but 'data' is null
    
    except KeyError as e:
        return jsonify({'status': 'error', 'message': f'Missing mandatory field: {e}'}), 400
    except Exception as e:
        return jsonify({'status': 'error', 'message': f"Order placement failed: {e}"}), 500
    


@api_v1_bp.route('/placesmartorder', methods=['POST'])
@limiter.limit(API_RATE_LIMIT)
def place_smart_order():
    try:
        # Extracting JSON data from the POST request
        data = request.json
        
        order_request_data = copy.deepcopy(request.json)
        # Remove 'apikey' from the copy
        order_request_data.pop('apikey', None)

        # Mandatory fields list
        mandatory_fields = ['apikey', 'strategy', 'exchange', 'symbol', 'action', 'quantity','position_size']
        missing_fields = [field for field in mandatory_fields if field not in data or not data[field]]

        # Check if there are any missing mandatory fields
        if missing_fields:
            return jsonify({
                'status': 'error',
                'message': f'Missing mandatory field(s): {", ".join(missing_fields)}'
            }), 400

        login_username = os.getenv('LOGIN_USERNAME')
        current_api_key = get_api_key(login_username)
               

        # Check if the provided Placeorder Request API key matches the Current App API Key
        if current_api_key != data['apikey']:
            return jsonify({'status': 'error', 'message': 'Invalid openalgo apikey'}), 403

        
        #print(f'placesmartorder_resp : {place_smartorder_api(data)}')
        res, response_data = place_smartorder_api(data)

        if res == None and response_data.get('message'):
            order_response_data = {
                    'status': 'success',
                    'message': response_data.get('message')
                }
            
            # Call the asynchronous log function
            executor.submit(async_log_order,'placesmartorder',order_request_data, order_response_data)
            return jsonify(order_response_data)
        
        # Check if the 'data' field is not null and the order was successfully placed
        if res.status == 200 and response_data.get('data'):
            order_id = response_data['data'].get('orderid')  # Extracting the orderid from response
            socketio.emit('order_event', {'symbol': data['symbol'], 'action': data['action'], 'orderid': order_id})
            if order_id:
                order_response_data = {
                       'status': 'success',
                        'orderid': order_id
                        }
                # Call the asynchronous log function
                executor.submit(async_log_order,'placesmartorder',order_request_data, order_response_data)
                return jsonify(order_response_data)
            
            else:
                # In case 'orderid' is not in the 'data'
                return jsonify({
                    'status': 'error',
                    'message': 'Order placed but order ID not found in response',
                    'details': response_data
                }), 500
        else:
            # If 'data' is null or status is not 200, extract the message and return as error
            message = response_data.get('message', 'Failed to place order')
            return jsonify({
                'status': 'error',
                'message': message,
                
            }), res.status if res.status != 200 else 500  # Use the API's status code, unless it's 200 but 'data' is null
    
    except KeyError as e:
        return jsonify({'status': 'error', 'message': f'Missing mandatory field: {e}'}), 400
    except Exception as e:
        return jsonify({'status': 'error', 'message': f"Order placement failed: {e}"}), 500
    
@api_v1_bp.route('/closeposition', methods=['POST'])
@limiter.limit(API_RATE_LIMIT)
def close_position():
    try:
        data = request.json  # Corrected to use data directly for consistency
        sqoff_request_data = copy.deepcopy(data)
        sqoff_request_data.pop('apikey', None)  # Remove 'apikey' from the copy for logging
        
        # Corrected mandatory fields check
        mandatory_fields = ['apikey', 'strategy']
        missing_fields = [field for field in mandatory_fields if field not in data or not data[field]]
        
        if missing_fields:
            return jsonify({'status': 'error', 'message': f'Missing mandatory field(s): {", ".join(missing_fields)}'}), 400

        login_username = os.getenv('LOGIN_USERNAME')
        current_api_key = get_api_key(login_username)
        
        # Check if the provided API key matches the current API key
        if data['apikey'] != current_api_key:
            return jsonify({"message": "Invalid API key"}), 403

        # Call the function to close all positions
        response_code, status_code = close_all_positions(current_api_key)

        # Emitting a socket event for closing position
        socketio.emit('close_position', {'status': 'success', 'message': 'All Open Positions SquaredOff'})
        
        # Asynchronously logging the action
        executor.submit(async_log_order, 'squareoff', sqoff_request_data, "All Open Positions SquaredOff")

        return jsonify(response_code), status_code

    except KeyError as e:
        # Handle the case where a mandatory field is not provided
        return jsonify({'status': 'error', 'message': f'Missing mandatory field: {e}'}), 400
    except Exception as e:
        # Emit failure event if an exception occurs
        socketio.emit('close_position', {'message': 'Failed to Square Off'})
        return jsonify({'status': 'error', 'message': f"Failed to close positions: {e}"}), 500

  
@api_v1_bp.route('/cancelorder', methods=['POST'])
@limiter.limit(API_RATE_LIMIT)
def cancel_order_route():
    try:
        # Extracting JSON data from the POST request
        data = request.json
        order_request_data = copy.deepcopy(data)  # For logging
        order_request_data.pop('apikey', None)  # Remove API key from data to be logged

        # Mandatory fields list
        mandatory_fields = ['apikey', 'strategy', 'orderid']
        missing_fields = [field for field in mandatory_fields if field not in data]

        print(missing_fields)

        # Check if there are any missing mandatory fields
        if missing_fields:
            return jsonify({
                'status': 'error',
                'message': f'Missing mandatory field(s): {", ".join(missing_fields)}'
            }), 400

        login_username = os.getenv('LOGIN_USERNAME')
        current_api_key = get_api_key(login_username)

        # Check if the provided API key matches the current API key
        if current_api_key != data['apikey']:
            return jsonify({'status': 'error', 'message': 'Invalid API key'}), 403

        # Call the cancel_order function
        response_message, status_code = cancel_order(data['orderid'])

        # Emit the cancellation event to the client via Socket.IO
        socketio.emit('cancel_order_event', {'status': response_message['status'], 'orderid': data['orderid']})

        # Log the successful order cancellation attempt
        executor.submit(async_log_order, 'cancelorder', order_request_data, response_message)

        return jsonify(response_message), status_code

    except KeyError as e:
        return jsonify({'status': 'error', 'message': f'Missing mandatory field: {e}'}), 400
    except Exception as e:
        # Emit failure event if an exception occurs
        socketio.emit('cancel_order_event', {'message': 'Failed to cancel order'})
        return jsonify({'status': 'error', 'message': f"Order cancellation failed: {e}"}), 500


@api_v1_bp.route('/cancelallorder', methods=['POST'])
@limiter.limit(API_RATE_LIMIT)
def cancel_all_orders():
    try:
        data = request.json

        order_request_data = copy.deepcopy(data)  # For logging
        order_request_data.pop('apikey', None)  # Remove API key from data to be logged
        # Validate mandatory fields
        mandatory_fields = ['apikey', 'strategy']
        missing_fields = [field for field in mandatory_fields if field not in data]

        if missing_fields:
            return jsonify({
                'status': 'error',
                'message': f'Missing mandatory field(s): {", ".join(missing_fields)}'
            }), 400

        login_username = os.getenv('LOGIN_USERNAME')
        current_api_key = get_api_key(login_username)

        # Check if the provided API key matches the current API key
        if current_api_key != data['apikey']:
            return jsonify({'status': 'error', 'message': 'Invalid API key'}), 403

        # Get the order book
        order_book_response = get_order_book()
        if order_book_response['status'] != True:
            return jsonify({'status': 'error', 'message': 'Failed to retrieve order book'}), 500

        # Filter orders that are in 'open' or 'trigger_pending' state
        orders_to_cancel = [order for order in order_book_response.get('data', [])
                            if order['status'] in ['open', 'trigger pending']]
        canceled_orders = []
        failed_cancellations = []

        # Cancel the filtered orders
        for order in orders_to_cancel:
            orderid = order['orderid']
            cancel_response, status_code = cancel_order(orderid)  # Updated to assume cancel_order returns response and status_code
            if status_code == 200:
                canceled_orders.append(orderid)
                # Emit the cancellation event to the client via Socket.IO
                socketio.emit('cancel_order_event', {'status': 'success', 'orderid': orderid})
            else:
                failed_cancellations.append(orderid)

        # Asynchronously logging the cancellation attempt
        executor.submit(async_log_order, 'cancelallorder', order_request_data, {
            'canceled_orders': canceled_orders,
            'failed_cancellations': failed_cancellations
        })

        # Return a success response
        message = f'Canceled {len(canceled_orders)} orders. Failed to cancel {len(failed_cancellations)} orders.'
        return jsonify({
            'status': 'success',
            'message': message
        })

    except KeyError as e:
        return jsonify({'status': 'error', 'message': f'Missing mandatory field: {e}'}), 400
    except Exception as e:
        # Emit failure event if an exception occurs
        socketio.emit('cancel_order_event', {'message': 'Failed to cancel orders'})
        return jsonify({'status': 'error', 'message': f"Failed to cancel orders: {e}"}), 500


@api_v1_bp.route('/modifyorder', methods=['POST'])
@limiter.limit(API_RATE_LIMIT)
def modify_order_route():
    try:
        data = request.json
        order_request_data = copy.deepcopy(data)  # For logging
        order_request_data.pop('apikey', None)  # Remove API key from data to be logged
        
        # Mandatory fields including all necessary for order modification
        mandatory_fields = ['apikey', 'strategy', 'exchange', 'symbol', 'orderid', 'action', 'product', 'pricetype', 'price', 'quantity', 'disclosed_quantity', 'trigger_price']
        missing_fields = [field for field in mandatory_fields if field not in data or not data[field]]

        if missing_fields:
            return jsonify({'status': 'error', 'message': f'Missing mandatory field(s): {", ".join(missing_fields)}'}), 400

        login_username = os.getenv('LOGIN_USERNAME')
        current_api_key = get_api_key(login_username)

        if data['apikey'] != current_api_key:
            return jsonify({'status': 'error', 'message': 'Invalid API key'}), 403

        # Assuming modify_order requires specific parameters from `data` and returns a response_message and a status_code
        response_message, status_code = modify_order(data)
        
        # Emitting the modification event to the client via Socket.IO
        socketio.emit('modify_order_event', {'status': response_message['status'], 'orderid': response_message.get('orderid')})
        
        # Asynchronously logging the order modification attempt
        executor.submit(async_log_order, 'modifyorder', order_request_data, response_message)

        return jsonify(response_message), status_code

    except KeyError as e:
        return jsonify({'status': 'error', 'message': f'Missing mandatory field: {e}'}), 400
    except Exception as e:
        # Emit failure event if an exception occurs
        socketio.emit('modify_order_event', {'message': 'Failed to modify order'})
        return jsonify({'status': 'error', 'message': f"Order modification failed: {e}"}), 500
