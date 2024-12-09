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

from .data_schemas import IntervalsSchema

load_dotenv()

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('intervals', description='Supported Intervals API')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize schema
intervals_schema = IntervalsSchema()

def import_broker_module(broker_name):
    try:
        module_path = f'broker.{broker_name}.api.data'
        broker_module = importlib.import_module(module_path)
        return broker_module
    except ImportError as error:
        logger.error(f"Error importing broker module '{module_path}': {error}")
        return None

@api.route('/', strict_slashes=False)
class Intervals(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get supported intervals for the broker"""
        try:
            # Validate request data
            intervals_data = intervals_schema.load(request.json)

            api_key = intervals_data['apikey']
            AUTH_TOKEN, broker = get_auth_token_broker(api_key)
            if AUTH_TOKEN is None:
                return make_response(jsonify({
                    'status': 'error',
                    'message': 'Invalid openalgo apikey'
                }), 403)

            broker_module = import_broker_module(broker)
            if broker_module is None:
                return make_response(jsonify({
                    'status': 'error',
                    'message': 'Broker-specific module not found'
                }), 404)

            try:
                # Initialize broker's data handler
                data_handler = broker_module.FyersData(AUTH_TOKEN)
                
                # Get supported intervals from the timeframe map
                intervals = {
                    'seconds': sorted([k for k in data_handler.timeframe_map.keys() if k.endswith('s')]),
                    'minutes': sorted([k for k in data_handler.timeframe_map.keys() if k.endswith('m')]),
                    'hours': sorted([k for k in data_handler.timeframe_map.keys() if k.endswith('h')]),
                    'days': ['D'],
                    'weeks': ['W'],
                    'months': ['M']
                }
                
                return make_response(jsonify({
                    'status': 'success',
                    'data': intervals
                }), 200)
            except Exception as e:
                logger.error(f"Error getting supported intervals: {e}")
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
            logger.error(f"Unexpected error in intervals endpoint: {e}")
            traceback.print_exc()
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)
