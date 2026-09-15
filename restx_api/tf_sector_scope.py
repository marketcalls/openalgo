import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import ValidationError

from database.auth_db import get_auth_token_broker
from limiter import limiter
from services.tf_cpr_service import attach_cpr, ensure_cpr_cache
from services.tradefinder_service import fetch_sector_scope, has_tf_jwt
from utils.logging import get_logger

from .data_schemas import TfSectorScopeSchema

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace(
    "tfsectorscope",
    description="TradeFinder Sector Scope (daily-index + all_sector) via the server's "
                 "own auto-refreshing JWT — no client-pasted token needed",
)

logger = get_logger(__name__)

tf_sector_scope_schema = TfSectorScopeSchema()


@api.route("/", strict_slashes=False)
class TfSectorScope(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Proxies TradeFinder's sector-scope data using the server-side JWT,
        same pattern as /tfmarketpulse. Returns {status: 'error'} (200) when
        the server token itself is unavailable, so the client can fall back
        to its own pasted token if it has one."""
        try:
            tf_sector_scope_schema.load(request.json)
            data = request.json or {}

            auth_token, broker = get_auth_token_broker(
                data.get("apikey", ""), include_feed_token=False
            )
            if auth_token is None:
                return make_response(
                    jsonify({"status": "error", "message": "Invalid openalgo apikey"}), 403
                )

            result = fetch_sector_scope()
            if result is None:
                # A missing token is the only case that's actually a token
                # problem -- fetch_sector_scope() also returns None for a
                # network error or TF renaming/removing its sector routes
                # (check log/app_stdout.log for the real reason), which
                # "token unavailable or expired" used to misreport identically.
                message = (
                    "Server-side TradeFinder token unavailable or expired"
                    if not has_tf_jwt()
                    else "TradeFinder sector data unavailable right now "
                    "(upstream request failed -- see server logs, not a token issue)"
                )
                return make_response(jsonify({"status": "error", "message": message}), 200)

            # Narrow-CPR enrichment, same pattern/cache as /tfmarketpulse. Sector
            # data is nested (sector -> {symbol -> stock dict}) rather than a
            # flat list, and stock dicts use TradeFinder's raw "Symbol" key
            # (capitalized) rather than "symbol" — attach_cpr()/ensure_cpr_cache()
            # both expect lowercase "symbol", so it's added here before calling in.
            sector_stocks = result.get("sectors") or {}
            all_stock_dicts = [
                stock
                for stocks in sector_stocks.values()
                for stock in stocks.values()
                if stock.get("Symbol")
            ]
            if all_stock_dicts:
                for stock in all_stock_dicts:
                    stock["symbol"] = stock["Symbol"]
                symbols = list({stock["Symbol"] for stock in all_stock_dicts})
                ensure_cpr_cache(symbols, auth_token, broker)
                attach_cpr(all_stock_dicts)

            return make_response(jsonify({"status": "success", "data": result}), 200)

        except ValidationError as err:
            return make_response(jsonify({"status": "error", "message": err.messages}), 400)
        except Exception as e:
            logger.exception(f"Unexpected error in tfsectorscope endpoint: {e}")
            return make_response(
                jsonify({"status": "error", "message": "An unexpected error occurred"}), 500
            )
