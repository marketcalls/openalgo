# blueprints/tv_json.py

from flask import Blueprint, render_template, request, jsonify, session, url_for, redirect
from database.symbol import enhanced_search_symbols  # Use the enhanced search function
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
        try:
            symbol_input = request.json.get('symbol')
            exchange = request.json.get('exchange')
            product = request.json.get('product')
            
            if not all([symbol_input, exchange, product]):
                return jsonify({'error': 'Missing required fields'}), 400
            
            api_key = get_api_key(session.get('user'))
            broker = session.get('broker')
            
            # Use enhanced search function
            symbols = enhanced_search_symbols(symbol_input, exchange)
            if not symbols:
                return jsonify({'error': 'Symbol not found'}), 404
            
            symbol_data = symbols[0]  # Take the first match
            
            # Create the JSON response object with OrderedDict
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
            
            return jsonify(json_data)
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    return render_template('tradingview.html', host=host)