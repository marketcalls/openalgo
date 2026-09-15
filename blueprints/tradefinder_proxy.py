"""
Tradefinder Proxy Blueprint

Server-side proxy for tradefinder.in's Option Apex money-flow data, so the
/trading chart's "Money Flow (tradefinder)" indicator can fetch it without
exposing the server-side TF JWT (strategies/tf_jwt.txt) to the browser or
hitting CORS.

Endpoints:
    GET /trading/tradefinder/moneyflow - Get the options money-flow histogram
"""

from flask import Blueprint, jsonify, request, session

from services.tradefinder_client import (
    TradefinderExpiryError,
    TradefinderTokenError,
    get_money_flow_histogram,
)
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

tradefinder_proxy_bp = Blueprint("tradefinder_proxy_bp", __name__, url_prefix="/")


@tradefinder_proxy_bp.route("/trading/tradefinder/moneyflow", methods=["GET"])
@check_session_validity
def money_flow():
    if not session.get("user"):
        return jsonify({"status": "error", "message": "Authentication required"}), 401

    script = request.args.get("script", "").strip()[:20]
    if not script:
        return jsonify({"status": "error", "message": "script is required"}), 400

    exp = request.args.get("exp", "").strip()[:10] or None
    exp_type = request.args.get("exp_type", "wk").strip()[:3]
    if exp_type not in ("wk", "mo"):
        return jsonify({"status": "error", "message": "exp_type must be 'wk' or 'mo'"}), 400

    def _parse_ts(name: str) -> int | None:
        raw = request.args.get(name)
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    from_ts = _parse_ts("from")
    to_ts = _parse_ts("to")

    try:
        points = get_money_flow_histogram(
            script, exp=exp, exp_type=exp_type, from_ts=from_ts, to_ts=to_ts
        )
        return jsonify({"status": "success", "data": points}), 200
    except TradefinderExpiryError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except TradefinderTokenError as e:
        return jsonify({"status": "error", "message": str(e)}), 401
    except Exception as e:
        logger.exception(f"Error fetching tradefinder money flow: {e}")
        return jsonify(
            {"status": "error", "message": "An error occurred processing your request"}
        ), 500
