from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from database.auth_db import get_auth_token_broker
from limiter import limiter
import os
from dotenv import load_dotenv
import importlib
import traceback
import logging

from .account_schema import TradebookSchema

load_dotenv()

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('tradebook', description='Trade Book API')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize schema
tradebook_schema = TradebookSchema()

def format_decimal(value):
    """Format numeric value to 2 decimal places"""
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    return value

def format_trade_data(trade_data):
    """Format all numeric values in trade data to 2 decimal places"""
    if isinstance(trade_data, list):
        return [
            {
                key: format_decimal(value) if isinstance(value, (int, float)) else value
                for key, value in item.items()
            }
            for item in trade_data
        ]
    return trade_data

def import_broker_module(broker_name):
    try:
        # Import API module
        api_module = importlib.import_module(f'broker.{broker_name}.api.order_api')
        # Import mapping module
        mapping_module = importlib.import_module(f'broker.{broker_name}.mapping.order_data')
        return {
            'get_trade_book': getattr(api_module, 'get_trade_book'),
            'map_trade_data': getattr(mapping_module, 'map_trade_data'),
            'transform_tradebook_data': getattr(mapping_module, 'transform_tradebook_data')
        }
    except (ImportError, AttributeError) as error:
        logger.error(f"Error importing broker modules: {error}")
        return None

@api.route('/', strict_slashes=False)
class Tradebook(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get trade book details"""
        try:
            # Validate request data
            tradebook_data = tradebook_schema.load(request.json)

            api_key = tradebook_data['apikey']
            AUTH_TOKEN, broker = get_auth_token_broker(api_key)
            if AUTH_TOKEN is None:
                return make_response(jsonify({
                    'status': 'error',
                    'message': 'Invalid openalgo apikey'
                }), 403)

            broker_funcs = import_broker_module(broker)
            if broker_funcs is None:
                return make_response(jsonify({
                    'status': 'error',
                    'message': 'Broker-specific module not found'
                }), 404)

            try:
                # Get tradebook data using broker's implementation
                trade_data = broker_funcs['get_trade_book'](AUTH_TOKEN)
                
                if 'status' in trade_data and trade_data['status'] == 'error':
                    return make_response(jsonify({
                        'status': 'error',
                        'message': trade_data.get('message', 'Error fetching trade data')
                    }), 500)

                # Transform data using mapping functions
                trade_data = broker_funcs['map_trade_data'](trade_data=trade_data)
                trade_data = broker_funcs['transform_tradebook_data'](trade_data)
                
                # Format numeric values to 2 decimal places
                formatted_trades = format_trade_data(trade_data)
                
                return make_response(jsonify({
                    'status': 'success',
                    'data': formatted_trades
                }), 200)
            except Exception as e:
                logger.error(f"Error processing trade data: {e}")
                traceback.print_exc()
                return make_response(jsonify({
                    'status': 'error',
                    'message': str(e)
                }), 500)

        except ValidationError as err:
            return make_response(jsonify({
                'status': 'error',
                'message': err.messages
            }), 400)
        except Exception as e:
            logger.error(f"Unexpected error in tradebook endpoint: {e}")
            traceback.print_exc()
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)
