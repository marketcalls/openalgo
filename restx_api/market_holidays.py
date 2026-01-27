import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import ValidationError

from limiter import limiter
from services.market_calendar_service import get_holidays
from utils.logging import get_logger

from .data_schemas import MarketHolidaysSchema

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace("market/holidays", description="Market Holidays API")

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
holidays_schema = MarketHolidaysSchema()


@api.route("/", strict_slashes=False)
class MarketHolidays(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get market holidays for a specific year"""
        try:
            # Validate request data
            holidays_data = holidays_schema.load(request.json)

            # Extract parameters
            year = holidays_data.get("year")

            # Call the service function to get holidays
            success, response_data, status_code = get_holidays(year=year)

            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            return make_response(jsonify({"status": "error", "message": err.messages}), 400)

        except Exception as e:
            logger.exception(f"Unexpected error in market holidays endpoint: {e}")
            return make_response(
                jsonify({"status": "error", "message": "An unexpected error occurred"}), 500
            )
