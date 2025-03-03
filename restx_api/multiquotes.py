from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from database.auth_db import get_auth_token_broker
from limiter import limiter
import os
import importlib
import traceback
import logging
import concurrent.futures

from .data_schemas import MultiQuotesSchema

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('multiquotes', description='Multi-Symbol Real-time Quotes API')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize schema
multiquotes_schema = MultiQuotesSchema()

def import_broker_module(broker_name):
    try:
        module_path = f'broker.{broker_name}.api.data'
        broker_module = importlib.import_module(module_path)
        return broker_module
    except ImportError as error:
        logger.error(f"Error importing broker module '{module_path}': {error}")
        return None

@api.route('/', strict_slashes=False)
class MultiQuotes(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get real-time quotes for multiple symbols"""
        try:
            # Validate request data
            multiquotes_data = multiquotes_schema.load(request.json)

            api_key = multiquotes_data['apikey']
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
                data_handler = broker_module.BrokerData(AUTH_TOKEN)
                
                symbols = multiquotes_data['symbols']
                exchanges = multiquotes_data['exchanges']
                
                # Validate input lists
                if len(symbols) != len(exchanges):
                    return make_response(jsonify({
                        'status': 'error',
                        'message': 'The number of symbols must match the number of exchanges'
                    }), 400)
                
                # Use ThreadPoolExecutor to fetch quotes in parallel
                quotes_result = {}
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(10, len(symbols))) as executor:
                    # Create a dictionary to map future to symbol for tracking
                    future_to_symbol = {
                        executor.submit(data_handler.get_quotes, symbol, exchange): (symbol, exchange)
                        for symbol, exchange in zip(symbols, exchanges)
                    }
                    
                    for future in concurrent.futures.as_completed(future_to_symbol):
                        symbol, exchange = future_to_symbol[future]
                        key = f"{exchange}:{symbol}"
                        try:
                            quote = future.result()
                            quotes_result[key] = quote
                        except Exception as e:
                            quotes_result[key] = {
                                'error': str(e),
                                'ltp': 0,
                                'open': 0,
                                'high': 0,
                                'low': 0,
                                'volume': 0,
                                'bid': 0,
                                'ask': 0,
                                'prev_close': 0
                            }
                
                if not quotes_result:
                    return make_response(jsonify({
                        'status': 'error',
                        'message': 'Failed to fetch quotes for all symbols'
                    }), 500)

                return make_response(jsonify({
                    'data': quotes_result,
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
            logger.error(f"Unexpected error in multiquotes endpoint: {e}")
            traceback.print_exc()
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)
