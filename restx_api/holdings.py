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

from .account_schema import HoldingsSchema

load_dotenv()

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('holdings', description='Holdings API')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize schema
holdings_schema = HoldingsSchema()

def format_decimal(value):
    """Format numeric value to 2 decimal places"""
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    return value

def format_holdings_data(holdings_data):
    """Format all numeric values in holdings data to 2 decimal places"""
    if isinstance(holdings_data, list):
        return [
            {
                key: format_decimal(value) if key in ['pnl', 'pnlpercent'] else value
                for key, value in item.items()
            }
            for item in holdings_data
        ]
    return holdings_data

def format_statistics(stats):
    """Format all numeric values in statistics to 2 decimal places"""
    if isinstance(stats, dict):
        return {
            key: format_decimal(value)
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
            'get_holdings': getattr(api_module, 'get_holdings'),
            'map_portfolio_data': getattr(mapping_module, 'map_portfolio_data'),
            'calculate_portfolio_statistics': getattr(mapping_module, 'calculate_portfolio_statistics'),
            'transform_holdings_data': getattr(mapping_module, 'transform_holdings_data')
        }
    except (ImportError, AttributeError) as error:
        logger.error(f"Error importing broker modules: {error}")
        return None

@api.route('/', strict_slashes=False)
class Holdings(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get holdings details"""
        try:
            # Validate request data
            holdings_data = holdings_schema.load(request.json)

            api_key = holdings_data['apikey']
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
                # Get holdings data using broker's implementation
                holdings_data = broker_funcs['get_holdings'](AUTH_TOKEN)
                
                if 'status' in holdings_data and holdings_data['status'] == 'error':
                    return make_response(jsonify({
                        'status': 'error',
                        'message': holdings_data.get('message', 'Error fetching holdings data')
                    }), 500)

                # Transform data using mapping functions
                holdings_data = broker_funcs['map_portfolio_data'](holdings_data)
                portfolio_stats = broker_funcs['calculate_portfolio_statistics'](holdings_data)
                holdings_data = broker_funcs['transform_holdings_data'](holdings_data)
                
                # Format numeric values to 2 decimal places
                formatted_holdings = format_holdings_data(holdings_data)
                formatted_stats = format_statistics(portfolio_stats)
                
                return make_response(jsonify({
                    'status': 'success',
                    'data': {
                        'holdings': formatted_holdings,
                        'statistics': formatted_stats
                    }
                }), 200)
            except Exception as e:
                logger.error(f"Error processing holdings data: {e}")
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
            logger.error(f"Unexpected error in holdings endpoint: {e}")
            traceback.print_exc()
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)
