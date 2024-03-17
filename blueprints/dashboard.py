from flask import Blueprint, render_template, session, redirect, url_for
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

    if AUTH_TOKEN is None:
        return redirect(url_for('auth.logout'))  
        

    api_key = os.getenv('BROKER_API_KEY')
    conn = http.client.HTTPSConnection("apiconnect.angelbroking.com")
    headers = {
        'Authorization': f'Bearer {AUTH_TOKEN}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-UserType': 'USER',
        'X-SourceID': 'WEB',
        'X-ClientLocalIP': 'CLIENT_LOCAL_IP',
        'X-ClientPublicIP': 'CLIENT_PUBLIC_IP',
        'X-MACAddress': 'MAC_ADDRESS',
        'X-PrivateKey': api_key
    }
    conn.request("GET", "/rest/secure/angelbroking/user/v1/getRMS", '', headers)

    res = conn.getresponse()
    data = res.read()
    margin_data = json.loads(data.decode("utf-8"))

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

