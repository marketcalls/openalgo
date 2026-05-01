import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import ValidationError

from limiter import limiter
from restx_api.schemas import GTTOrderBookSchema
from services.gtt_orderbook_service import get_gtt_orderbook
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace("gtt_orderbook", description="GTT Order Book API")

logger = get_logger(__name__)
gtt_book_schema = GTTOrderBookSchema()


@api.route("/", strict_slashes=False)
class GTTOrderBook(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """List all GTT triggers for the authenticated user."""
        try:
            book_data = gtt_book_schema.load(request.json or {})
            api_key = book_data["apikey"]

            success, response_data, status_code = get_gtt_orderbook(api_key=api_key)
            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            return make_response(jsonify({"status": "error", "message": err.messages}), 400)
        except Exception:
            logger.exception("An unexpected error occurred in GTTOrderBook endpoint.")
            return make_response(
                jsonify({"status": "error", "message": "An unexpected error occurred"}), 500
            )
