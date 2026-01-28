import os
import traceback

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import ValidationError

from limiter import limiter
from services.sandbox_service import is_sandbox_mode, sandbox_get_pnl_symbols
from utils.logging import get_logger

from .account_schema import PnlSymbolsSchema

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace("pnl", description="P&L Analysis API")

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
pnl_symbols_schema = PnlSymbolsSchema()


@api.route("/symbols", strict_slashes=False)
class PnLSymbols(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get day P&L breakdown by symbol (Sandbox mode only)"""
        try:
            # Check if sandbox mode is enabled
            if not is_sandbox_mode():
                return make_response(
                    jsonify(
                        {
                            "status": "error",
                            "message": "This endpoint is only available in sandbox/analyzer mode",
                        }
                    ),
                    400,
                )

            # Validate request data
            pnl_data = pnl_symbols_schema.load(request.json)

            api_key = pnl_data["apikey"]

            # Call the service function to get PnL by symbols
            success, response_data, status_code = sandbox_get_pnl_symbols(api_key, request.json)
            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            return make_response(jsonify({"status": "error", "message": err.messages}), 400)
        except Exception as e:
            logger.error(f"Unexpected error in pnl/symbols endpoint: {e}")
            traceback.print_exc()
            return make_response(
                jsonify({"status": "error", "message": "An unexpected error occurred"}), 500
            )
