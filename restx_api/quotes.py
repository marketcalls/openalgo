from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from database.auth_db import get_auth_token_broker
from limiter import limiter
import os
import importlib
import traceback
import logging

from .data_schemas import QuotesSchema

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('quotes', description='Real-time Quotes API')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize schema
quotes_schema = QuotesSchema()

def import_broker_module(broker_name):
    try:
        module_path = f'broker.{broker_name}.api.data'
        broker_module = importlib.import_module(module_path)
        return broker_module
    except ImportError as error:
        logger.error(f"Error importing broker module '{module_path}': {error}")
        return None

@api.route('/', strict_slashes=False)
class Quotes(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get real-time quotes for given symbol"""
        try:
            # Validate request data
            quotes_data = quotes_schema.load(request.json)

            api_key = quotes_data['apikey']
            AUTH_TOKEN, FEED_TOKEN, broker = get_auth_token_broker(api_key, include_feed_token=True)
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
                # Initialize broker's data handler based on broker's requirements
                if hasattr(broker_module.BrokerData.__init__, '__code__'):
                    # Check number of parameters the broker's __init__ accepts
                    param_count = broker_module.BrokerData.__init__.__code__.co_argcount
                    if param_count > 2:  # More than self and auth_token
                        data_handler = broker_module.BrokerData(AUTH_TOKEN, FEED_TOKEN)
                    else:
                        data_handler = broker_module.BrokerData(AUTH_TOKEN)
                else:
                    # Fallback to just auth token if we can't inspect
                    data_handler = broker_module.BrokerData(AUTH_TOKEN)
                    
                quotes = data_handler.get_quotes(
                    quotes_data['symbol'],
                    quotes_data['exchange']
                )
                
                if quotes is None:
                    return make_response(jsonify({
                        'status': 'error',
                        'message': 'Failed to fetch quotes'
                    }), 500)

                return make_response(jsonify({
                    'data': quotes,
                    'status': 'success'
                }), 200)
            except Exception as e:
                logger.error(f"Error in broker_module.get_quotes: {e}")
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
            logger.error(f"Unexpected error in quotes endpoint: {e}")
            traceback.print_exc()
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)
