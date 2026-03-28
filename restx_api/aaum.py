"""AAUM Intelligence API namespace.

Exposes AAUM sidecar at /api/v1/aaum/*.
All endpoints proxy to AAUM FastAPI via aaum_service.py.

Auth: session cookie (frontend uses apiClient with withCredentials: true).
No @login_required — not used in any restx_api/ endpoint (breaks JSON).
"""

import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource

from limiter import limiter

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")

from services.aaum_service import (
    aaum_analyze,
    aaum_execute,
    aaum_health,
    aaum_safety,
)

api = Namespace("aaum", description="AAUM Intelligence API")


@api.route("/analyze", strict_slashes=False)
class AaumAnalyze(Resource):
    @limiter.limit("5 per minute")          # analysis is expensive
    def post(self):
        """Run full 12-layer analysis. Takes 30–90 seconds."""
        data = request.json or {}
        symbol = (data.get("symbol") or "").strip().upper()
        if not symbol:
            return make_response(
                jsonify({"status": "error", "message": "symbol is required"}), 400
            )
        success, response, status = aaum_analyze(symbol)
        return make_response(jsonify(response), status)


@api.route("/execute", strict_slashes=False)
class AaumExecute(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Execute AAUM trade recommendation (live or paper)."""
        data = request.json or {}
        symbol = (data.get("symbol") or "").strip().upper()
        if not symbol:
            return make_response(
                jsonify({"status": "error", "message": "symbol is required"}), 400
            )
        paper = bool(data.get("paper", True))
        analysis_id = data.get("analysis_id")
        success, response, status = aaum_execute(symbol, paper, analysis_id)
        return make_response(jsonify(response), status)


@api.route("/health", strict_slashes=False)
class AaumHealth(Resource):
    def get(self):
        """AAUM sidecar health check (polled every 30s by frontend)."""
        success, response, status = aaum_health()
        return make_response(jsonify(response), status)


@api.route("/safety/<string:symbol>", strict_slashes=False)
class AaumSafety(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def get(self, symbol):
        """Quick safety pre-check for symbol."""
        success, response, status = aaum_safety(symbol)
        return make_response(jsonify(response), status)
