"""OpenAlgo Strategy Hub — REST API and page route.

Exposes the discovered lean_trading_engine strategy registry (populated by
blueprints/strategy_zmq_listener.py) to the React dashboard, plus start/stop
control endpoints. Real-time updates are pushed over SocketIO
(`strategy_hub_update`); these REST endpoints only serve the initial page
load and manual actions.
"""

from flask import Blueprint, jsonify, session

from blueprints.strategy_zmq_listener import get_registry_snapshot, send_command
from utils.logging import get_logger
from utils.session import check_session_validity

strategy_hub_bp = Blueprint("strategy_hub_bp", __name__, url_prefix="/strategy-hub")
logger = get_logger(__name__)


@strategy_hub_bp.route("", methods=["GET"])
@strategy_hub_bp.route("/", methods=["GET"])
def strategy_hub_page():
    """Serve the React Strategy Hub dashboard on a direct navigation or refresh."""
    from blueprints.react_app import serve_react_app

    return serve_react_app()


@strategy_hub_bp.route("/api/strategies", methods=["GET"])
@check_session_validity
def list_strategies():
    """Return the current discovered-strategy registry as a list."""
    registry = get_registry_snapshot()
    strategies = sorted(registry.values(), key=lambda s: s["strategy_id"])
    return jsonify({"status": "success", "data": strategies})


@strategy_hub_bp.route("/api/strategies/<strategy_id>/stop", methods=["POST"])
@check_session_validity
def stop_strategy(strategy_id):
    """Stop a strategy: ZMQ STOP signal first, systemd fallback."""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    success, message = send_command(strategy_id, "STOP")
    logger.info("Strategy Hub stop requested for %s by %s: %s", strategy_id, user_id, message)
    return jsonify({"status": "success" if success else "error", "message": message})


@strategy_hub_bp.route("/api/strategies/<strategy_id>/start", methods=["POST"])
@check_session_validity
def start_strategy(strategy_id):
    """Start a strategy: ZMQ START signal first, systemd fallback."""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    success, message = send_command(strategy_id, "START")
    logger.info("Strategy Hub start requested for %s by %s: %s", strategy_id, user_id, message)
    return jsonify({"status": "success" if success else "error", "message": message})
