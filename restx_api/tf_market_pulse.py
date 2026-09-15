import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import ValidationError

from database.auth_db import get_auth_token_broker
from limiter import limiter
from services.tf_cpr_service import attach_cpr, ensure_cpr_cache
from services.tf_directional_score_service import (
    attach_directional_score,
    ensure_directional_score_cache,
)
from services.tf_first_candle_service import attach_first_candle, ensure_first_candle_cache
from services.tradefinder_service import fetch_market_pulse
from utils.logging import get_logger

from .data_schemas import TfMarketPulseSchema

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace(
    "tfmarketpulse",
    description="TradeFinder market_pulse (Intraday Boost / Breakout Beacon / High Powered) "
                 "via the server's own auto-refreshing JWT — no client-pasted token needed",
)

logger = get_logger(__name__)

tf_market_pulse_schema = TfMarketPulseSchema()


@api.route("/", strict_slashes=False)
class TfMarketPulse(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Proxies TradeFinder's market_pulse using the server-side JWT
        (strategies/tf_jwt.txt, kept fresh by the TF JWT keep-alive scheduler/
        endpoint) so the openalgo-chart client never has to hold or paste its
        own TradeFinder token. Returns {status: 'error'} (200-adjacent, not a
        hard failure) when the server token itself is unavailable/expired, so
        the client can fall back to its own pasted token if it has one."""
        try:
            tf_market_pulse_schema.load(request.json)
            data = request.json or {}

            auth_token, broker = get_auth_token_broker(
                data.get("apikey", ""), include_feed_token=False
            )
            if auth_token is None:
                return make_response(
                    jsonify({"status": "error", "message": "Invalid openalgo apikey"}), 403
                )

            result = fetch_market_pulse()
            if result is None:
                return make_response(
                    jsonify({
                        "status": "error",
                        "message": "Server-side TradeFinder token unavailable or expired",
                    }),
                    200,
                )

            # Narrow-CPR enrichment: cache fill is non-blocking (background thread),
            # attach_cpr() serves whatever is cached so far (null until computed).
            boost_symbols = [it["symbol"] for it in result.get("intraday_boost", [])]
            if boost_symbols:
                ensure_cpr_cache(boost_symbols, auth_token, broker)
                attach_cpr(result["intraday_boost"])

                # First-candle shock enrichment: same non-blocking cache-fill
                # pattern as CPR above (see services/tf_first_candle_service.py).
                ensure_first_candle_cache(boost_symbols, auth_token, broker)
                attach_first_candle(result["intraday_boost"])

                # Directional steadiness enrichment: same non-blocking
                # cache-fill pattern, but refreshed every 5 minutes rather
                # than once per day (see services/tf_directional_score_service.py).
                ensure_directional_score_cache(boost_symbols, auth_token, broker)
                attach_directional_score(result["intraday_boost"])

            return make_response(jsonify({"status": "success", "data": result}), 200)

        except ValidationError as err:
            return make_response(jsonify({"status": "error", "message": err.messages}), 400)
        except Exception as e:
            logger.exception(f"Unexpected error in tfmarketpulse endpoint: {e}")
            return make_response(
                jsonify({"status": "error", "message": "An unexpected error occurred"}), 500
            )
