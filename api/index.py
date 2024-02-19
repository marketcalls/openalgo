from flask import Flask, request, jsonify, render_template, redirect, url_for
from flask import session
import os
from dotenv import load_dotenv
from SmartApi import SmartConnect  # Adjust import according to your setup
import pyotp

import logzero
from logzero import logger

# Set logging level to high value to ignore all logs
logzero.loglevel(60)  # Higher than CRITICAL

logger.debug("This debug message won't be shown.")
logger.info("This info message won't be shown.")
logger.warning("This warning won't be shown.")
logger.error("This error won't be shown.")
logger.critical("This critical message won't be shown.")

app = Flask(__name__)
load_dotenv()

# Environment variables
broker_api_key = os.getenv('BROKER_API_KEY')
broker_username = os.getenv('BROKER_USERNAME')
broker_pin = os.getenv('BROKER_PIN')
broker_token = os.getenv('BROKER_TOKEN')
login_username = os.getenv('LOGIN_USERNAME')
login_password = os.getenv('LOGIN_PASSWORD')
app.secret_key = os.getenv('APP_KEY')

# SmartConnect object
obj = SmartConnect(api_key=broker_api_key)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        # Render the login form when the route is accessed with GET
        return render_template('login.html')
    elif request.method == 'POST':
        # Process form submission
        username = request.form['username']
        password = request.form['password']
        
        if username == login_username and password == login_password:
            try:
                session['user'] = username 
                # Generate session and fetch tokens
                data = obj.generateSession(broker_username, broker_pin, pyotp.TOTP(broker_token).now())
                refreshToken = data['data']['refreshToken']
                AUTH_TOKEN = data['data']['jwtToken']
                FEED_TOKEN = obj.getfeedToken()
                
                # Display tokens (for educational purposes, adjust as needed)
                return f"Auth Token: {AUTH_TOKEN}<br>Feed Token: {FEED_TOKEN}"
            except Exception as e:
                return jsonify({
                    'status': 'error',
                    'message': str(e)
                })
        else:
            # (implement error messaging as needed)
            return "Invalid credentials", 401
        
@app.route('/logout')
def logout():
    session.pop('user', None)  # Remove 'user' from session
    return redirect(url_for('login'))

@app.route('/placeorder', methods=['POST'])
def place_order():
    try:
        # Extracting form data or JSON data from the POST request
        data = request.json if request.is_json else request.form
        
        # Assigning default values if not provided in the request
        variety = data.get('variety', 'NORMAL')
        producttype = data.get('producttype', 'INTRADAY')
        
        # Building the order parameters dictionary with incoming and default values
        orderparams = {
            "variety": variety,
            "tradingsymbol": data['tradingsymbol'],
            "symboltoken": data['symboltoken'],
            "transactiontype": data['transactiontype'],
            "exchange": data['exchange'],
            "ordertype": "MARKET",  # Assuming ordertype is always MARKET for this example
            "producttype": producttype,
            "duration": "DAY",  # Assuming duration is always DAY for this example
            "price": "0",  # Assuming price is always 0 for MARKET orders
            "squareoff": "0",  # Assuming squareoff is not required for this example
            "stoploss": "0",  # Assuming stoploss is not required for this example
            "quantity": data['quantity']
        }
        
        # Place the order
        orderid = obj.placeOrder(orderparams)
        
        # Return success response with order ID
        return jsonify({
            'status': 'success',
            'message': 'Order placement is successful',
            'orderid': orderid
        })
    except KeyError as e:
        # If any mandatory field is missing in the request
        return jsonify({'status': 'error', 'message': f'Missing mandatory field: {e}'}), 400
    except Exception as e:
        # Handling other exceptions
        return jsonify({
            'status': 'error',
            'message': f"Order placement failed: {e}"
        }), 500


if __name__ == '__main__':
    app.run(debug=True)
