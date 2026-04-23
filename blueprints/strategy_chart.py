"""
Strategy Chart Blueprint.

UI-only endpoint used by the Strategy Builder's Strategy Chart tab to fetch
the historical combined premium time series for the user's current leg set.
Session-authed, not exposed under /api/v1/.
"""

import os

from flask import Blueprint, jsonify, request, session
from flask_cors import cross_origin

from database.auth_db import get_api_key_for_tradingview, get_auth_token
from limiter import limiter
from services.intervals_service import get_intervals
from services.multi_strike_oi_service import get_multi_strike_oi_data
from services.strategy_chart_service import get_strategy_chart_data
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

strategy_chart_bp = Blueprint("strategy_chart_bp", __name__, url_prefix="/")

STRATEGY_CHART_LIMIT = os.getenv("STRATEGY_CHART_LIMIT", "30 per minute")


@strategy_chart_bp.route("/strategybuilder/api/strategy-chart", methods=["POST"])
@cross_origin()
@check_session_validity
@limiter.limit(STRATEGY_CHART_LIMIT)
def strategy_chart_data():
    """Get the combined premium time series for a user-built strategy."""
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
                {
                    "status": "error",
                    "message": "API key not configured. Please generate an API key in /apikey",
                }
            ), 401

        data = request.get_json(silent=True) or {}
        underlying = (data.get("underlying") or "").strip()
        exchange = (data.get("exchange") or "").strip()
        interval = (data.get("interval") or "5m").strip()
        try:
            days = int(data.get("days", 3))
        except (TypeError, ValueError):
            days = 3
        legs = data.get("legs") or []

        if not underlying or not exchange:
            return jsonify(
                {"status": "error", "message": "underlying and exchange are required"}
            ), 400
        if not isinstance(legs, list) or len(legs) == 0:
            return jsonify(
                {"status": "error", "message": "At least one leg is required"}
            ), 400

        success, response, status_code = get_strategy_chart_data(
            underlying=underlying,
            exchange=exchange,
            legs=legs,
            interval=interval,
            api_key=api_key,
            days=days,
        )
        return jsonify(response), status_code

    except Exception as e:
        logger.exception(f"Error in strategy chart API: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@strategy_chart_bp.route("/strategybuilder/api/multi-strike-oi", methods=["POST"])
@cross_origin()
@check_session_validity
@limiter.limit(STRATEGY_CHART_LIMIT)
def multi_strike_oi_data():
    """Get per-leg OI time series alongside the underlying price."""
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
                {
                    "status": "error",
                    "message": "API key not configured. Please generate an API key in /apikey",
                }
            ), 401

        data = request.get_json(silent=True) or {}
        underlying = (data.get("underlying") or "").strip()
        exchange = (data.get("exchange") or "").strip()
        interval = (data.get("interval") or "5m").strip()
        try:
            days = int(data.get("days", 3))
        except (TypeError, ValueError):
            days = 3
        legs = data.get("legs") or []

        if not underlying or not exchange:
            return jsonify(
                {"status": "error", "message": "underlying and exchange are required"}
            ), 400
        if not isinstance(legs, list) or len(legs) == 0:
            return jsonify(
                {"status": "error", "message": "At least one leg is required"}
            ), 400

        success, response, status_code = get_multi_strike_oi_data(
            underlying=underlying,
            exchange=exchange,
            legs=legs,
            interval=interval,
            api_key=api_key,
            days=days,
        )
        return jsonify(response), status_code

    except Exception as e:
        logger.exception(f"Error in multi-strike OI API: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@strategy_chart_bp.route("/strategybuilder/api/intervals", methods=["GET"])
@cross_origin()
@check_session_validity
def strategy_chart_intervals():
    """Proxy broker-supported intervals for the Strategy Chart tab."""
    try:
        login_username = session.get("user")
        if not login_username:
            return jsonify({"status": "error", "message": "Authentication required"}), 401

        api_key = get_api_key_for_tradingview(login_username)
        if not api_key:
            return jsonify({"status": "error", "message": "API key not configured"}), 401

        _, response, status_code = get_intervals(api_key=api_key)
        return jsonify(response), status_code

    except Exception as e:
        logger.exception(f"Error fetching intervals: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
