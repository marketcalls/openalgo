from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from database.auth_db import get_auth_token_broker, Auth, db_session, verify_api_key
from limiter import limiter
import os
import importlib
import traceback
import logging

from .data_schemas import DepthSchema

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
            auth_info = get_auth_token_broker(api_key, include_feed_token=True)
            if len(auth_info) == 3:
                AUTH_TOKEN, FEED_TOKEN, broker = auth_info
            else:
                return make_response(jsonify({
                    'status': 'error',
                    'message': 'Invalid openalgo apikey'
                }), 403)

            # Get user_id from auth database
            user_id = None
            try:
                user_id = verify_api_key(api_key)  # Get the actual user_id from API key
                if user_id:
                    auth_obj = Auth.query.filter_by(name=user_id).first()  # Query using user_id instead of api_key
                    if auth_obj and auth_obj.user_id:
                        user_id = auth_obj.user_id
            except Exception as e:
                logger.warning(f"Could not fetch user_id: {e}")

            broker_module = import_broker_module(broker)
            if broker_module is None:
                return make_response(jsonify({
                    'status': 'error',
                    'message': 'Broker-specific module not found'
                }), 404)

            try:
                # Initialize broker's data handler based on broker's requirements
                if hasattr(broker_module.BrokerData.__init__, '__code__'):
                    # Check number of parameters the broker's __init__ accepts
                    param_count = broker_module.BrokerData.__init__.__code__.co_argcount
                    if param_count > 3:  # More than self, auth_token, and feed_token
                        data_handler = broker_module.BrokerData(AUTH_TOKEN, FEED_TOKEN, user_id)
                    elif param_count > 2:  # More than self and auth_token
                        data_handler = broker_module.BrokerData(AUTH_TOKEN, FEED_TOKEN)
                    else:
                        data_handler = broker_module.BrokerData(AUTH_TOKEN)
                else:
                    # Fallback to just auth token if we can't inspect
                    data_handler = broker_module.BrokerData(AUTH_TOKEN)
                depth = data_handler.get_depth(
                    depth_data['symbol'],
                    depth_data['exchange']
                )
                
                if depth is None:
                    return make_response(jsonify({
                        'status': 'error',
                        'message': 'Failed to fetch market depth'
                    }), 500)

                return make_response(jsonify({
                    'data': depth,
                    'status': 'success'
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
