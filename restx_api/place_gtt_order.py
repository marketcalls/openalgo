import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import ValidationError

from database.settings_db import get_analyze_mode
from events import GTTFailedEvent
from limiter import limiter
from restx_api.schemas import PlaceGTTOrderSchema
from services.place_gtt_order_service import emit_analyzer_error, place_gtt_order
from utils.event_bus import bus
from utils.logging import get_logger

ORDER_RATE_LIMIT = os.getenv("ORDER_RATE_LIMIT", "10 per second")
api = Namespace("place_gtt_order", description="Place GTT Order API")

logger = get_logger(__name__)
place_gtt_schema = PlaceGTTOrderSchema()


@api.route("/", strict_slashes=False)
class PlaceGTTOrder(Resource):
    @limiter.limit(ORDER_RATE_LIMIT)
    def post(self):
        """Place a GTT (Good Till Triggered) order — single or two-leg OCO."""
        try:
            data = request.json or {}

            try:
                order_data = place_gtt_schema.load(data)
            except ValidationError as err:
                error_message = str(err.messages)
                if get_analyze_mode():
                    return make_response(jsonify(emit_analyzer_error(data, error_message)), 400)
                error_response = {"status": "error", "message": error_message}
                safe_request = {k: v for k, v in data.items() if k != "apikey"}
                bus.publish(GTTFailedEvent(
                    mode="live",
                    api_type="placegttorder",
                    symbol=data.get("symbol", ""),
                    exchange=data.get("exchange", ""),
                    trigger_type=data.get("trigger_type", ""),
                    request_data=safe_request,
                    response_data=error_response,
                    error_message=error_message,
                ))
                return make_response(jsonify(error_response), 400)

            api_key = order_data.pop("apikey", None)

            success, response_data, status_code = place_gtt_order(
                order_data=order_data, api_key=api_key
            )

            return make_response(jsonify(response_data), status_code)

        except Exception:
            logger.exception("An unexpected error occurred in PlaceGTTOrder endpoint.")
            return make_response(
                jsonify({"status": "error", "message": "An unexpected error occurred"}), 500
            )
