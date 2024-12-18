from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from database.auth_db import get_auth_token_broker
from limiter import limiter
import os
import importlib
import traceback
import logging

from .account_schema import FundsSchema

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('funds', description='Account Funds API')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize schema
funds_schema = FundsSchema()

def import_broker_module(broker_name):
    try:
        module_path = f'broker.{broker_name}.api.funds'
        broker_module = importlib.import_module(module_path)
        return broker_module
    except ImportError as error:
        logger.error(f"Error importing broker module '{module_path}': {error}")
        return None

@api.route('/', strict_slashes=False)
class Funds(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get account funds and margin details"""
        try:
            # Validate request data
            funds_data = funds_schema.load(request.json)

            api_key = funds_data['apikey']
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
                # Get funds data using broker's implementation
                funds = broker_module.get_margin_data(AUTH_TOKEN)
                
                return make_response(jsonify({
                    'status': 'success',
                    'data': funds
                }), 200)
            except Exception as e:
                logger.error(f"Error in broker_module.get_margin_data: {e}")
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
            logger.error(f"Unexpected error in funds endpoint: {e}")
            traceback.print_exc()
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)
