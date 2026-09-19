"""Decision-telemetry intake endpoint (``POST /api/v1/analyze``).

ADR-006 Amendment 5 counterpart: the strategy process (LOATS) routes every
TradeDecision through this endpoint once its ``ANALYZER_INTAKE_PATH`` setting
points here. Until now the routed decision received an HTTP 404 from the
gateway's absent ``/analyze`` intake — an honestly-counted error outcome under
the read-only semantic. This endpoint accepts the decision telemetry, records
it in the analyzer log, and acknowledges with a structured success response so
the producer's routing counters reflect real deliveries.

The endpoint is intentionally receive-and-record only: it never places orders,
never touches broker credentials beyond the standard apikey authentication,
and is therefore safe to expose alongside the read-only ANALYZE-mode surface.
"""

import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import ValidationError

from database.analyzer_db import async_log_analyzer
from database.auth_db import get_auth_token_broker
from limiter import limiter
from restx_api.account_schema import AnalyzerIntakeSchema
from services.analyze_intake_service import record_decision_intake
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace("analyze", description="Decision Telemetry Intake API")

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
analyzer_intake_schema = AnalyzerIntakeSchema()


@api.route("/", strict_slashes=False)
class AnalyzeIntake(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Record a routed strategy decision and acknowledge receipt."""
        try:
            data = request.json

            try:
                intake_data = analyzer_intake_schema.load(data)
            except ValidationError as err:
                error_response = {"status": "error", "message": err.messages}
                # Bad schema: skip DB audit to avoid flooding (house rule).
                return make_response(jsonify(error_response), 400)

            api_key = intake_data.pop("apikey", None)

            # API-key authentication only (no direct auth_token path: the
            # producer is by definition an external API client).
            AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
            if AUTH_TOKEN is None:
                error_response = {"status": "error", "message": "Invalid openalgo apikey"}
                # Skip logging for invalid API keys to prevent database flooding.
                return make_response(jsonify(error_response), 403)

            # apikey is already popped; log WITHOUT the credential.
            log_request = {k: v for k, v in (data or {}).items() if k != "apikey"}

            success, response_data, status_code = record_decision_intake(
                intake_data=intake_data,
                original_data=log_request,
            )
            return make_response(jsonify(response_data), status_code)

        except Exception:
            logger.exception("An unexpected error occurred in the analyze intake endpoint.")
            error_response = {"status": "error", "message": "An unexpected error occurred"}
            return make_response(jsonify(error_response), 500)
