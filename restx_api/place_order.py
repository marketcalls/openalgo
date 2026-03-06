import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource, fields
from marshmallow import ValidationError

from limiter import limiter
from restx_api.schemas import OrderSchema
from services.place_order_service import place_order
from utils.logging import get_logger

ORDER_RATE_LIMIT = os.getenv("ORDER_RATE_LIMIT", "10 per second")
api = Namespace("place_order", description="Place Order API")

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
order_schema = OrderSchema()


@api.route("/", strict_slashes=False)
class PlaceOrder(Resource):
    @limiter.limit(ORDER_RATE_LIMIT)
    def post(self):
        """Place an order with the broker"""
        try:
            data = request.json

            # Validate and deserialize input
            try:
                order_data = order_schema.load(data)
            except ValidationError as err:
                error_response = {"status": "error", "message": str(err.messages)}
                return make_response(jsonify(error_response), 400)

            # Extract API key
            api_key = order_data.get("apikey", None)

            # Call the service function to place the order
            success, response_data, status_code = place_order(order_data=order_data, api_key=api_key)

            return make_response(jsonify(response_data), status_code)

        except Exception:
            logger.exception("An unexpected error occurred in PlaceOrder endpoint.")
            error_response = {
                "status": "error",
                "message": "An unexpected error occurred in the API endpoint",
            }
            return make_response(jsonify(error_response), 500)
