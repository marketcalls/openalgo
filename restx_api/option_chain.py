"""
Option Chain API Endpoint

POST /api/v1/optionchain

Fetches option chain data with real-time quotes for strikes.
Each CE and PE option includes its own label (ATM, ITM1, ITM2, OTM1, OTM2, etc.).

Request Body:
{
    "apikey": "your_api_key",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "30DEC25",
    "strike_count": 10  // Optional: if not provided, returns entire chain
}

Response:
{
    "status": "success",
    "underlying": "NIFTY",
    "underlying_ltp": 24250.50,
    "expiry_date": "30DEC25",
    "atm_strike": 24250.0,
    "chain": [
        {
            "strike": 24000.0,
            "ce": {
                "symbol": "NIFTY30DEC2524000CE",
                "label": "ITM5",
                "ltp": 320.50,
                ...
            },
            "pe": {
                "symbol": "NIFTY30DEC2524000PE",
                "label": "OTM5",
                "ltp": 85.25,
                ...
            }
        },
        {
            "strike": 24250.0,
            "ce": { "symbol": "...", "label": "ATM", ... },
            "pe": { "symbol": "...", "label": "ATM", ... }
        },
        {
            "strike": 24500.0,
            "ce": { "symbol": "...", "label": "OTM5", ... },
            "pe": { "symbol": "...", "label": "ITM5", ... }
        },
        ...
    ]
}

Strike Labels (different for CE and PE):
    - ATM: At-The-Money strike (same for both CE and PE)
    - Strike BELOW ATM: CE is ITM, PE is OTM
    - Strike ABOVE ATM: CE is OTM, PE is ITM
"""

from flask import request
from flask_restx import Namespace, Resource
from marshmallow import ValidationError
from limiter import limiter
from utils.logging import get_logger
from .data_schemas import OptionChainSchema
from services.option_chain_service import get_option_chain
import os

# Initialize logger
logger = get_logger(__name__)

# Create namespace
api = Namespace('optionchain', description='Get Option Chain with Real-time Quotes')

# Get rate limit from environment
API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")


@api.route('/', strict_slashes=False)
class OptionChain(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get option chain for underlying with real-time quotes"""
        try:
            # Validate request data
            schema = OptionChainSchema()
            data = schema.load(request.json)

            # Extract parameters
            api_key = data['apikey']
            underlying = data['underlying']
            exchange = data['exchange']
            expiry_date = data['expiry_date']
            strike_count = data.get('strike_count')  # None means return entire chain

            logger.info(
                f"Option chain request: underlying={underlying}, exchange={exchange}, "
                f"expiry={expiry_date}, strike_count={'all' if strike_count is None else strike_count}"
            )

            # Call service to get option chain
            success, response, status_code = get_option_chain(
                underlying=underlying,
                exchange=exchange,
                expiry_date=expiry_date,
                strike_count=strike_count,
                api_key=api_key
            )

            return response, status_code

        except ValidationError as err:
            logger.warning(f"Validation error in option chain request: {err.messages}")
            return {
                'status': 'error',
                'message': 'Validation error',
                'errors': err.messages
            }, 400
        except Exception as e:
            logger.exception(f"Unexpected error in option chain endpoint: {e}")
            return {
                'status': 'error',
                'message': 'An unexpected error occurred'
            }, 500
