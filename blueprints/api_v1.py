from flask import Blueprint, request, jsonify
from database.auth_db import get_auth_token, get_api_key
from database.token_db import get_token
from mapping.transform_data import transform_data
from api.order_api import place_order_api, place_smartorder_api
import http.client
import json
import os

# Create a Blueprint for version 1 of the API
api_v1_bp = Blueprint('api_v1', __name__, url_prefix='/api/v1')

@api_v1_bp.route('/placeorder', methods=['POST'])
def place_order():
    try:
        # Extracting JSON data from the POST request
        data = request.json

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
            if order_id:
                return jsonify({
                    'status': 'success',
                    'orderid': order_id
                })
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
def place_smart_order():
    try:
        # Extracting JSON data from the POST request
        data = request.json

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
        
        # Check if the 'data' field is not null and the order was successfully placed
        if res.status == 200 and response_data.get('data'):
            order_id = response_data['data'].get('orderid')  # Extracting the orderid from response
            if order_id:
                return jsonify({
                    'status': 'success',
                    'orderid': order_id
                })
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
    