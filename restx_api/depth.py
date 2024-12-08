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

from .data_schemas import DepthSchema

load_dotenv()

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('depth', description='Market Depth API')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize schema
depth_schema = DepthSchema()

def import_broker_module(broker_name):
    try:
        module_path = f'broker.{broker_name}.api.data'
        broker_module = importlib.import_module(module_path)
        return broker_module
    except ImportError as error:
        logger.error(f"Error importing broker module '{module_path}': {error}")
        return None

@api.route('/', strict_slashes=False)
class Depth(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get market depth for given symbol"""
        try:
            # Validate request data
            depth_data = depth_schema.load(request.json)

            api_key = depth_data['apikey']
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
                depth = data_handler.get_depth(
                    depth_data['symbol'],
                    depth_data['exchange']
                )
                
                return make_response(jsonify({
                    'status': 'success',
                    'data': depth
                }), 200)
            except Exception as e:
                logger.error(f"Error in broker_module.get_depth: {e}")
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
            logger.error(f"Unexpected error in depth endpoint: {e}")
            traceback.print_exc()
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)
