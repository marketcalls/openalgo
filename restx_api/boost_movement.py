import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import ValidationError

from database.auth_db import get_auth_token_broker
from limiter import limiter
from services.tf_rank_movement_service import movement_snapshot
from utils.logging import get_logger

from .data_schemas import BoostMovementSchema

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace(
    "boostmovement",
    description="Current-day Intraday Boost rank-movement state (delta, velocity, "
    "acceleration, Top-N, sustained zone, event) derived from the snapshot history",
)

logger = get_logger(__name__)

boost_movement_schema = BoostMovementSchema()


@api.route("/", strict_slashes=False)
class BoostMovement(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Return per-symbol current-day rank-movement rows, newest rank first.

        Reconstructed from the isolated boost-snapshot DuckDB by the pure
        movement engine (no upstream TradeFinder fetch, no extra polling), so the
        chart's Intraday Boost panel can render the whole path a stock took to its
        rank rather than only the rank. Degrades to an empty list (not an error)
        when there are no snapshots for the day."""
        try:
            data = boost_movement_schema.load(request.json)

            auth_token, _broker = get_auth_token_broker(data["apikey"], include_feed_token=False)
            if auth_token is None:
                return make_response(
                    jsonify({"status": "error", "message": "Invalid openalgo apikey"}), 403
                )

            rows = movement_snapshot(date=data["date"], list_type=data["list_type"])
            return make_response(
                jsonify(
                    {
                        "status": "success",
                        "list_type": data["list_type"],
                        "count": len(rows),
                        "symbols": rows,
                    }
                ),
                200,
            )

        except ValidationError as err:
            return make_response(jsonify({"status": "error", "message": err.messages}), 400)
        except Exception as e:
            logger.exception(f"Unexpected error in boostmovement endpoint: {e}")
            return make_response(
                jsonify({"status": "error", "message": "An unexpected error occurred"}), 500
            )
