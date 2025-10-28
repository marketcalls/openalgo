from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from limiter import limiter
import os

from .data_schemas import OptionGreeksSchema
from services.option_greeks_service import get_option_greeks
from database.auth_db import verify_api_key
from utils.logging import get_logger

logger = get_logger(__name__)

# Rate limit for option greeks API
GREEKS_RATE_LIMIT = os.getenv("GREEKS_RATE_LIMIT", "30 per minute")

api = Namespace('optiongreeks', description='Option Greeks API')

# Initialize schema
option_greeks_schema = OptionGreeksSchema()


@api.route('', strict_slashes=False)
class OptionGreeks(Resource):
    @limiter.limit(GREEKS_RATE_LIMIT)
    def post(self):
        """
        Calculate Option Greeks (Delta, Gamma, Theta, Vega, Rho) and Implied Volatility

        This endpoint calculates option Greeks using Black-Scholes model for options
        across all supported exchanges (NFO, BFO, CDS, MCX).

        Required fields:
        - apikey: API key for authentication
        - symbol: Option symbol (e.g., NIFTY28NOV2424000CE)
        - exchange: Exchange code (NFO, BFO, CDS, MCX)

        Optional fields:
        - interest_rate: Risk-free interest rate (annualized %). Defaults to 6.5%

        Example Request:
        {
            "apikey": "your_api_key",
            "symbol": "NIFTY28NOV2424000CE",
            "exchange": "NFO",
            "interest_rate": 6.5
        }

        Example Response:
        {
            "status": "success",
            "symbol": "NIFTY28NOV2424000CE",
            "exchange": "NFO",
            "underlying": "NIFTY",
            "strike": 24000,
            "option_type": "CE",
            "expiry_date": "28-Nov-2024",
            "days_to_expiry": 5.5,
            "spot_price": 24015.75,
            "option_price": 125.50,
            "interest_rate": 6.5,
            "implied_volatility": 15.25,
            "greeks": {
                "delta": 0.5234,
                "gamma": 0.000125,
                "theta": -12.5678,
                "vega": 18.7654,
                "rho": 0.001234
            }
        }
        """
        try:
            # Get request data
            data = request.json

            if data is None:
                return make_response(jsonify({
                    'status': 'error',
                    'message': 'Request body is missing or invalid JSON'
                }), 400)

            # Validate request data
            try:
                validated_data = option_greeks_schema.load(data)
            except ValidationError as err:
                logger.warning(f"Validation error in option greeks request: {err.messages}")
                return make_response(jsonify({
                    'status': 'error',
                    'message': 'Validation failed',
                    'errors': err.messages
                }), 400)

            # Extract validated data
            api_key = validated_data.get('apikey')
            symbol = validated_data.get('symbol')
            exchange = validated_data.get('exchange')
            interest_rate = validated_data.get('interest_rate')
            underlying_symbol = validated_data.get('underlying_symbol')
            underlying_exchange = validated_data.get('underlying_exchange')
            expiry_time = validated_data.get('expiry_time')

            # Verify API key
            if not verify_api_key(api_key):
                logger.warning(f"Invalid API key used for option greeks: {api_key[:10]}...")
                return make_response(jsonify({
                    'status': 'error',
                    'message': 'Invalid openalgo apikey'
                }), 401)

            # Get option Greeks
            logger.info(f"Calculating Greeks for {symbol} on {exchange}")
            if underlying_symbol:
                logger.info(f"Using custom underlying: {underlying_symbol} on {underlying_exchange or 'auto-detected'}")
            if expiry_time:
                logger.info(f"Using custom expiry time: {expiry_time}")

            success, response, status_code = get_option_greeks(
                option_symbol=symbol,
                exchange=exchange,
                interest_rate=interest_rate,
                underlying_symbol=underlying_symbol,
                underlying_exchange=underlying_exchange,
                expiry_time=expiry_time,
                api_key=api_key
            )

            if success:
                logger.info(f"Greeks calculated successfully: {symbol}")
            else:
                logger.error(f"Failed to calculate Greeks: {response.get('message')}")

            return make_response(jsonify(response), status_code)

        except Exception as e:
            logger.exception(f"Unexpected error in option greeks endpoint: {e}")
            return make_response(jsonify({
                'status': 'error',
                'message': 'Internal server error while calculating option Greeks'
            }), 500)
