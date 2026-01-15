"""
Options Order API Endpoint

POST /api/v1/optionsorder

Places option orders by resolving option symbol based on underlying and offset,
then placing the order. Works in both live and analyze (sandbox) mode.
Supports order splitting via optional splitsize parameter.

Request Body:
{
    "apikey": "your_api_key",
    "strategy": "strategy_name",
    "underlying": "NIFTY",  // or "NIFTY28NOV24FUT"
    "exchange": "NSE_INDEX",  // or "NSE", "NFO", "BSE_INDEX", "BSE", "BFO"
    "expiry_date": "28NOV24",  // Optional if underlying includes expiry
    "strike_int": 50,  // Optional: Strike interval. If omitted, actual strikes from database are used (RECOMMENDED)
    "offset": "ITM2",  // ATM, ITM1-ITM50, OTM1-OTM50
    "option_type": "CE",  // CE or PE
    "action": "BUY",  // or "SELL"
    "quantity": 75,
    "splitsize": 0,  // Optional: If > 0, splits order into multiple orders of this size
    "pricetype": "MARKET",  // or "LIMIT", "SL", "SL-M"
    "product": "MIS",  // or "NRML"
    "price": 0.0,  // For LIMIT orders
    "trigger_price": 0.0,  // For SL/SL-M orders
    "disclosed_quantity": 0
}

Response (Success - Live Mode - Regular Order):
{
    "status": "success",
    "orderid": "240123000001234",
    "symbol": "NIFTY28NOV2423500CE",
    "exchange": "NFO",
    "underlying": "NIFTY",
    "underlying_ltp": 23587.50,
    "offset": "ITM2",
    "option_type": "CE"
}

Response (Success - Split Order):
{
    "status": "success",
    "symbol": "NIFTY28NOV2423500CE",
    "exchange": "NFO",
    "underlying": "NIFTY",
    "underlying_ltp": 23587.50,
    "offset": "ITM2",
    "option_type": "CE",
    "total_quantity": 150,
    "split_size": 50,
    "results": [
        {"order_num": 1, "quantity": 50, "status": "success", "orderid": "240123000001234"},
        {"order_num": 2, "quantity": 50, "status": "success", "orderid": "240123000001235"},
        {"order_num": 3, "quantity": 50, "status": "success", "orderid": "240123000001236"}
    ]
}

Response (Success - Analyze Mode):
{
    "status": "success",
    "orderid": "SB-1234567890",
    "symbol": "NIFTY28NOV2423500CE",
    "exchange": "NFO",
    "underlying": "NIFTY",
    "underlying_ltp": 23587.50,
    "offset": "ITM2",
    "option_type": "CE",
    "mode": "analyze"
}

Response (Error):
{
    "status": "error",
    "message": "Option symbol NIFTY28NOV2425500CE not found in NFO. Symbol may not exist or master contract needs update."
}
"""

from flask import request, jsonify, make_response
from flask_restx import Namespace, Resource
from marshmallow import ValidationError
from limiter import limiter
from utils.logging import get_logger
from restx_api.schemas import OptionsOrderSchema
from services.place_options_order_service import place_options_order
import os

# Initialize logger
logger = get_logger(__name__)

# Create namespace
api = Namespace('optionsorder', description='Place Options Order API')

# Get rate limit from environment
ORDER_RATE_LIMIT = os.getenv("ORDER_RATE_LIMIT", "10 per second")


@api.route('/', strict_slashes=False)
class OptionsOrder(Resource):
    @limiter.limit(ORDER_RATE_LIMIT)
    def post(self):
        """
        Place an options order by resolving the symbol based on underlying and offset.
        Works in both live and analyze (sandbox) mode.
        """
        try:
            # Validate request data
            schema = OptionsOrderSchema()
            data = schema.load(request.json)

            # Extract API key
            api_key = data.get('apikey')

            logger.info(
                f"Options order API request: underlying={data.get('underlying')}, "
                f"offset={data.get('offset')}, action={data.get('action')}"
            )

            # Call the service function to place the options order
            success, response_data, status_code = place_options_order(
                options_data=data,
                api_key=api_key
            )

            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            logger.warning(f"Validation error in options order request: {err.messages}")
            return make_response(jsonify({
                'status': 'error',
                'message': 'Validation error',
                'errors': err.messages
            }), 400)
        except Exception as e:
            logger.exception("An unexpected error occurred in OptionsOrder endpoint.")
            error_response = {
                'status': 'error',
                'message': 'An unexpected error occurred in the API endpoint'
            }
            return make_response(jsonify(error_response), 500)
