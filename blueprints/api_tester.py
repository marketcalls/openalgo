from flask import Blueprint, render_template, request, jsonify, session
from functools import wraps
import json
import os
from database.auth_db import get_api_key_for_tradingview
from utils.session import check_session_validity
from utils.logging import get_logger

logger = get_logger(__name__)

api_tester_bp = Blueprint('api_tester', __name__, url_prefix='/api-tester')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated_function

@api_tester_bp.route('/')
@check_session_validity
def index():
    """Render the API tester page"""
    login_username = session.get('user')
    # Get the decrypted API key if it exists
    api_key = get_api_key_for_tradingview(login_username) if login_username else None
    logger.info(f"API Tester accessed by user: {login_username}")
    return render_template('api_tester.html', 
                         login_username=login_username,
                         api_key=api_key or '')

@api_tester_bp.route('/api-key')
@check_session_validity
def get_api_key():
    """Get the current user's API key"""
    login_username = session.get('user')
    if not login_username:
        return jsonify({'error': 'Not authenticated'}), 401
    
    api_key = get_api_key_for_tradingview(login_username)
    return jsonify({'api_key': api_key or ''})

@api_tester_bp.route('/collections')
@check_session_validity
def get_collections():
    """Get all available API collections"""
    collections = []
    
    # Load Postman collection
    postman_path = os.path.join('collections', 'postman', 'openalgo.postman_collection.json')
    if os.path.exists(postman_path):
        with open(postman_path, 'r') as f:
            postman_data = json.load(f)
            collections.append({
                'name': 'Postman Collection',
                'type': 'postman',
                'data': postman_data
            })
    
    # Load Bruno collection
    bruno_path = os.path.join('collections', 'openalgo_bruno.json')
    if os.path.exists(bruno_path):
        with open(bruno_path, 'r') as f:
            bruno_data = json.load(f)
            collections.append({
                'name': 'Bruno Collection',
                'type': 'bruno',
                'data': bruno_data
            })
    
    return jsonify(collections)

