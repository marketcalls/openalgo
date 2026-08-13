"""
Gamma Density Blueprint

Serves Γ×OI gamma density and convexity-zone data for option chains.

Endpoint:
    POST /gammadensity/api/gamma-data  - Gamma density + expected-move bands

Underlyings and expiries are served by the shared search blueprint
(/search/api/underlyings, /search/api/expiries).
"""

import re

from flask import Blueprint, jsonify, request, session
from flask_cors import cross_origin

from database.auth_db import get_api_key_for_tradingview
from services.gamma_density_service import calculate_gamma_density
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

gamma_density_bp = Blueprint("gamma_density_bp", __name__, url_prefix="/")


@gamma_density_bp.route("/gammadensity/api/gamma-data", methods=["POST"])
@cross_origin()
@check_session_validity
def gamma_data():
    """Get gamma density (Γ×OI) and convexity-zone data for all strikes."""
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

        success, response, status_code = calculate_gamma_density(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            api_key=api_key,
        )

        return jsonify(response), status_code

    except Exception as e:
        logger.exception(f"Error in Gamma Density API: {e}")
        return jsonify(
            {"status": "error", "message": "An error occurred processing your request"}
        ), 500
