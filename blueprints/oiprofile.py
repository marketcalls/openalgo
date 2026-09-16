"""
OI Profile Blueprint

Serves OI Profile data: futures candles + OI butterfly + OI change (daily,
or an arbitrary window when window_start/window_end are given).
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

# Cap how many expiries can be summed in one request. Six is what Sensibull's
# own OI Profile offers, and matching it is the point.
MAX_EXPIRIES = 6

# Strikes either side of ATM. Each one is two legs to quote, so the ceiling is
# what keeps a careless request from asking the broker for the whole chain.
DEFAULT_STRIKE_COUNT = 20
MAX_STRIKE_COUNT = 50

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
        # Optional list of expiries to sum OI across (nearest first).
        expiry_dates = data.get("expiry_dates") or ([expiry_date] if expiry_date else [])
        if not isinstance(expiry_dates, list):
            return jsonify({"status": "error", "message": "expiry_dates must be a list"}), 400
        expiry_dates = [str(e).strip().upper()[:10] for e in expiry_dates[:MAX_EXPIRIES] if e]
        interval = data.get("interval", "5m").strip()[:5]
        days = min(int(data.get("days", 5)), 30)
        # The chart overlay only needs current OI; the change pass costs one
        # history call per option leg, so let a caller opt out of it.
        include_change = data.get("include_change", True) is not False
        # The overlay draws on the chart's own bars, so it asks for no candles.
        include_candles = data.get("include_candles", True) is not False

        try:
            strike_count = int(data.get("strike_count", DEFAULT_STRIKE_COUNT))
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "strike_count must be a number"}), 400
        strike_count = max(1, min(strike_count, MAX_STRIKE_COUNT))

        try:
            window_start = data.get("window_start")
            window_end = data.get("window_end")
            window_start = int(window_start) if window_start is not None else None
            window_end = int(window_end) if window_end is not None else None
        except (TypeError, ValueError):
            return jsonify(
                {"status": "error", "message": "window_start/window_end must be unix seconds"}
            ), 400

        if (window_start is None) != (window_end is None):
            return jsonify(
                {"status": "error", "message": "window_start and window_end must be given together"}
            ), 400

        if window_start is not None and window_start >= window_end:
            return jsonify(
                {"status": "error", "message": "window_start must be before window_end"}
            ), 400

        if not underlying or not exchange or not expiry_dates:
            return jsonify(
                {
                    "status": "error",
                    "message": "underlying, exchange, and at least one expiry are required",
                }
            ), 400

        if not re.match(r"^[A-Z0-9]+$", underlying) or not re.match(r"^[A-Z0-9_]+$", exchange):
            return jsonify({"status": "error", "message": "Invalid input format"}), 400

        if any(not re.match(r"^\d{2}[A-Z]{3}\d{2}$", e) for e in expiry_dates):
            return jsonify(
                {"status": "error", "message": "Invalid expiry format. Expected DDMMMYY"}
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
            expiry_date=expiry_dates[0],
            expiry_dates=expiry_dates,
            interval=interval,
            days=days,
            api_key=api_key,
            window_start=window_start,
            window_end=window_end,
            include_change=include_change,
            include_candles=include_candles,
            strike_count=strike_count,
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
