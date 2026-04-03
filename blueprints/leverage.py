# blueprints/leverage.py
# Leverage configuration for crypto brokers (Delta Exchange)
# Stores a single common leverage value in leverage_config table.

from flask import Blueprint, jsonify, request

from database.leverage_db import get_leverage, set_leverage
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

leverage_bp = Blueprint("leverage_bp", __name__, url_prefix="/leverage")


@leverage_bp.route("/api/current", methods=["GET"])
@check_session_validity
def get_current():
    """Get the current common leverage setting."""
    return jsonify({
        "status": "success",
        "leverage": get_leverage(),
    })


@leverage_bp.route("/api/update", methods=["POST"])
@check_session_validity
def update_leverage():
    """
    Set common leverage for all crypto futures orders.
    Expects JSON: {"leverage": 10}
    """
    data = request.get_json()
    if data is None or "leverage" not in data:
        return jsonify({"status": "error", "message": "Missing leverage field"}), 400

    try:
        leverage = float(data["leverage"])
        import math
        if math.isnan(leverage) or math.isinf(leverage):
            return jsonify({"status": "error", "message": "Invalid leverage value"}), 400
        if leverage < 0:
            return jsonify({"status": "error", "message": "Leverage cannot be negative"}), 400
        if not leverage.is_integer():
            return jsonify({"status": "error", "message": "Leverage must be a whole number"}), 400
        leverage = int(leverage)
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid leverage value"}), 400

    set_leverage(leverage)

    label = f"{int(leverage)}x" if leverage > 0 else "Default"
    return jsonify({
        "status": "success",
        "message": f"Leverage set to {label}",
    })
