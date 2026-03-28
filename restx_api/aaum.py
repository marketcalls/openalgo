import os
import traceback

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import Schema, ValidationError, fields, validate

from database.auth_db import get_auth_token_broker
from limiter import limiter
from services.aaum_service import (
    analyze,
    analyze_mock,
    check_health,
    execute_trade,
    get_aaum_url,
    get_trade_card,
    set_aaum_url,
)
from services.aaum_dashboard_service import (
    get_agent_consensus,
    get_command_center,
    get_institutional_score,
    get_model_predictions,
    get_oi_intelligence,
    get_risk_snapshot,
    get_self_learning,
    get_stock_scanner,
    get_timeframe_matrix,
)
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace("aaum", description="AAUM Intelligence Proxy API")

# Initialize logger
logger = get_logger(__name__)


# --- Marshmallow Schemas ---

class AaumAnalyzeSchema(Schema):
    apikey = fields.Str(required=False, validate=validate.Length(min=1, max=256))
    symbol = fields.Str(required=True, validate=validate.Length(min=1, max=50))
    config = fields.Dict(keys=fields.Str(), required=False)


class AaumTradeCardSchema(Schema):
    apikey = fields.Str(required=False, validate=validate.Length(min=1, max=256))


class AaumExecuteSchema(Schema):
    apikey = fields.Str(required=False, validate=validate.Length(min=1, max=256))
    trade_intent = fields.Dict(required=True)


class AaumConfigSchema(Schema):
    url = fields.Str(required=True, validate=validate.Length(min=8, max=512))


# Initialize schemas
analyze_schema = AaumAnalyzeSchema()
trade_card_schema = AaumTradeCardSchema()
execute_schema = AaumExecuteSchema()
config_schema = AaumConfigSchema()


def _validate_api_key(api_key: str):
    """
    Validate an OpenAlgo API key and return (auth_token, broker) or None.
    Returns tuple (AUTH_TOKEN, broker) on success, or None on failure.
    """
    AUTH_TOKEN, broker = get_auth_token_broker(api_key)
    if AUTH_TOKEN is None:
        return None
    return AUTH_TOKEN, broker


# --- Endpoints ---

