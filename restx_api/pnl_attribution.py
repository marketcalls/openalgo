import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import ValidationError

from limiter import limiter
from services.pnl_attribution_service import get_pnl_attribution
from utils.logging import get_logger

from .account_schema import PnlAttributionSchema

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")

# A separate namespace object from restx_api/pnl_symbols.py's "pnl", mounted on
# the same "/pnl" path, so neither file needs to know about the other.
api = Namespace("pnl_attribution", description="P&L attribution by strategy and M2M")

logger = get_logger(__name__)

pnl_attribution_schema = PnlAttributionSchema()


@api.route("/attribution", strict_slashes=False)
class PnlAttribution(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Live positions or holdings split by strategy, with an Unattributed
        remainder. With m2m, each position also carries today's M2M."""
        try:
            data = pnl_attribution_schema.load(request.json)

            success, response_data, status_code = get_pnl_attribution(
                api_key=data["apikey"], kind=data["kind"], include_m2m=data["m2m"]
            )
            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            return make_response(jsonify({"status": "error", "message": err.messages}), 400)
        except Exception as e:
            logger.exception(f"Unexpected error in pnl/attribution endpoint: {e}")
            return make_response(
                jsonify({"status": "error", "message": "An unexpected error occurred"}), 500
            )
