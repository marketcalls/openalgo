from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from database.auth_db import get_auth_token_broker
from database.symbol import SymToken, db_session
from limiter import limiter
import os
import traceback
import logging
from sqlalchemy.orm.exc import NoResultFound

from .data_schemas import SymbolSchema

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('symbol', description='Symbol information API')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize schema
symbol_schema = SymbolSchema()

@api.route('/', strict_slashes=False)
class Symbol(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get symbol information for a given symbol and exchange"""
        try:
            # Validate request data
            symbol_data = symbol_schema.load(request.json)

            api_key = symbol_data['apikey']
            symbol = symbol_data['symbol']
            exchange = symbol_data['exchange']
            
            # Verify API key
            AUTH_TOKEN, broker = get_auth_token_broker(api_key)
            if AUTH_TOKEN is None:
                return make_response(jsonify({
                    'status': 'error',
                    'message': 'Invalid openalgo apikey'
                }), 403)

            try:
                # Query the database for the symbol
                result = db_session.query(SymToken).filter(
                    SymToken.symbol == symbol,
                    SymToken.exchange == exchange
                ).first()
                
                if result is None:
                    return make_response(jsonify({
                        'status': 'error',
                        'message': f'Symbol {symbol} not found in exchange {exchange}'
                    }), 404)
                
                # Transform the SymToken object to a dictionary
                symbol_info = {
                    'id': result.id,
                    'symbol': result.symbol,
                    'brsymbol': result.brsymbol,
                    'name': result.name,
                    'exchange': result.exchange,
                    'brexchange': result.brexchange,
                    'token': result.token,
                    'expiry': result.expiry,
                    'strike': result.strike,
                    'lotsize': result.lotsize,
                    'instrumenttype': result.instrumenttype,
                    'tick_size': result.tick_size
                }
                
                return make_response(jsonify({
                    'data': symbol_info,
                    'status': 'success'
                }), 200)
                
            except NoResultFound:
                return make_response(jsonify({
                    'status': 'error',
                    'message': f'Symbol {symbol} not found in exchange {exchange}'
                }), 404)
                
            except Exception as e:
                logger.error(f"Error retrieving symbol information: {e}")
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
            logger.error(f"Unexpected error in symbol endpoint: {e}")
            traceback.print_exc()
            return make_response(jsonify({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }), 500)
