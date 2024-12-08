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

from .account_schema import PositionbookSchema

load_dotenv()

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('positionbook', description='Position Book API')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize schema
positionbook_schema = PositionbookSchema()

def format_decimal(value):
    """Format numeric value to 2 decimal places"""
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    return value

def format_position_data(position_data):
    """Format all numeric values in position data to 2 decimal places"""
    if isinstance(position_data, list):
        return [
            {
                key: format_decimal(value) if isinstance(value, (int, float)) else value
                for key, value in item.items()
            }
            for item in position_data
        ]
    return position_data

def import_broker_module(broker_name):
    try:
        # Import API module
        api_module = importlib.import_module(f'broker.{broker_name}.api.order_api')
        # Import mapping module
        mapping_module = importlib.import_module(f'broker.{broker_name}.mapping.order_data')
        return {
            'get_positions': getattr(api_module, 'get_positions'),
            'map_position_data': getattr(mapping_module, 'map_position_data'),
            'transform_positions_data': getattr(mapping_module, 'transform_positions_data')
        }
    except (ImportError, AttributeError) as error:
        logger.error(f"Error importing broker modules: {error}")
        return None

@api.route('/', strict_slashes=False)
class Positionbook(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get position book details"""
        try:
            # Validate request data
            positionbook_data = positionbook_schema.load(request.json)

            api_key = positionbook_data['apikey']
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
                # Get positions data using broker's implementation
                positions_data = broker_funcs['get_positions'](AUTH_TOKEN)
                
                if 'status' in positions_data and positions_data['status'] == 'error':
                    return make_response(jsonify({
                        'status': 'error',
                        'message': positions_data.get('message', 'Error fetching positions data')
                    }), 500)

                # Transform data using mapping functions
                positions_data = broker_funcs['map_position_data'](positions_data)
                positions_data = broker_funcs['transform_positions_data'](positions_data)
                
                # Format numeric values to 2 decimal places
                formatted_positions = format_position_data(positions_data)
                
                return make_response(jsonify({
                    'status': 'success',
                    'data': formatted_positions
                }), 200)
            except Exception as e:
                logger.error(f"Error processing positions data: {e}")
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
            logger.error(f"Unexpected error in positionbook endpoint: {e}")
            traceback.print_exc()
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)
