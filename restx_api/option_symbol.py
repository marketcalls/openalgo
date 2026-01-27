"""
Option Symbol API Endpoint

POST /api/v1/optionsymbol

Fetches option symbol based on underlying, expiry, strike offset, and option type.
Calculates ATM from current LTP and returns the appropriate option symbol.

Request Body:
{
    "apikey": "your_api_key",
    "strategy": "strategy_name",  // DEPRECATED: Optional, will be removed in future versions
    "underlying": "NIFTY",  // or "NIFTY28OCT25FUT"
    "exchange": "NSE_INDEX",  // or "NSE", "NFO", "BSE_INDEX", "BSE", "BFO"
    "expiry_date": "28OCT25",  // Optional if underlying includes expiry
    "strike_int": 50,  // Optional: Strike interval. If omitted, actual strikes from database are used (RECOMMENDED)
    "offset": "ITM2",  // ATM, ITM1-ITM50, OTM1-OTM50
    "option_type": "CE"  // CE or PE
}

Response:
{
    "status": "success",
    "symbol": "NIFTY28OCT2523500CE",
    "exchange": "NFO",
    "lotsize": 25,
    "tick_size": 0.05,
    "underlying_ltp": 23587.50
}
"""

import os

from flask import request
from flask_restx import Namespace, Resource
from marshmallow import ValidationError

from limiter import limiter
from services.option_symbol_service import get_option_symbol
from utils.logging import get_logger

from .data_schemas import OptionSymbolSchema

# Initialize logger
logger = get_logger(__name__)

# Create namespace
api = Namespace("optionsymbol", description="Get Option Symbol based on Underlying and Offset")

# Get rate limit from environment
API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")


@api.route("/", strict_slashes=False)
class OptionSymbol(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get option symbol based on underlying, expiry, strike offset, and option type"""
        try:
            # Validate request data
            schema = OptionSymbolSchema()
            data = schema.load(request.json)

            # Extract parameters
            api_key = data["apikey"]
            underlying = data["underlying"]
            exchange = data["exchange"]
            expiry_date = data.get("expiry_date")  # Optional
            strike_int = data.get(
                "strike_int"
            )  # Optional - if not provided, actual strikes from database will be used
            offset = data["offset"]
            option_type = data["option_type"]

            logger.info(
                f"Option symbol request: underlying={underlying}, exchange={exchange}, "
                f"expiry={expiry_date}, strike_int={strike_int}, offset={offset}, type={option_type}"
            )

            # Call service to get option symbol
            success, response, status_code = get_option_symbol(
                underlying=underlying,
                exchange=exchange,
                expiry_date=expiry_date,
                strike_int=strike_int,
                offset=offset,
                option_type=option_type,
                api_key=api_key,
            )

            return response, status_code

        except ValidationError as err:
            logger.warning(f"Validation error in option symbol request: {err.messages}")
            return {"status": "error", "message": "Validation error", "errors": err.messages}, 400
        except Exception as e:
            logger.exception(f"Unexpected error in option symbol endpoint: {e}")
            return {"status": "error", "message": "An unexpected error occurred"}, 500
