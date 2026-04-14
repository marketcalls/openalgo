import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import ValidationError

from database.auth_db import verify_api_key
from limiter import limiter
from services.option_greeks_service import get_multi_option_greeks
from utils.logging import get_logger

from .data_schemas import MultiOptionGreeksSchema

logger = get_logger(__name__)

# Rate limit for multi option greeks API (same as multiquotes)
API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")

api = Namespace("multioptiongreeks", description="Batch Option Greeks API")

# Initialize schema
multi_option_greeks_schema = MultiOptionGreeksSchema()


@api.route("", strict_slashes=False)
class MultiOptionGreeks(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """
        Calculate Option Greeks for multiple symbols in a single request

        This endpoint calculates option Greeks (Delta, Gamma, Theta, Vega, Rho)
        and Implied Volatility for multiple option symbols using Black-76 model.

        Required fields:
        - apikey: API key for authentication
        - symbols: List of option symbol requests, each containing:
            - symbol: Option symbol (e.g., NIFTY28NOV2424000CE)
            - exchange: Exchange code (NFO, BFO, CDS, MCX)
            - underlying_symbol: (Optional) Underlying symbol
            - underlying_exchange: (Optional) Underlying exchange

        Optional fields:
        - interest_rate: Risk-free interest rate (annualized %). Applied to all symbols.
        - expiry_time: Custom expiry time in HH:MM format. Applied to all symbols.

        Example Request:
        {
            "apikey": "your_api_key",
            "symbols": [
                {"symbol": "NIFTY30DEC2524000CE", "exchange": "NFO"},
                {"symbol": "NIFTY30DEC2524000PE", "exchange": "NFO"},
                {"symbol": "NIFTY30DEC2526000CE", "exchange": "NFO", "underlying_symbol": "NIFTY30DEC25FUT", "underlying_exchange": "NFO"}
            ],
            "interest_rate": 7.0
        }

        Example Response:
        {
            "status": "success",
            "data": [
                {
                    "status": "success",
                    "symbol": "NIFTY30DEC2524000CE",
                    "exchange": "NFO",
                    "implied_volatility": 15.25,
                    "greeks": {"delta": 0.52, "gamma": 0.0001, "theta": -4.97, "vega": 30.76, "rho": 0.001}
                },
                ...
            ],
            "summary": {"total": 3, "success": 2, "failed": 1}
        }
        """
        try:
            # Get request data
            data = request.json

            if data is None:
                return make_response(
                    jsonify(
                        {"status": "error", "message": "Request body is missing or invalid JSON"}
                    ),
                    400,
                )

            # Validate request data
            try:
                validated_data = multi_option_greeks_schema.load(data)
            except ValidationError as err:
                logger.warning(f"Validation error in multi option greeks request: {err.messages}")
                return make_response(
                    jsonify(
                        {"status": "error", "message": "Validation failed", "errors": err.messages}
                    ),
                    400,
                )

            # Extract validated data
            api_key = validated_data.get("apikey")
            symbols = validated_data.get("symbols")
            interest_rate = validated_data.get("interest_rate")
            expiry_time = validated_data.get("expiry_time")

            # Verify API key
            if not verify_api_key(api_key):
                logger.warning(f"Invalid API key used for multi option greeks: {api_key[:10]}...")
                return make_response(
                    jsonify({"status": "error", "message": "Invalid openalgo apikey"}), 401
                )

            # Get multi option Greeks
            logger.info(f"Calculating Greeks for {len(symbols)} symbols")

            success, response, status_code = get_multi_option_greeks(
                symbols=symbols,
                interest_rate=interest_rate,
                expiry_time=expiry_time,
                api_key=api_key,
            )

            if success:
                logger.info(f"Multi Greeks calculated: {response.get('summary', {})}")
            else:
                logger.error(f"Failed to calculate multi Greeks: {response.get('message')}")

            return make_response(jsonify(response), status_code)

        except Exception as e:
            logger.exception(f"Unexpected error in multi option greeks endpoint: {e}")
            return make_response(
                jsonify(
                    {
                        "status": "error",
                        "message": "Internal server error while calculating option Greeks",
                    }
                ),
                500,
            )
