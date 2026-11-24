import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import ValidationError

from database.apilog_db import async_log_order
from database.apilog_db import executor as log_executor
from limiter import limiter
from restx_api.schemas import ChargesSchema
from services.charges_service import calculate_charges
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "50 per second")
api = Namespace("charges", description="Brokerage and Statutory Charges API")

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
charges_schema = ChargesSchema()


def _without_key(data):
    """The request as it may be logged: the API key is the caller's secret."""
    if not isinstance(data, dict):
        return {}
    return {name: value for name, value in data.items() if name != "apikey"}


@api.route("/", strict_slashes=False)
class Charges(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Brokerage and statutory charges for an order, before it is placed"""
        data = None
        try:
            # Get the request data
            data = request.json

            # Validate and deserialize input using Marshmallow schema
            try:
                validated_data = charges_schema.load(data)
            except ValidationError as err:
                error_response = {"status": "error", "message": str(err.messages)}
                log_executor.submit(async_log_order, "charges", _without_key(data), error_response)
                return make_response(jsonify(error_response), 400)

            api_key = validated_data.pop("apikey", None)

            success, response_data, status_code = calculate_charges(
                charges_data=validated_data, api_key=api_key
            )

            return make_response(jsonify(response_data), status_code)

        except Exception:
            logger.exception("An unexpected error occurred in Charges endpoint.")
            error_response = {
                "status": "error",
                "message": "An unexpected error occurred in the API endpoint",
            }
            try:
                log_executor.submit(async_log_order, "charges", _without_key(data), error_response)
            except Exception as e:
                logger.exception(f"Failed to log charges request: {e}")
            return make_response(jsonify(error_response), 500)
