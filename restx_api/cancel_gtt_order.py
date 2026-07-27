import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import ValidationError

from database.settings_db import get_analyze_mode
from events import GTTCancelFailedEvent
from limiter import limiter
from restx_api.schemas import CancelGTTOrderSchema
from services.cancel_gtt_order_service import cancel_gtt_order, emit_analyzer_error
from utils.event_bus import bus
from utils.logging import get_logger

ORDER_RATE_LIMIT = os.getenv("ORDER_RATE_LIMIT", "10 per second")
api = Namespace("cancel_gtt_order", description="Cancel GTT Order API")

logger = get_logger(__name__)
cancel_gtt_schema = CancelGTTOrderSchema()


@api.route("/", strict_slashes=False)
class CancelGTTOrder(Resource):
    @limiter.limit(ORDER_RATE_LIMIT)
    def post(self):
        """Cancel an active GTT trigger."""
        try:
            data = request.json or {}

            try:
                order_data = cancel_gtt_schema.load(data)
            except ValidationError as err:
                error_message = str(err.messages)
                if get_analyze_mode():
                    return make_response(jsonify(emit_analyzer_error(data, error_message)), 400)
                error_response = {"status": "error", "message": error_message}
                safe_request = {k: v for k, v in data.items() if k != "apikey"}
                bus.publish(GTTCancelFailedEvent(
                    mode="live",
                    api_type="cancelgttorder",
                    trigger_id=data.get("trigger_id", ""),
                    request_data=safe_request,
                    response_data=error_response,
                    error_message=error_message,
                ))
                return make_response(jsonify(error_response), 400)

            api_key = order_data.pop("apikey", None)
            trigger_id = order_data.get("trigger_id")
            strategy = order_data.get("strategy")

            success, response_data, status_code = cancel_gtt_order(
                trigger_id=trigger_id, api_key=api_key, strategy=strategy
            )

            return make_response(jsonify(response_data), status_code)

        except Exception:
            logger.exception("An unexpected error occurred in CancelGTTOrder endpoint.")
            return make_response(
                jsonify({"status": "error", "message": "An unexpected error occurred"}), 500
            )
