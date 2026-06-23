"""Arbitrage Blueprint

Serves the futures calendar-spread arbitrage universe.

Endpoints:
    GET /arbitrage/api/universe?exchanges=NFO,MCX
        Returns the near/next/third-month futures pairs and the de-duplicated
        symbol list to subscribe to over the market-data WebSocket.
"""

from flask import Blueprint, jsonify, request, session
from flask_cors import cross_origin

from database.auth_db import get_api_key_for_tradingview
from services.arbitrage_service import DEFAULT_EXCHANGES, get_arbitrage_universe
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

arbitrage_bp = Blueprint("arbitrage_bp", __name__, url_prefix="/")


@arbitrage_bp.route("/arbitrage/api/universe", methods=["GET"])
@cross_origin()
@check_session_validity
def arbitrage_universe():
    """Return the calendar-spread universe for the requested exchanges."""
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

        raw = (request.args.get("exchanges") or "").strip()
        if raw:
            exchanges = [ex.strip().upper() for ex in raw.split(",") if ex.strip()]
        else:
            exchanges = list(DEFAULT_EXCHANGES)

        success, response, status_code = get_arbitrage_universe(
            exchanges=exchanges,
            api_key=api_key,
        )

        return jsonify(response), status_code

    except Exception as e:
        logger.exception(f"Error in arbitrage universe API: {e}")
        return (
            jsonify({"status": "error", "message": "An error occurred processing your request"}),
            500,
        )
