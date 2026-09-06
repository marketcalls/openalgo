"""
Volatility Surface Blueprint
Serves 3D implied volatility surface data for index options.
"""

from flask import Blueprint, g, jsonify, request, session
from flask_cors import cross_origin

from database.auth_db import (
    get_api_key_for_tradingview,
    get_auth_token,
    get_broker_name_for_user,
    get_username_by_apikey,
)
from services.vol_surface_service import get_vol_surface_data
from utils.logging import get_logger
from utils.session import apikey_or_session, check_session_validity

logger = get_logger(__name__)

vol_surface_bp = Blueprint("vol_surface_bp", __name__, url_prefix="/")


@vol_surface_bp.route("/volsurface/api/surface-data", methods=["POST"])
@cross_origin()
@apikey_or_session
def surface_data():
    """Get 3D volatility surface data across strikes and expiries."""
    try:
        # Broker comes from the identity the decorator already verified (the
        # apikey arrived via body, ?apikey or X-API-Key — all surfaced as
        # g.openalgo_apikey); browser logins fall back to the session, which
        # stores the broker name directly. Resolving via the verified
        # username (not the raw key) keeps usable credentials out of
        # broker_cache (cubic review, 2026-09-06).
        decorator_api_key = getattr(g, "openalgo_apikey", None)
        if decorator_api_key:
            broker = get_broker_name_for_user(get_username_by_apikey(decorator_api_key))
        else:
            broker = session.get("broker")
        if not broker:
            return jsonify({"status": "error", "message": "Broker not set in session"}), 400

        login_username = getattr(g, "openalgo_user", None) or session.get("user")
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
        expiry_dates = data.get("expiry_dates", [])
        strike_count = int(data.get("strike_count", 15))

        if not underlying or not exchange:
            return jsonify(
                {"status": "error", "message": "underlying and exchange are required"}
            ), 400

        if not expiry_dates or not isinstance(expiry_dates, list):
            return jsonify(
                {"status": "error", "message": "expiry_dates must be a non-empty list"}
            ), 400

        # Limit to 8 expiries max
        expiry_dates = expiry_dates[:8]
        strike_count = min(max(5, strike_count), 40)

        success, response, status_code = get_vol_surface_data(
            underlying=underlying,
            exchange=exchange,
            expiry_dates=expiry_dates,
            strike_count=strike_count,
            api_key=api_key,
        )

        return jsonify(response), status_code

    except Exception as e:
        logger.exception(f"Error in vol surface API: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
