import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource, fields
from marshmallow import ValidationError

from limiter import limiter
from restx_api.schemas import (
    CancelSuperOrderSchema,
    ModifySuperOrderSchema,
    SuperOrderSchema,
)
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace("superorder", description="Super Order API")

# Initialize logger
logger = get_logger(__name__)

# Initialize schemas
superorder_schema = SuperOrderSchema()
modify_superorder_schema = ModifySuperOrderSchema()
cancel_superorder_schema = CancelSuperOrderSchema()


super_order_model = api.model(
    "SuperOrder",
    {
        "apikey": fields.String(
            required=True,
            description="OpenAlgo API Key",
            example="a85992a13ab7db424c239c50826116366e9f4fd8c591345a2d23aad01ffa4d00",
        ),
        "strategy": fields.String(
            required=True,
            description="Strategy name for tracking",
            example="Test Strategy",
        ),
        "exchange": fields.String(
            required=True, description="Exchange (NSE / BSE / MCX)", example="NSE"
        ),
        "symbol": fields.String(
            required=True, description="Trading symbol", example="YESBANK"
        ),
        "action": fields.String(
            required=True, description="BUY or SELL", example="BUY"
        ),
        "product": fields.String(
            required=True, description="MIS / NRML / CNC / MTF", example="MIS"
        ),
        "pricetype": fields.String(
            required=True,
            description="LIMIT (Super Orders require a limit entry price)",
            example="LIMIT",
        ),
        "quantity": fields.String(
            required=True, description="Number of shares/lots", example="10"
        ),
        "price": fields.String(
            required=True, description="Entry price (Main Leg limit price)", example="21.50"
        ),
        "target_price": fields.String(
            required=True,
            description="Target exit price (above entry for BUY, below for SELL)",
            example="23.00",
        ),
        "stoploss_price": fields.String(
            required=True,
            description="Stop-loss price (below entry for BUY, above for SELL)",
            example="20.00",
        ),
        "trail_jump": fields.String(
            required=False,
            description="Trailing SL increment (min: tick size). Omit to disable.",
            example="0.50",
        ),
    },
)

@api.route("/", strict_slashes=False)
class SuperOrderList(Resource):
    @api.doc("place_super_order")
    @api.expect(super_order_model)
    @api.response(200, "Success")
    @api.response(400, "Validation Error")
    @api.response(401, "Unauthorized")
    @api.response(500, "Internal Server Error")
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Place a new Super Order"""
        try:
            data = request.json
            order_data = superorder_schema.load(data)

            api_key = order_data.get("apikey", None)

            from services.superorder_service import place_superorder
            success, response_data, status_code = place_superorder(
                order_data=order_data, api_key=api_key
            )
            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            error_response = {"status": "error", "message": str(err.messages)}
            return make_response(jsonify(error_response), 400)
        except Exception:
            logger.exception(
                "An unexpected error occurred in SuperOrder post endpoint."
            )
            error_response = {
                "status": "error",
                "message": "An unexpected error occurred in the API endpoint",
            }
            return make_response(jsonify(error_response), 500)

    @limiter.limit(API_RATE_LIMIT)
    def get(self):
        """Get all Super Orders for the user"""
        try:
            # Requires apikey in query param for GET request
            api_key = request.args.get("apikey")
            if not api_key:
                return make_response(
                    jsonify({"status": "error", "message": "API key required"}), 400
                )

            from services.superorder_service import get_superorders
            success, response_data, status_code = get_superorders(api_key=api_key)
            return make_response(jsonify(response_data), status_code)

        except Exception:
            logger.exception("An unexpected error occurred in SuperOrder get endpoint.")
            error_response = {
                "status": "error",
                "message": "An unexpected error occurred in the API endpoint",
            }
            return make_response(jsonify(error_response), 500)


@api.route("/<int:id>", strict_slashes=False)
class SuperOrderDetails(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def get(self, id):
        """Get details of a specific Super Order"""
        try:
            api_key = request.args.get("apikey")
            if not api_key:
                return make_response(
                    jsonify({"status": "error", "message": "API key required"}), 400
                )

            from services.superorder_service import get_superorder
            success, response_data, status_code = get_superorder(
                order_id=id, api_key=api_key
            )
            return make_response(jsonify(response_data), status_code)

        except Exception:
            logger.exception(
                "An unexpected error occurred in SuperOrder get details endpoint."
            )
            error_response = {
                "status": "error",
                "message": "An unexpected error occurred in the API endpoint",
            }
            return make_response(jsonify(error_response), 500)

    @limiter.limit(API_RATE_LIMIT)
    def put(self, id):
        """Modify target/SL prices or legs in PENDING state of a Super Order"""
        try:
            data = request.json
            if not data:
                data = {}
            data["order_id"] = id

            order_data = modify_superorder_schema.load(data)
            api_key = order_data.get("apikey")

            from services.superorder_service import modify_superorder
            success, response_data, status_code = modify_superorder(
                order_data=order_data, api_key=api_key
            )
            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            error_response = {"status": "error", "message": str(err.messages)}
            return make_response(jsonify(error_response), 400)
        except Exception:
            logger.exception(
                "An unexpected error occurred in SuperOrder modify endpoint."
            )
            error_response = {
                "status": "error",
                "message": "An unexpected error occurred in the API endpoint",
            }
            return make_response(jsonify(error_response), 500)

    @limiter.limit(API_RATE_LIMIT)
    def delete(self, id):
        """Cancel a Super Order"""
        try:
            # Delete body might have apikey or from query string
            api_key = request.args.get("apikey")
            if not api_key and request.is_json:
                data = request.json
                if data:
                    api_key = data.get("apikey")

            if not api_key:
                return make_response(
                    jsonify({"status": "error", "message": "API key required"}), 400
                )

            from services.superorder_service import cancel_superorder
            success, response_data, status_code = cancel_superorder(
                order_id=id, api_key=api_key
            )
            return make_response(jsonify(response_data), status_code)

        except Exception:
            logger.exception(
                "An unexpected error occurred in SuperOrder delete endpoint."
            )
            error_response = {
                "status": "error",
                "message": "An unexpected error occurred in the API endpoint",
            }
            return make_response(jsonify(error_response), 500)
