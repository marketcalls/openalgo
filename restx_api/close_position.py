from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from database.auth_db import get_auth_token_broker
from database.apilog_db import async_log_order, executor
from database.settings_db import get_analyze_mode
from extensions import socketio
from limiter import limiter
import os
from dotenv import load_dotenv
import importlib
import logging
import traceback
import copy

load_dotenv()

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('close_position', description='Close Position API')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Marshmallow schema
from restx_api.schemas import ClosePositionSchema
close_position_schema = ClosePositionSchema()

def import_broker_module(broker_name):
    try:
        module_path = f'broker.{broker_name}.api.order_api'
        broker_module = importlib.import_module(module_path)
        return broker_module
    except ImportError as error:
        logger.error(f"Error importing broker module '{module_path}': {error}")
        return None

@api.route('/', strict_slashes=False)
class ClosePosition(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        try:
            data = request.json
            
            # Early validation of API key before any mode-specific logic
            order_data = close_position_schema.load(data)
            api_key = order_data['apikey']
            AUTH_TOKEN, broker = get_auth_token_broker(api_key)
            
            if AUTH_TOKEN is None:
                error_response = {
                    'status': 'error',
                    'message': 'Invalid openalgo apikey'
                }
                if not get_analyze_mode():
                    executor.submit(async_log_order, 'closeposition', data, error_response)
                return make_response(jsonify(error_response), 403)

            # Check analyze mode and return placeholder if enabled
            if get_analyze_mode():
                return make_response(jsonify({
                    'status': 'info',
                    'message': 'Close Position Analyzer: Implementation in progress',
                    'broker': broker,
                    'mode': 'analyze'
                }), 200)

            # Live Mode - Proceed with actual position closing
            order_request_data = copy.deepcopy(data)
            order_request_data.pop('apikey', None)

            broker_module = import_broker_module(broker)
            if broker_module is None:
                error_response = {
                    'status': 'error',
                    'message': 'Broker-specific module not found'
                }
                executor.submit(async_log_order, 'closeposition', data, error_response)
                return make_response(jsonify(error_response), 404)

            try:
                res, response_data = broker_module.close_position_api(order_data, AUTH_TOKEN)
            except Exception as e:
                logger.error(f"Error in broker_module.close_position_api: {e}")
                traceback.print_exc()
                error_response = {
                    'status': 'error',
                    'message': 'Failed to close position due to internal error'
                }
                executor.submit(async_log_order, 'closeposition', data, error_response)
                return make_response(jsonify(error_response), 500)

            if res.status == 200:
                socketio.emit('close_position_event', {
                    'status': response_data.get('status'),
                    'mode': 'live'
                })
                executor.submit(async_log_order, 'closeposition', order_request_data, response_data)
                return make_response(jsonify(response_data), 200)
            else:
                message = response_data.get('message', 'Failed to close position') if isinstance(response_data, dict) else 'Failed to close position'
                error_response = {
                    'status': 'error',
                    'message': message
                }
                executor.submit(async_log_order, 'closeposition', data, error_response)
                return make_response(jsonify(error_response), res.status if res.status != 200 else 500)

        except ValidationError as err:
            logger.warning(f"Validation error: {err.messages}")
            error_response = {'status': 'error', 'message': err.messages}
            if not get_analyze_mode():
                executor.submit(async_log_order, 'closeposition', data, error_response)
            return make_response(jsonify(error_response), 400)

        except KeyError as e:
            missing_field = str(e)
            logger.error(f"KeyError: Missing field {missing_field}")
            error_response = {
                'status': 'error',
                'message': f"A required field is missing: {missing_field}"
            }
            if not get_analyze_mode():
                executor.submit(async_log_order, 'closeposition', data, error_response)
            return make_response(jsonify(error_response), 400)

        except Exception as e:
            logger.error("An unexpected error occurred in ClosePosition endpoint.")
            traceback.print_exc()
            error_response = {
                'status': 'error',
                'message': 'An unexpected error occurred'
            }
            if not get_analyze_mode():
                executor.submit(async_log_order, 'closeposition', data, error_response)
            return make_response(jsonify(error_response), 500)
