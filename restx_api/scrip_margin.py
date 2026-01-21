from flask_restx import Namespace, Resource
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from limiter import limiter
import os

from .data_schemas import ScripMarginSchema
from services.scrip_margin_service import calculate_scrip_margin
from database.apilog_db import async_log_order, executor as log_executor
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('margin-scrip', description='Per-Scrip Margin Calculator API')

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
scrip_margin_schema = ScripMarginSchema()

@api.route('/', strict_slashes=False)
class ScripMargin(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Calculate margin and leverage for a single symbol

        Returns margin requirement and dynamic leverage calculation for a given symbol.
        Supports all product types (MIS, NRML, CNC) across all exchanges.

        Request Body:
        {
            "apikey": "your_api_key",
            "symbol": "UPL",
            "exchange": "NSE",
            "product": "MIS",
            "quantity": 1,
            "action": "BUY",
            "pricetype": "MARKET",
            "price": "0"
        }

        Response:
        {
            "status": "success",
            "data": {
                "symbol": "UPL",
                "exchange": "NSE",
                "product": "MIS",
                "ltp": 1480.0,
                "margin_per_unit": 296.0,
                "leverage": 5.0,
                "margin_percent": 20.0,
                "quantity": 1,
                "total_margin_required": 296.0,
                "margin_breakdown": {
                    "span_margin": 0,
                    "exposure_margin": 296.0,
                    "option_premium": 0,
                    "additional_margin": 0
                }
            }
        }

        Note: If LTP is unavailable (e.g., pre-market, permission issues),
        leverage and margin_percent will be null, but margin data will still be returned.
        """
        try:
            # Validate request data
            validated_data = scrip_margin_schema.load(request.json)

            # Call the service function to calculate scrip margin
            success, response_data, status_code = calculate_scrip_margin(
                scrip_data=validated_data,
                api_key=validated_data.get('apikey')
            )

            # Async log the request and response
            log_executor.submit(
                async_log_order,
                'scrip_margin',
                request.json,
                response_data
            )

            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            error_response = {
                'status': 'error',
                'message': str(err.messages)
            }
            # Log validation errors
            log_executor.submit(
                async_log_order,
                'scrip_margin',
                request.json,
                error_response
            )
            return make_response(jsonify(error_response), 400)

        except Exception as e:
            logger.exception("Unexpected error in scrip margin endpoint")
            error_response = {
                'status': 'error',
                'message': 'An unexpected error occurred'
            }
            # Log unexpected errors
            log_executor.submit(
                async_log_order,
                'scrip_margin',
                request.json,
                error_response
            )
            return make_response(jsonify(error_response), 500)
