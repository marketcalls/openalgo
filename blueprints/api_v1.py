from flask import Blueprint, request, jsonify
from database.auth_db import get_auth_token
from database.token_db import get_token
from mapping.transform_data import transform_data
import http.client
import json
import os


# Create a Blueprint for version 1 of the API
api_v1_bp = Blueprint('api_v1', __name__, url_prefix='/api/v1')

@api_v1_bp.route('/placeorder', methods=['POST'])
def place_order():
    
    try:
        # Extracting form data or JSON data from the POST request
        data = request.json

        login_username = os.getenv('LOGIN_USERNAME')

        AUTH_TOKEN = get_auth_token(login_username)
        
        
        # Retrieve AUTH_TOKEN and API_KEY from session or environment
        
        #print(f'Auth Token : {AUTH_TOKEN}')
        print(f'API Request : {data}')
        
        token = get_token(data['symbol'],data['exchange'])
        
        newdata = transform_data(data,token)  
        
        print(f'New API Request : {newdata}')
            

        # Prepare headers with the AUTH_TOKEN and other details
        headers = {
            'Authorization': f'Bearer {AUTH_TOKEN}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-UserType': 'USER',
            'X-SourceID': 'WEB',
            'X-ClientLocalIP': 'CLIENT_LOCAL_IP', 
            'X-ClientPublicIP': 'CLIENT_PUBLIC_IP',
            'X-MACAddress': 'MAC_ADDRESS',
            'X-PrivateKey': newdata['apikey']
        }

        
        
        # Preparing the payload with data received from the request
        payload = json.dumps({
            "variety": newdata.get('variety', 'NORMAL'),
            "tradingsymbol": newdata['tradingsymbol'],
            "symboltoken": newdata['symboltoken'],
            "transactiontype": newdata['transactiontype'],
            "exchange": newdata['exchange'],
            "ordertype": newdata.get('ordertype', 'MARKET'),
            "producttype": newdata.get('producttype', 'INTRADAY'),
            "duration": newdata.get('duration', 'DAY'),
            "price": newdata.get('price', '0'),
            "triggerprice": newdata.get('triggerprice', '0'),
            "squareoff": newdata.get('squareoff', '0'),
            "stoploss": newdata.get('stoploss', '0'),
            "quantity": newdata['quantity']
        })

        # Making the HTTP request to place the order
        conn = http.client.HTTPSConnection("apiconnect.angelbroking.com")
        conn.request("POST", "/rest/secure/angelbroking/order/v1/placeOrder", payload, headers)
        
        # Processing the response
        res = conn.getresponse()
        data = res.read()
        response_data = json.loads(data.decode("utf-8"))
        
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
    