@api.route("/analyze", strict_slashes=False)
class AaumAnalyze(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Proxy analysis request to AAUM POST /api/v1/analysis/run"""
        try:
            data = request.json

            # Validate and deserialize input
            try:
                validated = analyze_schema.load(data)
            except ValidationError as err:
                return make_response(
                    jsonify({"status": "error", "message": str(err.messages)}), 400
                )

            # Authenticate: API key (external) or session cookie (frontend)
            api_key = validated.pop("apikey", None)
            if api_key:
                auth_result = _validate_api_key(api_key)
                if auth_result is None:
                    return make_response(
                        jsonify({"status": "error", "message": "Invalid openalgo apikey"}), 403
                    )

            # Call AAUM service
            symbol = validated["symbol"]
            config = validated.get("config")
            success, response_data, status_code = analyze(symbol=symbol, config=config)

            if success:
                # Frontend expects the analysis data directly (Zod validates it)
                return make_response(jsonify(response_data.get("data", response_data)), status_code)
            return make_response(jsonify(response_data), status_code)

        except Exception:
            logger.exception("An unexpected error occurred in AAUM analyze endpoint.")
            return make_response(
                jsonify({"status": "error", "message": "An unexpected error occurred"}), 500
            )


@api.route("/trade-card/<string:symbol>", strict_slashes=False)
class AaumTradeCard(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self, symbol):
        """Proxy trade-card request to AAUM POST /api/v3/trade-card/{symbol}"""
        try:
            data = request.json

            # Validate and deserialize input
            try:
                validated = trade_card_schema.load(data)
            except ValidationError as err:
                return make_response(
                    jsonify({"status": "error", "message": str(err.messages)}), 400
                )

            # Authenticate: API key (external) or session cookie (frontend)
            api_key = validated.pop("apikey", None)
            if api_key:
                auth_result = _validate_api_key(api_key)
                if auth_result is None:
                    return make_response(
                        jsonify({"status": "error", "message": "Invalid openalgo apikey"}), 403
                    )

            # Call AAUM service
            success, response_data, status_code = get_trade_card(symbol=symbol)

            return make_response(jsonify(response_data), status_code)

        except Exception:
            logger.exception("An unexpected error occurred in AAUM trade-card endpoint.")
            return make_response(
                jsonify({"status": "error", "message": "An unexpected error occurred"}), 500
            )


@api.route("/execute", strict_slashes=False)
class AaumExecute(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Forward execute request to AAUM (TradeIntent -> order)"""
        try:
            data = request.json

            # Validate and deserialize input
            try:
                validated = execute_schema.load(data)
            except ValidationError as err:
                return make_response(
                    jsonify({"status": "error", "message": str(err.messages)}), 400
                )

            # Authenticate: API key (external) or session cookie (frontend)
            api_key = validated.pop("apikey", None)
            if api_key:
                auth_result = _validate_api_key(api_key)
                if auth_result is None:
                    return make_response(
                        jsonify({"status": "error", "message": "Invalid openalgo apikey"}), 403
                )

            # Call AAUM service
            trade_intent = validated["trade_intent"]
            success, response_data, status_code = execute_trade(trade_intent=trade_intent)

            return make_response(jsonify(response_data), status_code)

        except Exception:
            logger.exception("An unexpected error occurred in AAUM execute endpoint.")
            return make_response(
                jsonify({"status": "error", "message": "An unexpected error occurred"}), 500
            )


@api.route("/demo", strict_slashes=False)
class AaumDemo(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Return mock AAUM analysis data for frontend testing during off-market hours."""
        try:
            data = request.json or {}
            symbol = data.get("symbol", "SBIN")

            if not isinstance(symbol, str) or len(symbol) < 1 or len(symbol) > 50:
                return make_response(
                    jsonify({"status": "error", "message": "Invalid symbol"}), 400
                )

            mock_data = analyze_mock(symbol)
            mock_data["_mock"] = True
            mock_data["_mock_reason"] = "Demo endpoint — not a live analysis"
            return make_response(jsonify(mock_data), 200)

        except Exception:
            logger.exception("An unexpected error occurred in AAUM demo endpoint.")
            return make_response(
                jsonify({"status": "error", "message": "An unexpected error occurred"}), 500
            )


@api.route("/config", strict_slashes=False)
class AaumConfig(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Set the AAUM backend URL at runtime (no restart needed)."""
        try:
            data = request.json or {}

            try:
                validated = config_schema.load(data)
            except ValidationError as err:
                return make_response(
                    jsonify({"status": "error", "message": str(err.messages)}), 400
                )

            new_url = validated["url"]

            # Basic URL sanity check
            if not (new_url.startswith("http://") or new_url.startswith("https://")):
                return make_response(
                    jsonify({"status": "error", "message": "URL must start with http:// or https://"}),
                    400,
                )

            old_url = get_aaum_url()
            set_aaum_url(new_url)
            logger.info(f"AAUM URL changed: {old_url} -> {new_url}")

            return make_response(
                jsonify({
                    "status": "success",
                    "message": f"AAUM URL updated to {new_url}",
                    "old_url": old_url,
                    "new_url": new_url,
                }),
                200,
            )

        except Exception:
            logger.exception("An unexpected error occurred in AAUM config endpoint.")
            return make_response(
                jsonify({"status": "error", "message": "An unexpected error occurred"}), 500
            )


@api.route("/health", strict_slashes=False)
class AaumHealth(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def get(self):
        """Check AAUM backend health — probes Colab tunnel and localhost."""
        try:
            health = check_health()
            return make_response(jsonify(health), 200)
        except Exception:
            logger.exception("An unexpected error occurred in AAUM health endpoint.")
            return make_response(
                jsonify({"status": "offline", "message": "Health check failed"}), 500
            )


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard Panel Endpoints — Real-time data from AAUM + OpenAlgo broker APIs
# ─────────────────────────────────────────────────────────────────────────────

def _dashboard_response(data):
    """Wrap dashboard data in a standard response envelope."""
    import time
    return make_response(jsonify({
        "status": "success",
        "data": data,
        "timestamp": int(time.time() * 1000),
    }), 200)


def _dashboard_error(message, status_code=500):
    """Return a standard dashboard error response."""
    return make_response(jsonify({
        "status": "error",
        "error": message,
    }), status_code)


def _get_symbol_param():
    """Extract and validate 'symbol' query parameter."""
    symbol = request.args.get("symbol", "").strip().upper()
    if not symbol or len(symbol) > 50:
        return None
    return symbol


@api.route("/dashboard/command-center", strict_slashes=False)
class DashboardCommandCenter(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def get(self):
        """Command Center — combined signal with entry/SL/target."""
        try:
            symbol = _get_symbol_param()
            if not symbol:
                return _dashboard_error("Missing or invalid 'symbol' parameter", 400)
            data = get_command_center(symbol)
            return _dashboard_response(data)
        except Exception:
            logger.exception("Dashboard command-center error")
            return _dashboard_error("Failed to get command center data")


@api.route("/dashboard/timeframe-matrix", strict_slashes=False)
class DashboardTimeframeMatrix(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def get(self):
        """Timeframe Matrix — trend per timeframe (1m, 5m, 15m, 1h, 4h)."""
        try:
            symbol = _get_symbol_param()
            if not symbol:
                return _dashboard_error("Missing or invalid 'symbol' parameter", 400)
            data = get_timeframe_matrix(symbol)
            return _dashboard_response(data)
        except Exception:
            logger.exception("Dashboard timeframe-matrix error")
            return _dashboard_error("Failed to get timeframe matrix data")


@api.route("/dashboard/institutional-score", strict_slashes=False)
class DashboardInstitutionalScore(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def get(self):
        """Institutional Score — composite 0-100 with sub-scores."""
        try:
            symbol = _get_symbol_param()
            if not symbol:
                return _dashboard_error("Missing or invalid 'symbol' parameter", 400)
            data = get_institutional_score(symbol)
            return _dashboard_response(data)
        except Exception:
            logger.exception("Dashboard institutional-score error")
            return _dashboard_error("Failed to get institutional score data")


@api.route("/dashboard/agent-consensus", strict_slashes=False)
class DashboardAgentConsensus(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def get(self):
        """Agent Consensus — 9 agent votes with consensus."""
        try:
            symbol = _get_symbol_param()
            if not symbol:
                return _dashboard_error("Missing or invalid 'symbol' parameter", 400)
            data = get_agent_consensus(symbol)
            return _dashboard_response(data)
        except Exception:
            logger.exception("Dashboard agent-consensus error")
            return _dashboard_error("Failed to get agent consensus data")


@api.route("/dashboard/model-predictions", strict_slashes=False)
class DashboardModelPredictions(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def get(self):
        """Model Predictions — 7 model predictions with ensemble."""
        try:
            symbol = _get_symbol_param()
            if not symbol:
                return _dashboard_error("Missing or invalid 'symbol' parameter", 400)
            data = get_model_predictions(symbol)
            return _dashboard_response(data)
        except Exception:
            logger.exception("Dashboard model-predictions error")
            return _dashboard_error("Failed to get model predictions data")


@api.route("/dashboard/oi-intelligence", strict_slashes=False)
class DashboardOIIntelligence(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def get(self):
        """OI Intelligence — PCR, max pain, buildup, GEX."""
        try:
            symbol = _get_symbol_param()
            if not symbol:
                return _dashboard_error("Missing or invalid 'symbol' parameter", 400)
            data = get_oi_intelligence(symbol)
            return _dashboard_response(data)
        except Exception:
            logger.exception("Dashboard oi-intelligence error")
            return _dashboard_error("Failed to get OI intelligence data")


@api.route("/dashboard/risk-snapshot", strict_slashes=False)
class DashboardRiskSnapshot(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def get(self):
        """Risk Snapshot — P&L, positions, drawdown, exposure."""
        try:
            data = get_risk_snapshot()
            return _dashboard_response(data)
        except Exception:
            logger.exception("Dashboard risk-snapshot error")
            return _dashboard_error("Failed to get risk snapshot data")


@api.route("/dashboard/stock-scanner", strict_slashes=False)
class DashboardStockScanner(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def get(self):
        """Stock Scanner — top 20 stocks ranked by score."""
        try:
            data = get_stock_scanner()
            return _dashboard_response(data)
        except Exception:
            logger.exception("Dashboard stock-scanner error")
            return _dashboard_error("Failed to get stock scanner data")


@api.route("/dashboard/self-learning", strict_slashes=False)
class DashboardSelfLearning(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def get(self):
        """Self-Learning — accuracy, weight changes, lessons, patterns."""
        try:
            symbol = request.args.get("symbol", "").strip().upper() or None
            data = get_self_learning(symbol)
            return _dashboard_response(data)
        except Exception:
            logger.exception("Dashboard self-learning error")
            return _dashboard_error("Failed to get self-learning data")
