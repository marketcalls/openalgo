import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import ValidationError

from limiter import limiter
from database.auth_db import get_auth_token_broker
from restx_api.schemas import (
    BracketOrderSchema,
    BracketOrderStatusSchema,
    CancelBracketOrderSchema,
)
from services.bracket_order_service import (
    cancel_bracket_order,
    get_bracket_order_status,
    place_bracket_order,
)
from utils.logging import get_logger

ORDER_RATE_LIMIT = os.getenv("ORDER_RATE_LIMIT", "10 per second")
api = Namespace("bracket_order", description="Bracket Order API")

logger = get_logger(__name__)

# Initialize schemas
bo_schema = BracketOrderSchema()
status_schema = BracketOrderStatusSchema()
cancel_schema = CancelBracketOrderSchema()


@api.route("/", strict_slashes=False)
class BracketOrder(Resource):
    @limiter.limit(ORDER_RATE_LIMIT)
    def post(self):
        """Place a bracket order with entry, target, and stop-loss legs"""
        try:
            data = request.json

            try:
                order_data = bo_schema.load(data)
            except ValidationError as err:
                return make_response(jsonify({"status": "error", "message": str(err.messages)}), 400)

            api_key = order_data.get("apikey", None)
            
            # Auth check first
            auth_token, broker = get_auth_token_broker(api_key)
            if not auth_token:
                return make_response(jsonify({"status": "error", "message": "Invalid API key"}), 403)

            success, response_data, status_code = place_bracket_order(order_data=order_data, api_key=api_key)
            return make_response(jsonify(response_data), status_code)

        except Exception:
            logger.exception("An unexpected error occurred in BracketOrder endpoint.")
            return make_response(jsonify({
                "status": "error",
                "message": "An unexpected error occurred in the API endpoint",
            }), 500)


@api.route("/status", strict_slashes=False)
class BracketOrderStatus(Resource):
    @limiter.limit(ORDER_RATE_LIMIT)
    def post(self):
        """Get the status of a bracket order"""
        try:
            data = request.json

            try:
                status_data = status_schema.load(data)
            except ValidationError as err:
                return make_response(jsonify({"status": "error", "message": str(err.messages)}), 400)

            api_key = status_data.get("apikey")
            bo_id = status_data.get("bo_id")

            # Auth check first
            auth_token, broker = get_auth_token_broker(api_key)
            if not auth_token:
                return make_response(jsonify({"status": "error", "message": "Invalid API key"}), 403)

            success, response_data, status_code = get_bracket_order_status(bo_id, api_key)
            return make_response(jsonify(response_data), status_code)

        except Exception:
            logger.exception("An unexpected error occurred in BracketOrderStatus endpoint.")
            return make_response(jsonify({
                "status": "error",
                "message": "An unexpected error occurred in the API endpoint",
            }), 500)


@api.route("/cancel", strict_slashes=False)
class CancelBracketOrder(Resource):
    @limiter.limit(ORDER_RATE_LIMIT)
    def post(self):
        """Cancel an active bracket order"""
        try:
            data = request.json

            try:
                cancel_data = cancel_schema.load(data)
            except ValidationError as err:
                return make_response(jsonify({"status": "error", "message": str(err.messages)}), 400)

            api_key = cancel_data.get("apikey")
            bo_id = cancel_data.get("bo_id")
            square_off = cancel_data.get("square_off", False)

            auth_token, broker = get_auth_token_broker(api_key)
            if not auth_token:
                return make_response(jsonify({"status": "error", "message": "Invalid API key"}), 403)

            success, response_data, status_code = cancel_bracket_order(
                bo_id=bo_id, 
                api_key=api_key, 
                auth_token=auth_token, 
                broker=broker,
                square_off=square_off
            )
            return make_response(jsonify(response_data), status_code)

        except Exception:
            logger.exception("An unexpected error occurred in CancelBracketOrder endpoint.")
            return make_response(jsonify({
                "status": "error",
                "message": "An unexpected error occurred in the API endpoint",
            }), 500)
