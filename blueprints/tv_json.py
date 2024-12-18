# blueprints/tv_json.py

from flask import Blueprint, render_template, request, jsonify, session, url_for, redirect
from database.symbol import enhanced_search_symbols
from database.auth_db import get_api_key_for_tradingview
from utils.session import check_session_validity
from collections import OrderedDict
import os
import logging

logger = logging.getLogger(__name__)

host = os.getenv('HOST_SERVER')

tv_json_bp = Blueprint('tv_json_bp', __name__, url_prefix='/tradingview')

@tv_json_bp.route('/', methods=['GET', 'POST'])
@check_session_validity
def tradingview_json():
    if request.method == 'POST':
        try:
            symbol_input = request.json.get('symbol')
            exchange = request.json.get('exchange')
            product = request.json.get('product')
            
            if not all([symbol_input, exchange, product]):
                logger.error("Missing required fields in TradingView request")
                return jsonify({'error': 'Missing required fields'}), 400
            
            logger.info(f"Processing TradingView request - Symbol: {symbol_input}, Exchange: {exchange}, Product: {product}")
            
            # Get actual API key for TradingView
            api_key = get_api_key_for_tradingview(session.get('user'))
            broker = session.get('broker')
            
            if not api_key:
                logger.error(f"API key not found for user: {session.get('user')}")
                return jsonify({'error': 'API key not found'}), 404
            
            # Use enhanced search function
            symbols = enhanced_search_symbols(symbol_input, exchange)
            if not symbols:
                logger.warning(f"Symbol not found: {symbol_input}")
                return jsonify({'error': 'Symbol not found'}), 404
            
            symbol_data = symbols[0]  # Take the first match
            logger.info(f"Found matching symbol: {symbol_data.symbol}")
            
            # Create the JSON response object with OrderedDict
            json_data = OrderedDict([
                ("apikey", api_key),  # Use actual API key
                ("strategy", "Tradingview"),
                ("symbol", symbol_data.symbol),
                ("action", "{{strategy.order.action}}"),
                ("exchange", symbol_data.exchange),
                ("pricetype", "MARKET"),
                ("product", product),
                ("quantity", "{{strategy.order.contracts}}"),
                ("position_size", "{{strategy.position_size}}"),
            ])
            
            logger.info("Successfully generated TradingView webhook data")
            return jsonify(json_data)
            
        except Exception as e:
            logger.error(f"Error processing TradingView request: {str(e)}")
            return jsonify({'error': str(e)}), 500
    
    return render_template('tradingview.html', host=host)
