import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import ValidationError

from limiter import limiter
from services.market_calendar_service import get_timings
from utils.logging import get_logger

from .data_schemas import MarketTimingsSchema

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace("market/timings", description="Market Timings API")

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
timings_schema = MarketTimingsSchema()


@api.route("/", strict_slashes=False)
class MarketTimings(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get market timings for a specific date"""
        try:
            # Validate request data
            timings_data = timings_schema.load(request.json)

            # Extract parameters
            date_str = timings_data["date"]

            # Call the service function to get timings
            success, response_data, status_code = get_timings(date_str=date_str)

            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            return make_response(jsonify({"status": "error", "message": err.messages}), 400)

        except Exception as e:
            logger.exception(f"Unexpected error in market timings endpoint: {e}")
            return make_response(
                jsonify({"status": "error", "message": "An unexpected error occurred"}), 500
            )
