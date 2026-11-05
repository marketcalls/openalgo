"""
Strike Profile Blueprint

Serves gamma exposure (GEX) and delta exposure (DEX) per strike across
several expiries.
Endpoints:
    POST /strikeprofile/api/profile-data - GEX and DEX grid for the given expiries
"""

import re

from flask import Blueprint, jsonify, request, session
from flask_cors import cross_origin

from database.auth_db import get_api_key_for_tradingview
from services.strike_profile_service import get_strike_profile
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

strike_profile_bp = Blueprint("strike_profile_bp", __name__, url_prefix="/")

# Each expiry is one option chain fetch, so the list is capped.
MAX_EXPIRIES = 20

ALLOWED_RANGES = {2.0, 5.0, 10.0}


@strike_profile_bp.route("/strikeprofile/api/profile-data", methods=["POST"])
@cross_origin()
@check_session_validity
def profile_data():
    """Get GEX and DEX for every strike of the requested expiries."""
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
        underlying = str(data.get("underlying", "")).strip()[:20]
        exchange = str(data.get("exchange", "")).strip()[:20]
        expiry_dates = data.get("expiry_dates", [])
        range_value = data.get("range_pct", 5)

        if not underlying or not exchange:
            return jsonify(
                {"status": "error", "message": "underlying and exchange are required"}
            ), 400

        if not re.match(r"^[A-Z0-9]+$", underlying) or not re.match(r"^[A-Z0-9_]+$", exchange):
            return jsonify({"status": "error", "message": "Invalid input format"}), 400

        if not isinstance(expiry_dates, list) or not expiry_dates:
            return jsonify({"status": "error", "message": "Select at least one expiry."}), 400

        expiry_dates = [str(e).strip().upper() for e in expiry_dates[:MAX_EXPIRIES]]
        if not all(re.match(r"^\d{2}[A-Z]{3}\d{2}$", e) for e in expiry_dates):
            return jsonify(
                {"status": "error", "message": "Invalid expiry format. Expected DDMMMYY"}
            ), 400

        if range_value is None:
            range_pct = None
        else:
            try:
                range_pct = float(range_value)
            except (TypeError, ValueError):
                return jsonify({"status": "error", "message": "Invalid strike range"}), 400
            if range_pct not in ALLOWED_RANGES:
                return jsonify({"status": "error", "message": "Invalid strike range"}), 400

        success, response, status_code = get_strike_profile(
            underlying=underlying,
            exchange=exchange,
            expiry_dates=expiry_dates,
            api_key=api_key,
            range_pct=range_pct,
        )

        return jsonify(response), status_code

    except Exception as e:
        logger.exception(f"Error in strike profile API: {e}")
        return (
            jsonify({"status": "error", "message": "An error occurred processing your request"}),
            500,
        )
