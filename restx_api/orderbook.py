from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from database.auth_db import get_auth_token_broker
from limiter import limiter
import os
import importlib
import traceback
import logging

from .account_schema import OrderbookSchema

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('orderbook', description='Order Book API')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize schema
orderbook_schema = OrderbookSchema()

def format_decimal(value):
    """Format numeric value to 2 decimal places"""
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    return value

def format_order_data(order_data):
    """Format all numeric values in order data to 2 decimal places"""
    if isinstance(order_data, list):
        return [
            {
                key: format_decimal(value) if isinstance(value, (int, float)) else value
                for key, value in item.items()
            }
            for item in order_data
        ]
    return order_data

def format_statistics(stats):
    """Format all numeric values in statistics to 2 decimal places"""
    if isinstance(stats, dict):
        return {
            key: format_decimal(value) if isinstance(value, (int, float)) else value
            for key, value in stats.items()
        }
    return stats

def import_broker_module(broker_name):
    try:
        # Import API module
        api_module = importlib.import_module(f'broker.{broker_name}.api.order_api')
        # Import mapping module
        mapping_module = importlib.import_module(f'broker.{broker_name}.mapping.order_data')
        return {
            'get_order_book': getattr(api_module, 'get_order_book'),
            'map_order_data': getattr(mapping_module, 'map_order_data'),
            'calculate_order_statistics': getattr(mapping_module, 'calculate_order_statistics'),
            'transform_order_data': getattr(mapping_module, 'transform_order_data')
        }
    except (ImportError, AttributeError) as error:
        logger.error(f"Error importing broker modules: {error}")
        return None

@api.route('/', strict_slashes=False)
class Orderbook(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get order book details"""
        try:
            # Validate request data
            orderbook_data = orderbook_schema.load(request.json)

            api_key = orderbook_data['apikey']
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
                # Get orderbook data using broker's implementation
                order_data = broker_funcs['get_order_book'](AUTH_TOKEN)
                
                if 'status' in order_data and order_data['status'] == 'error':
                    return make_response(jsonify({
                        'status': 'error',
                        'message': order_data.get('message', 'Error fetching order data')
                    }), 500)

                # Transform data using mapping functions
                order_data = broker_funcs['map_order_data'](order_data=order_data)
                order_stats = broker_funcs['calculate_order_statistics'](order_data)
                order_data = broker_funcs['transform_order_data'](order_data)
                
                # Format numeric values to 2 decimal places
                formatted_orders = format_order_data(order_data)
                formatted_stats = format_statistics(order_stats)
                
                return make_response(jsonify({
                    'status': 'success',
                    'data': {
                        'orders': formatted_orders,
                        'statistics': formatted_stats
                    }
                }), 200)
            except Exception as e:
                logger.error(f"Error processing order data: {e}")
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
            logger.error(f"Unexpected error in orderbook endpoint: {e}")
            traceback.print_exc()
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)
