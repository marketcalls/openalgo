from flask_restx import Namespace, Resource, fields
from flask import request, jsonify, make_response
from marshmallow import ValidationError
from limiter import limiter
import os

from .data_schemas import ScripMarginSchema
from services.scrip_margin_service import calculate_scrip_margin
from database.apilog_db import async_log_order, executor as log_executor
from utils.logging import get_logger
from utils.latency_monitor import track_latency

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace('margin-scrip', description='Per-Scrip Margin Calculator API')

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
scrip_margin_schema = ScripMarginSchema()

# Define Swagger model for request body
scrip_margin_model = api.model('ScripMargin', {
    'apikey': fields.String(required=True, description='API Key for authentication'),
    'symbol': fields.String(required=True, description='Trading symbol (e.g., RELIANCE, NIFTY26DEC24FUT)', example='NIFTY26DEC24FUT'),
    'exchange': fields.String(required=True, description='Exchange (NSE, BSE, NFO, BFO, CDS, MCX)', example='NFO'),
    'product': fields.String(required=True, description='Product type (MIS, NRML, CNC)', example='MIS'),
    'quantity': fields.Integer(required=False, description='Quantity (Optional: Auto-fetched for derivatives, defaults to 1 for equity)', example=None),
    'action': fields.String(required=False, default='BUY', description='Action (BUY/SELL, default: BUY)', example='BUY'),
    'pricetype': fields.String(required=False, default='MARKET', description='Price type (MARKET, LIMIT, SL, SL-M, default: MARKET)', example='MARKET'),
    'price': fields.String(required=False, default='0', description='Price (default: 0 for market orders)', example='0')
})

@api.route('/', strict_slashes=False)
class ScripMargin(Resource):
    @api.expect(scrip_margin_model)
    @limiter.limit(API_RATE_LIMIT)
    @track_latency('SCRIP_MARGIN')
    def post(self):
        """Calculate margin and leverage for a single symbol with automatic lot size detection

        Automatically fetches lot size from database for any symbol with lotsize > 1.
        Users can override by providing explicit quantity.

        Request Body:
        {
            "apikey": "your_api_key",
            "symbol": "NIFTY26DEC24FUT",
            "exchange": "NFO",
            "product": "MIS"
            // quantity is optional - will auto-fetch lot size (e.g., 50 for NIFTY)
        }

        Response includes:
        - quantity: Resolved quantity used for calculation
        - lot_size: Lot size from database (for derivatives) or null (for equity)
        - margin_per_unit: Margin required per share/contract
        - total_margin_required: Total margin for the resolved quantity

        Example Response:
        {
            "status": "success",
            "data": {
                "symbol": "NIFTY26DEC24FUT",
                "exchange": "NFO",
                "product": "MIS",
                "ltp": 24500.0,
                "margin_per_unit": 2500.0,
                "leverage": 9.8,
                "margin_percent": 10.2,
                "quantity": 50,
                "lot_size": 50,
                "total_margin_required": 125000.0,
                "margin_breakdown": {
                    "span_margin": 0,
                    "exposure_margin": 125000.0,
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