@api_tester_bp.route('/endpoints')
@check_session_validity
def get_endpoints():
    """Get structured list of all API endpoints"""
    endpoints = {
        'account': [
            {
                'name': 'Analyzer Status',
                'method': 'POST',
                'path': '/api/v1/analyzer',
                'body': {'apikey': ''}
            },
            {
                'name': 'Analyzer Toggle',
                'method': 'POST',
                'path': '/api/v1/analyzer/toggle',
                'body': {'apikey': '', 'mode': False}
            },
            {
                'name': 'Funds',
                'method': 'POST',
                'path': '/api/v1/funds',
                'body': {'apikey': ''}
            },
            {
                'name': 'Orderbook',
                'method': 'POST',
                'path': '/api/v1/orderbook',
                'body': {'apikey': ''}
            },
            {
                'name': 'Tradebook',
                'method': 'POST',
                'path': '/api/v1/tradebook',
                'body': {'apikey': ''}
            },
            {
                'name': 'Positionbook',
                'method': 'POST',
                'path': '/api/v1/positionbook',
                'body': {'apikey': ''}
            },
            {
                'name': 'Holdings',
                'method': 'POST',
                'path': '/api/v1/holdings',
                'body': {'apikey': ''}
            }
        ],
        'orders': [
            {
                'name': 'Place Order',
                'method': 'POST',
                'path': '/api/v1/placeorder',
                'body': {
                    'apikey': '',
                    'strategy': 'Test Strategy',
                    'symbol': 'SBIN',
                    'action': 'BUY',
                    'exchange': 'NSE',
                    'pricetype': 'MARKET',
                    'product': 'MIS',
                    'quantity': '1'
                }
            },
            {
                'name': 'Place Smart Order',
                'method': 'POST',
                'path': '/api/v1/placesmartorder',
                'body': {
                    'apikey': '',
                    'strategy': 'Test Strategy',
                    'exchange': 'NSE',
                    'symbol': 'SBIN',
                    'action': 'BUY',
                    'product': 'MIS',
                    'pricetype': 'MARKET',
                    'quantity': '1',
                    'position_size': '5000'
                }
            },
            {
                'name': 'Basket Order',
                'method': 'POST',
                'path': '/api/v1/basketorder',
                'body': {
                    'apikey': '',
                    'strategy': 'Test Strategy',
                    'orders': [
                        {
                            'symbol': 'SBIN',
                            'exchange': 'NSE',
                            'action': 'BUY',
                            'quantity': '1',
                            'pricetype': 'MARKET',
                            'product': 'MIS'
                        }
                    ]
                }
            },
            {
                'name': 'Split Order',
                'method': 'POST',
                'path': '/api/v1/splitorder',
                'body': {
                    'apikey': '',
                    'strategy': 'Test Strategy',
                    'exchange': 'NSE',
                    'symbol': 'SBIN',
                    'action': 'BUY',
                    'quantity': '100',
                    'splitsize': '20',
                    'pricetype': 'MARKET',
                    'product': 'MIS'
                }
            },
            {
                'name': 'Modify Order',
                'method': 'POST',
                'path': '/api/v1/modifyorder',
                'body': {
                    'apikey': '',
                    'strategy': 'Test Strategy',
                    'symbol': 'SBIN',
                    'action': 'BUY',
                    'exchange': 'NSE',
                    'orderid': '',
                    'product': 'MIS',
                    'pricetype': 'LIMIT',
                    'price': '100',
                    'quantity': '1',
                    'disclosed_quantity': '0',
                    'trigger_price': '0'
                }
            },
            {
                'name': 'Cancel Order',
                'method': 'POST',
                'path': '/api/v1/cancelorder',
                'body': {
                    'apikey': '',
                    'strategy': 'Test Strategy',
                    'orderid': ''
                }
            },
            {
                'name': 'Cancel All Orders',
                'method': 'POST',
                'path': '/api/v1/cancelallorder',
                'body': {
                    'apikey': '',
                    'strategy': 'Test Strategy'
                }
            },
            {
                'name': 'Close Position',
                'method': 'POST',
                'path': '/api/v1/closeposition',
                'body': {
                    'apikey': '',
                    'strategy': 'Test Strategy'
                }
            },
            {
                'name': 'Order Status',
                'method': 'POST',
                'path': '/api/v1/orderstatus',
                'body': {
                    'apikey': '',
                    'strategy': 'Test Strategy',
                    'orderid': ''
                }
            },
            {
                'name': 'Open Position',
                'method': 'POST',
                'path': '/api/v1/openposition',
                'body': {
                    'apikey': '',
                    'strategy': 'Test Strategy',
                    'symbol': 'SBIN',
                    'exchange': 'NSE',
                    'product': 'MIS'
                }
            }
        ],
        'data': [
            {
                'name': 'Quotes',
                'method': 'POST',
                'path': '/api/v1/quotes',
                'body': {
                    'apikey': '',
                    'symbol': 'SBIN',
                    'exchange': 'NSE'
                }
            },
            {
                'name': 'Depth',
                'method': 'POST',
                'path': '/api/v1/depth',
                'body': {
                    'apikey': '',
                    'symbol': 'SBIN',
                    'exchange': 'NSE'
                }
            },
            {
                'name': 'History',
                'method': 'POST',
                'path': '/api/v1/history',
                'body': {
                    'apikey': '',
                    'symbol': 'SBIN',
                    'exchange': 'NSE',
                    'interval': '1d',
                    'start_date': '2025-01-01',
                    'end_date': '2025-01-31'
                }
            },
            {
                'name': 'Intervals',
                'method': 'POST',
                'path': '/api/v1/intervals',
                'body': {'apikey': ''}
            },
            {
                'name': 'Symbol',
                'method': 'POST',
                'path': '/api/v1/symbol',
                'body': {
                    'apikey': '',
                    'symbol': 'SBIN',
                    'exchange': 'NSE'
                }
            },
            {
                'name': 'Search',
                'method': 'POST',
                'path': '/api/v1/search',
                'body': {
                    'apikey': '',
                    'query': 'SBIN',
                    'exchange': 'NSE'
                }
            },
            {
                'name': 'Expiry',
                'method': 'POST',
                'path': '/api/v1/expiry',
                'body': {
                    'apikey': '',
                    'symbol': 'NIFTY',
                    'exchange': 'NFO',
                    'instrumenttype': 'options'
                }
            },
            {
                'name': 'Option Symbol',
                'method': 'POST',
                'path': '/api/v1/optionsymbol',
                'body': {
                    'apikey': '',
                    'strategy': 'Test Strategy',
                    'underlying': 'NIFTY',
                    'exchange': 'NSE_INDEX',
                    'expiry_date': '28NOV24',
                    'strike_int': 50,
                    'offset': 'ATM',
                    'option_type': 'CE'
                }
            },
            {
                'name': 'Option Greeks',
                'method': 'POST',
                'path': '/api/v1/optiongreeks',
                'body': {
                    'apikey': '',
                    'symbol': 'NIFTY28NOV2426000CE',
                    'exchange': 'NFO'
                }
            },
            {
                'name': 'Ticker',
                'method': 'GET',
                'path': '/api/v1/ticker/NSE:SBIN',
                'params': {
                    'apikey': '',
                    'interval': 'D',
                    'from': '2025-01-01',
                    'to': '2025-01-31',
                    'format': 'json'
                },
                'description': 'Historical OHLCV data. Symbol in path as exchange:symbol (e.g., NSE:SBIN)'
            }
        ],
        'utilities': [
            {
                'name': 'Ping',
                'method': 'POST',
                'path': '/api/v1/ping',
                'body': {'apikey': ''}
            },
            {
                'name': 'Instruments',
                'method': 'GET',
                'path': '/api/v1/instruments',
                'params': {
                    'apikey': '',
                    'exchange': 'NSE',
                    'format': 'json'
                },
                'description': 'Download instruments. Leave exchange empty for all exchanges, or specify: NSE, BSE, NFO, BFO, MCX, etc.'
            },
            {
                'name': 'Margin Calculator',
                'method': 'POST',
                'path': '/api/v1/margin',
                'body': {
                    'apikey': '',
                    'positions': [
                        {
                            'symbol': 'SBIN',
                            'exchange': 'NSE',
                            'action': 'BUY',
                            'product': 'MIS',
                            'pricetype': 'LIMIT',
                            'quantity': '10',
                            'price': '750.50',
                            'trigger_price': '0'
                        }
                    ]
                }
            }
        ]
    }
    
    return jsonify(endpoints)
