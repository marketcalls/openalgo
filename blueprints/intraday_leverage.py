# blueprints/intraday_leverage.py
# REST API for per-symbol intraday leverage multipliers.
# Used by the Position Calculator to look up each stock's
# intraday leverage multiplier for position sizing.

from flask import Blueprint, jsonify, request

from database.intraday_leverage_db import get_multiplier, get_multipliers_bulk
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

intraday_leverage_bp = Blueprint("intraday_leverage_bp", __name__, url_prefix="/intraday-leverage")


@intraday_leverage_bp.route("/api/<symbol>", methods=["GET"])
@check_session_validity
def get_leverage(symbol):
    """Get intraday leverage multiplier for a single symbol.

    Query param: exchange (default NSE)
    Returns: { status, data: { symbol, exchange, multiplier } }
    """
    exchange = request.args.get("exchange", "NSE").upper()
    multiplier = get_multiplier(symbol.upper(), exchange)

    if multiplier is None:
        return jsonify(
            {
                "status": "success",
                "data": {
                    "symbol": symbol.upper(),
                    "exchange": exchange,
                    "multiplier": None,
                    "message": "Symbol not found in leverage table",
                },
            }
        )

    return jsonify(
        {
            "status": "success",
            "data": {
                "symbol": symbol.upper(),
                "exchange": exchange,
                "multiplier": multiplier,
            },
        }
    )


@intraday_leverage_bp.route("/api/batch", methods=["POST"])
@check_session_validity
def get_leverage_batch():
    """Get leverage multipliers for multiple symbols.

    Request body: { symbols: ["SBIN", "RELIANCE", ...] }
    Returns: { status, data: [{ symbol, exchange, multiplier }, ...] }
    """
    data = request.get_json()
    if data is None or "symbols" not in data:
        return jsonify({"status": "error", "message": "Missing symbols field"}), 400

    symbols = data["symbols"]
    if not isinstance(symbols, list) or len(symbols) > 100:
        return jsonify(
            {
                "status": "error",
                "message": "symbols must be a list of up to 100 strings",
            }
        ), 400

    exchange = data.get("exchange", "NSE").upper()
    results = get_multipliers_bulk(symbols, exchange)

    response = [
        {
            "symbol": s.upper(),
            "exchange": exchange,
            "multiplier": results.get(s),
        }
        for s in symbols
    ]

    return jsonify({"status": "success", "data": response})
