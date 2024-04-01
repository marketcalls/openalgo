# blueprints/tv_json.py

from flask import Blueprint, render_template, request, jsonify, session, url_for, redirect
from database.tv_search import search_symbols
from database.auth_db import get_api_key
from collections import OrderedDict
from dotenv import load_dotenv
import os

load_dotenv()

host = os.getenv('HOST_SERVER')

tv_json_bp = Blueprint('tv_json_bp', __name__, url_prefix='/tradingview')

@tv_json_bp.route('/', methods=['GET', 'POST'])
def tradingview_json():
    
    if not session.get('logged_in'):
        return redirect(url_for('auth_bp.login'))
    
    if request.method == 'POST':
        symbol_input = request.json.get('symbol')  # Changed to request.json to get data from JSON payload
        exchange = request.json.get('exchange')
        product = request.json.get('product')
        api_key = get_api_key(session.get('user'))  # Make sure 'user_id' is correctly set in session
        
        broker = session['broker']
        # Search for the symbol in the database to get the exchange segment
        symbols = search_symbols(symbol_input,exchange)
        if not symbols:
            return jsonify({'error': 'Symbol not found'}), 404
        symbol_data = symbols[0]  # Take the first match
        

        # Create the JSON response object
        # Create an OrderedDict with the keys in the desired order
        json_data = OrderedDict([
            ("apikey", api_key),
            ("strategy", "Tradingview"),
            ("symbol", symbol_data.symbol),
            ("action", "{{strategy.order.action}}"),
            ("exchange", symbol_data.exchange),
            ("pricetype", "MARKET"),
            ("product", product),
            ("quantity", "{{strategy.order.contracts}}"),
            ("position_size", "{{strategy.position_size}}"),
        ])
        
        # JSONify the ordered dict
        response = jsonify(json_data)
        response.headers.add('Content-Type', 'application/json')
        return response
    
    return render_template('tradingview.html',host=host)
