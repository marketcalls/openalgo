"""
Timeseries Blueprint — Multi-Symbol History API

Endpoints:
    POST /timeseries/api/chain  - Get option chain symbols (with metadata)
    POST /timeseries/api/data   - Fetch aligned history for any list of symbols
"""

import re
from datetime import datetime

from flask import Blueprint, jsonify, request, session
from flask_cors import cross_origin

from database.auth_db import get_api_key_for_tradingview
from services.timeseries_service import get_timeseries_chain_data, get_multi_symbol_history
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

# Allowed intervals for intraday timeseries
ALLOWED_INTERVALS = {"1m", "3m", "5m", "15m", "1h"}

timeseries_bp = Blueprint("timeseries_bp", __name__, url_prefix="/")


@timeseries_bp.route("/timeseries/api/chain", methods=["POST"])
@cross_origin()
@check_session_validity
def get_chain():
    """Get option chain symbols for timeseries analysis."""
    try:
        login_username = session.get("user")
        if not login_username:
            return jsonify({"status": "error", "message": "Authentication required"}), 401

        api_key = get_api_key_for_tradingview(login_username)
        if not api_key:
            return jsonify({
                "status": "error",
                "message": "API key not configured. Please generate an API key in /apikey",
            }), 401

        data = request.get_json(silent=True) or {}
        underlying = data.get("underlying", "").strip()[:20]
        exchange = data.get("exchange", "").strip()[:20]
        expiry_date = data.get("expiry_date", "").strip()[:10]
        strike_count = min(int(data.get("strike_count", 5)), 25)

        if not underlying or not exchange or not expiry_date:
            return jsonify({
                "status": "error",
                "message": "underlying, exchange, and expiry_date are required",
            }), 400

        # Input validation
        if not re.match(r"^[A-Z0-9]+$", underlying):
            return jsonify({"status": "error", "message": "Invalid underlying format"}), 400

        if not re.match(r"^[A-Z0-9_]+$", exchange):
            return jsonify({"status": "error", "message": "Invalid exchange format"}), 400

        if not re.match(r"^\d{2}[A-Z]{3}\d{2}$", expiry_date):
            return jsonify({
                "status": "error",
                "message": "Invalid expiry_date format. Expected DDMMMYY",
            }), 400

        success, response, status_code = get_timeseries_chain_data(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            strike_count=strike_count,
            api_key=api_key,
        )

        return jsonify(response), status_code

    except Exception as e:
        logger.exception(f"Error in timeseries chain API: {e}")
        return jsonify({
            "status": "error",
            "message": "An error occurred processing your request",
        }), 500


@timeseries_bp.route("/timeseries/api/data", methods=["POST"])
@cross_origin()
@check_session_validity
def get_data():
    """
    Fetch aligned history for an arbitrary list of symbols.

    The backend is symbol-agnostic — it treats every symbol the same
    regardless of whether it's a CE option, PE option, futures, equity, etc.
    The frontend is responsible for classification and aggregation.

    Required params:
        symbols:    [{symbol, exchange}, ...]
        start_date: YYYY-MM-DD
        end_date:   YYYY-MM-DD

    Optional params:
        interval:   "1m" (default) | "3m" | "5m" | "15m" | "1h"
    """
    try:
        login_username = session.get("user")
        if not login_username:
            return jsonify({"status": "error", "message": "Authentication required"}), 401

        api_key = get_api_key_for_tradingview(login_username)
        if not api_key:
            return jsonify({
                "status": "error",
                "message": "API key not configured. Please generate an API key in /apikey",
            }), 401

        data = request.get_json(silent=True) or {}

        symbols = data.get("symbols", [])
        interval = data.get("interval", "1m").strip()[:5]
        today = datetime.now().strftime("%Y-%m-%d")
        start_date = data.get("start_date", today).strip()[:10]
        end_date = data.get("end_date", today).strip()[:10]

        if not symbols:
            return jsonify({
                "status": "error",
                "message": "symbols list is required",
            }), 400

        if interval not in ALLOWED_INTERVALS:
            return jsonify({
                "status": "error",
                "message": f"Invalid interval. Allowed: {', '.join(sorted(ALLOWED_INTERVALS))}",
            }), 400

        # Validate date formats
        date_re = r"^\d{4}-\d{2}-\d{2}$"
        if not re.match(date_re, start_date) or not re.match(date_re, end_date):
            return jsonify({
                "status": "error",
                "message": "Invalid date format. Expected YYYY-MM-DD",
            }), 400

        # Validate symbols structure — only symbol + exchange required
        for s in symbols:
            if not isinstance(s, dict) or "symbol" not in s or "exchange" not in s:
                return jsonify({
                    "status": "error",
                    "message": "Each symbol must have 'symbol' and 'exchange' fields",
                }), 400

        success, response, status_code = get_multi_symbol_history(
            symbols=symbols,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            api_key=api_key,
        )

        return jsonify(response), status_code

    except Exception as e:
        logger.exception(f"Error in timeseries data API: {e}")
        return jsonify({
            "status": "error",
            "message": "An error occurred processing your request",
        }), 500
