import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import ValidationError

from limiter import limiter
from services.tf_boost_query_service import boost_universe_service
from utils.logging import get_logger

from .data_schemas import BoostSnapshotsSchema

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace("boostsnapshots", description="Historical Intraday Boost list universe for backtesting")

logger = get_logger(__name__)

boost_snapshots_schema = BoostSnapshotsSchema()


@api.route("/", strict_slashes=False)
class BoostSnapshots(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Return the UNION of symbols that were in a TradeFinder ranked list at
        any point over the [date - lookbackDays, date] window — so a backtest can
        run on the whole day's boost universe, not just the live list right now.
        Returns an empty list (not an error) when no snapshots exist for the range."""
        try:
            data = boost_snapshots_schema.load(request.json)

            success, response_data, status_code = boost_universe_service(
                api_key=data["apikey"],
                date=data["date"],
                lookback_days=data.get("lookbackDays", 1),
                list_type=data.get("list_type", "intraday_boost"),
                rank_as_of=data.get("rankAsOf", ""),
                include_ranks=data.get("includeRanks", False),
                include_prices=data.get("includePrices", False),
            )

            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            return make_response(jsonify({"status": "error", "message": err.messages}), 400)
        except Exception as e:
            logger.exception(f"Unexpected error in boostsnapshots endpoint: {e}")
            return make_response(
                jsonify({"status": "error", "message": "An unexpected error occurred"}), 500
            )
