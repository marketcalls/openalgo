"""
Custom Straddle Blueprint
Serves simulated intraday ATM straddle PnL with automated N-point adjustments.
"""

from flask import Blueprint, jsonify, request, session
from flask_cors import cross_origin

from database.auth_db import get_api_key_for_tradingview, get_auth_token
from database.symbol import SymToken, db_session
from services.custom_straddle_service import get_custom_straddle_simulation
from services.intervals_service import get_intervals
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

custom_straddle_bp = Blueprint("custom_straddle_bp", __name__, url_prefix="/")


@custom_straddle_bp.route("/straddlepnl/api/simulate", methods=["POST"])
@cross_origin()
@check_session_validity
def simulate():
    """Run intraday straddle simulation with adjustments."""
    try:
        data = request.get_json(silent=True) or {}

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

        underlying = data.get("underlying", "").strip()
        exchange = data.get("exchange", "").strip()
        expiry_date = data.get("expiry_date", "").strip()
        interval = data.get("interval", "1m").strip()
        days = int(data.get("days", 1))
        adjustment_points = int(data.get("adjustment_points", 50))
        lot_size = int(data.get("lot_size", 65))
        lots = int(data.get("lots", 1))

        if not underlying or not exchange or not expiry_date:
            return jsonify(
                {"status": "error", "message": "underlying, exchange, and expiry_date are required"}
            ), 400

        if adjustment_points < 1:
            return jsonify({"status": "error", "message": "adjustment_points must be >= 1"}), 400

        if lot_size < 1 or lots < 1:
            return jsonify({"status": "error", "message": "lot_size and lots must be >= 1"}), 400

        success, response, status_code = get_custom_straddle_simulation(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            interval=interval,
            api_key=api_key,
            days=days,
            adjustment_points=adjustment_points,
            lot_size=lot_size,
            lots=lots,
        )

        return jsonify(response), status_code

    except Exception as e:
        logger.exception(f"Error in custom straddle API: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@custom_straddle_bp.route("/straddlepnl/api/lotsize", methods=["GET"])
@cross_origin()
@check_session_validity
def get_lotsize():
    """Get lot size for a given underlying and exchange from the symbol database."""
    try:
        underlying = request.args.get("underlying", "").strip().upper()
        exchange = request.args.get("exchange", "").strip().upper()

        if not underlying or not exchange:
            return jsonify({"status": "error", "message": "underlying and exchange required"}), 400

        # Query any option symbol for this underlying to get its lot size
        result = (
            db_session.query(SymToken.lotsize)
            .filter(
                SymToken.symbol.like(f"{underlying}%"),
                SymToken.exchange == exchange,
                SymToken.lotsize.isnot(None),
                SymToken.lotsize > 0,
            )
            .first()
        )

        if result:
            return jsonify({"status": "success", "lotsize": result.lotsize})
        return jsonify({"status": "success", "lotsize": None})

    except Exception as e:
        logger.exception(f"Error fetching lot size: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@custom_straddle_bp.route("/straddlepnl/api/intervals", methods=["GET"])
@cross_origin()
@check_session_validity
def custom_straddle_intervals():
    """Get broker-supported intervals."""
    try:
        login_username = session.get("user")
        if not login_username:
            return jsonify({"status": "error", "message": "Authentication required"}), 401

        api_key = get_api_key_for_tradingview(login_username)
        if not api_key:
            return jsonify({"status": "error", "message": "API key not configured"}), 401

        success, response, status_code = get_intervals(api_key=api_key)
        return jsonify(response), status_code

    except Exception as e:
        logger.exception(f"Error fetching intervals: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
