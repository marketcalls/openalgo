import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import ValidationError

from database.apilog_db import async_log_order
from database.apilog_db import executor as log_executor
from limiter import limiter
from restx_api.schemas import MarginCalculatorSchema
from services.margin_service import calculate_margin
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "50 per second")
api = Namespace("margin", description="Margin Calculator API")

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
margin_schema = MarginCalculatorSchema()


@api.route("/", strict_slashes=False)
class MarginCalculator(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Calculate margin requirement for a basket of positions"""
        try:
            # Get the request data
            data = request.json

            # Validate and deserialize input using Marshmallow schema
            try:
                validated_data = margin_schema.load(data)
            except ValidationError as err:
                error_message = str(err.messages)
                error_response = {"status": "error", "message": error_message}
                log_executor.submit(async_log_order, "margin", data, error_response)
                return make_response(jsonify(error_response), 400)

            # Extract API key without removing it from the validated data
            api_key = validated_data.get("apikey", None)

            # Call the service function to calculate margin
            success, response_data, status_code = calculate_margin(
                margin_data=validated_data, api_key=api_key
            )

            return make_response(jsonify(response_data), status_code)

        except Exception:
            logger.exception("An unexpected error occurred in Margin Calculator endpoint.")
            error_response = {
                "status": "error",
                "message": "An unexpected error occurred in the API endpoint",
            }
            # Log the error
            try:
                log_executor.submit(
                    async_log_order, "margin", data if "data" in locals() else {}, error_response
                )
            except:
                pass
            return make_response(jsonify(error_response), 500)
