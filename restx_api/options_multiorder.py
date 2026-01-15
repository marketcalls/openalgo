"""
Options Multi-Order API Endpoint

POST /api/v1/optionsmultiorder

Places multiple option legs with common underlying, resolving symbols based on offset.
BUY legs are executed first, then SELL legs for margin efficiency.
Each leg supports optional splitsize parameter to split large orders.

Request Body:
{
    "apikey": "your_api_key",
    "strategy": "Iron Condor",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "28NOV24",
    "legs": [
        {
            "offset": "OTM10",
            "option_type": "CE",
            "action": "BUY",
            "quantity": 75,
            "splitsize": 0  // Optional: If > 0, splits this leg into multiple orders of this size
        },
        {
            "offset": "OTM10",
            "option_type": "PE",
            "action": "BUY",
            "quantity": 150,
            "splitsize": 75  // Example: splits 150 qty into 2 orders of 75 each
        },
        {
            "offset": "OTM5",
            "option_type": "CE",
            "action": "SELL",
            "quantity": 75
        },
        {
            "offset": "OTM5",
            "option_type": "PE",
            "action": "SELL",
            "quantity": 75
        }
    ]
}

Response (Success - Regular Legs):
{
    "status": "success",
    "underlying": "NIFTY",
    "underlying_ltp": 26000.50,
    "results": [
        {
            "leg": 1,
            "symbol": "NIFTY25NOV2526000CE",
            "exchange": "NFO",
            "offset": "OTM10",
            "option_type": "CE",
            "action": "BUY",
            "status": "success",
            "orderid": "240123000001234"
        },
        ...
    ]
}

Response (Success - With Split Leg):
{
    "status": "success",
    "underlying": "NIFTY",
    "underlying_ltp": 26000.50,
    "results": [
        {
            "leg": 1,
            "symbol": "NIFTY25NOV2526000CE",
            "exchange": "NFO",
            "offset": "OTM10",
            "option_type": "CE",
            "action": "BUY",
            "status": "success",
            "orderid": "240123000001234"
        },
        {
            "leg": 2,
            "symbol": "NIFTY25NOV2526000PE",
            "exchange": "NFO",
            "offset": "OTM10",
            "option_type": "PE",
            "action": "BUY",
            "status": "success",
            "total_quantity": 150,
            "split_size": 75,
            "split_results": [
                {"order_num": 1, "quantity": 75, "status": "success", "orderid": "240123000001235"},
                {"order_num": 2, "quantity": 75, "status": "success", "orderid": "240123000001236"}
            ]
        },
        ...
    ]
}

Note: BUY legs execute first for margin efficiency, then SELL legs.
"""

from flask import request, jsonify, make_response
from flask_restx import Namespace, Resource
from marshmallow import ValidationError
from limiter import limiter
from utils.logging import get_logger
from restx_api.schemas import OptionsMultiOrderSchema
from services.options_multiorder_service import place_options_multiorder
import os

# Initialize logger
logger = get_logger(__name__)

# Create namespace
api = Namespace('optionsmultiorder', description='Options Multi-Order API')

# Get rate limit from environment
ORDER_RATE_LIMIT = os.getenv("ORDER_RATE_LIMIT", "10 per second")


@api.route('/', strict_slashes=False)
class OptionsMultiOrder(Resource):
    @limiter.limit(ORDER_RATE_LIMIT)
    def post(self):
        """
        Place multiple option legs with common underlying.
        BUY legs execute first for margin efficiency.
        """
        try:
            # Validate request data
            schema = OptionsMultiOrderSchema()
            data = schema.load(request.json)

            # Extract API key
            api_key = data.get('apikey')

            logger.info(
                f"Options multi-order API request: underlying={data.get('underlying')}, "
                f"legs={len(data.get('legs', []))}"
            )

            # Call the service function
            success, response_data, status_code = place_options_multiorder(
                multiorder_data=data,
                api_key=api_key
            )

            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            logger.warning(f"Validation error in options multi-order request: {err.messages}")
            return make_response(jsonify({
                'status': 'error',
                'message': 'Validation error',
                'errors': err.messages
            }), 400)
        except Exception as e:
            logger.exception("An unexpected error occurred in OptionsMultiOrder endpoint.")
            error_response = {
                'status': 'error',
                'message': 'An unexpected error occurred in the API endpoint'
            }
            return make_response(jsonify(error_response), 500)
