from flask import Blueprint, render_template, session, redirect, url_for, jsonify
from database.auth_db import get_auth_token
import os 
import http.client
import json 


dashboard_bp = Blueprint('dashboard_bp', __name__, url_prefix='/')

@dashboard_bp.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))  
    
    login_username = os.getenv('LOGIN_USERNAME')

    AUTH_TOKEN = get_auth_token(login_username)

    api_key = os.getenv('BROKER_API_KEY')
    conn = http.client.HTTPSConnection("api.upstox.com")
    headers = {
        'Authorization': f'Bearer {AUTH_TOKEN}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
       
    }
    conn.request("GET", "/v2/user/get-funds-and-margin", '', headers)

    res = conn.getresponse()
    data = res.read()
    margin_data = json.loads(data.decode("utf-8"))

    print(f'margin data : {margin_data}')

    if margin_data.get('status') == 'error':
        # Log the error or inform the user
        print(f"Error fetching margin data: {margin_data.get('errors')}")
        # Return an appropriate response or render a template with an error message
        return render_template('dashboard_error.html', margin_data={})


    # Calculate the sum of available_margin and used_margin
    total_available_margin = sum([
        margin_data['data']['commodity']['available_margin'],
        margin_data['data']['equity']['available_margin']
    ])
    total_used_margin = sum([
        margin_data['data']['commodity']['used_margin'],
        margin_data['data']['equity']['used_margin']
    ])

    # Construct the final JSON output
    margin_data = {
        "status": True,
        "message": "SUCCESS",
        "errorcode": "",
        "data": {
            "availablecash": str(total_available_margin),
            "collateral": "0",
            "m2munrealized": "0",
            "m2mrealized": "0",
            "utiliseddebits": str(total_used_margin),
        }
    }

    

    # Check if 'data' key exists and is not None
    if margin_data.get('data') is not None:
        # Process the data as required
        for key, value in margin_data['data'].items():
            if value is not None and isinstance(value, str):
                try:
                    margin_data['data'][key] = "{:.2f}".format(float(value))
                except ValueError:
                    pass
        return render_template('dashboard.html', margin_data=margin_data['data'])
    else:
        # Handle the case where 'data' is None or doesn't exist
        # You can pass an empty dictionary or a placeholder to indicate no data is available
        return render_template('dashboard.html', margin_data={})

