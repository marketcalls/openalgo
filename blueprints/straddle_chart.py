"""
Straddle Chart Blueprint
Serves Dynamic ATM Straddle chart data for index options.
"""

from flask import Blueprint, jsonify, request, session
from flask_cors import cross_origin

from database.auth_db import get_api_key_for_tradingview, get_auth_token
from services.intervals_service import get_intervals
from services.straddle_chart_service import get_straddle_chart_data
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

straddle_bp = Blueprint("straddle_bp", __name__, url_prefix="/")


@straddle_bp.route("/straddle/api/straddle-data", methods=["POST"])
@cross_origin()
@check_session_validity
def straddle_data():
    """Get Dynamic ATM Straddle time series for charting."""
    try:
        broker = session.get("broker")
        if not broker:
            return jsonify({"status": "error", "message": "Broker not set in session"}), 400

        login_username = session["user"]
        auth_token = get_auth_token(login_username)
        if auth_token is None:
            return jsonify({"status": "error", "message": "Authentication required"}), 401

        api_key = get_api_key_for_tradingview(login_username)
        if not api_key:
            return jsonify(
                {"status": "error", "message": "API key not configured. Please generate an API key in /apikey"}
            ), 401

        data = request.get_json(silent=True) or {}
        underlying = data.get("underlying", "").strip()
        exchange = data.get("exchange", "").strip()
        expiry_date = data.get("expiry_date", "").strip()
        interval = data.get("interval", "1m").strip()
        days = int(data.get("days", 5))

        if not underlying or not exchange or not expiry_date:
            return jsonify(
                {"status": "error", "message": "underlying, exchange, and expiry_date are required"}
            ), 400

        success, response, status_code = get_straddle_chart_data(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            interval=interval,
            api_key=api_key,
            days=days,
        )

        return jsonify(response), status_code

    except Exception as e:
        logger.exception(f"Error in straddle chart API: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@straddle_bp.route("/straddle/api/intervals", methods=["GET"])
@cross_origin()
@check_session_validity
def straddle_intervals():
    """Get broker-supported intervals for the straddle chart."""
    try:
        login_username = session.get("user")
        if not login_username:
            return jsonify({"status": "error", "message": "Authentication required"}), 401

        api_key = get_api_key_for_tradingview(login_username)
        if not api_key:
            return jsonify(
                {"status": "error", "message": "API key not configured"}
            ), 401

        success, response, status_code = get_intervals(api_key=api_key)
        return jsonify(response), status_code

    except Exception as e:
        logger.exception(f"Error fetching intervals: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
