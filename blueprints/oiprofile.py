"""
OI Profile Blueprint

Serves OI Profile data: futures candles + OI butterfly + daily OI change.
Endpoints:
    POST /oiprofile/api/profile-data  - Get OI profile data
    GET  /oiprofile/api/intervals     - Get broker-supported intervals (filtered)
"""

import re

from flask import Blueprint, jsonify, request, session
from flask_cors import cross_origin

from database.auth_db import get_api_key_for_tradingview
from services.intervals_service import get_intervals
from services.oi_profile_service import get_oi_profile_data
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

# Only allow these intraday intervals for the candlestick panel
ALLOWED_INTERVALS = {"1m", "5m", "15m"}

oiprofile_bp = Blueprint("oiprofile_bp", __name__, url_prefix="/")


@oiprofile_bp.route("/oiprofile/api/profile-data", methods=["POST"])
@cross_origin()
@check_session_validity
def profile_data():
    """Get OI Profile data (futures candles + OI + OI change)."""
    try:
        login_username = session.get("user")
        if not login_username:
            return jsonify({"status": "error", "message": "Authentication required"}), 401

        api_key = get_api_key_for_tradingview(login_username)
        if not api_key:
            return jsonify(
                {
                    "status": "error",
                    "message": "API key not configured. Please generate an API key in /apikey",
                }
            ), 401

        data = request.get_json(silent=True) or {}
        underlying = data.get("underlying", "").strip()[:20]
        exchange = data.get("exchange", "").strip()[:20]
        expiry_date = data.get("expiry_date", "").strip()[:10]
        interval = data.get("interval", "5m").strip()[:5]
        days = min(int(data.get("days", 5)), 30)

        if not underlying or not exchange or not expiry_date:
            return jsonify(
                {
                    "status": "error",
                    "message": "underlying, exchange, and expiry_date are required",
                }
            ), 400

        if not re.match(r"^[A-Z0-9]+$", underlying) or not re.match(r"^[A-Z0-9_]+$", exchange):
            return jsonify({"status": "error", "message": "Invalid input format"}), 400

        if not re.match(r"^\d{2}[A-Z]{3}\d{2}$", expiry_date):
            return jsonify(
                {"status": "error", "message": "Invalid expiry_date format. Expected DDMMMYY"}
            ), 400

        if interval not in ALLOWED_INTERVALS:
            return jsonify(
                {
                    "status": "error",
                    "message": f"Invalid interval. Allowed: {', '.join(sorted(ALLOWED_INTERVALS))}",
                }
            ), 400

        success, response, status_code = get_oi_profile_data(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            interval=interval,
            days=days,
            api_key=api_key,
        )

        return jsonify(response), status_code

    except Exception as e:
        logger.exception(f"Error in OI Profile data API: {e}")
        return (
            jsonify({"status": "error", "message": "An error occurred processing your request"}),
            500,
        )


@oiprofile_bp.route("/oiprofile/api/intervals", methods=["GET"])
@cross_origin()
@check_session_validity
def intervals():
    """Get broker-supported intervals filtered to 1m, 5m, 15m."""
    try:
        login_username = session.get("user")
        if not login_username:
            return jsonify({"status": "error", "message": "Authentication required"}), 401

        api_key = get_api_key_for_tradingview(login_username)
        if not api_key:
            return jsonify(
                {
                    "status": "error",
                    "message": "API key not configured. Please generate an API key in /apikey",
                }
            ), 401

        success, response, status_code = get_intervals(api_key=api_key)

        if success:
            data = response.get("data", {})
            all_minutes = data.get("minutes", [])
            # Filter to only allowed intervals that the broker supports
            supported = [i for i in all_minutes if i in ALLOWED_INTERVALS]
            return jsonify({"status": "success", "data": {"intervals": supported}}), 200

        return jsonify(response), status_code

    except Exception as e:
        logger.exception(f"Error fetching intervals: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
