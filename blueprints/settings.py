# blueprints/settings.py

from flask import Blueprint, jsonify, request

from database.settings_db import (
    get_analyze_mode,
    get_paper_price_source,
    set_analyze_mode,
    set_paper_price_source,
)
from sandbox.execution_thread import start_execution_engine, stop_execution_engine
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

settings_bp = Blueprint("settings_bp", __name__, url_prefix="/settings")


@settings_bp.route("/analyze-mode")
@check_session_validity
def get_mode():
    """Get current analyze mode setting"""
    try:
        return jsonify({"analyze_mode": get_analyze_mode()})
    except Exception as e:
        logger.exception(f"Error getting analyze mode: {str(e)}")
        return jsonify({"error": "Failed to get analyze mode"}), 500


@settings_bp.route("/analyze-mode/<int:mode>", methods=["POST"])
@check_session_validity
def set_mode(mode):
    """Set analyze mode setting and manage execution engine thread"""
    try:
        set_analyze_mode(bool(mode))
        mode_name = "Analyze" if mode else "Live"

        # Start or stop execution engine based on mode
        if mode:
            # Starting Analyze mode - start execution engine
            success, message = start_execution_engine()
            if success:
                logger.info("Execution engine started for Analyze mode")
            else:
                logger.warning(f"Failed to start execution engine: {message}")
        else:
            # Switching to Live mode - stop execution engine
            success, message = stop_execution_engine()
            if success:
                logger.info("Execution engine stopped for Live mode")
            else:
                logger.warning(f"Failed to stop execution engine: {message}")

        return jsonify(
            {
                "success": True,
                "analyze_mode": bool(mode),
                "message": f"Switched to {mode_name} Mode",
            }
        )
    except Exception as e:
        logger.exception(f"Error setting analyze mode: {str(e)}")
        return jsonify({"error": "Failed to set analyze mode"}), 500


@settings_bp.route("/paper-price-source", methods=["GET"])
@check_session_validity
def get_price_source():
    """Get current paper trading price source (LIVE or REPLAY)"""
    try:
        return jsonify({"paper_price_source": get_paper_price_source()})
    except Exception as e:
        logger.exception(f"Error getting paper price source: {str(e)}")
        return jsonify({"error": "Failed to get paper price source"}), 500


@settings_bp.route("/paper-price-source", methods=["POST"])
@check_session_validity
def set_price_source():
    """
    Set paper trading price source.

    JSON body:
        {"source": "LIVE" | "REPLAY"}
    """
    try:
        data = request.get_json()
        if not data or "source" not in data:
            return jsonify({"error": "JSON body with 'source' field required"}), 400

        source = str(data["source"]).upper().strip()
        set_paper_price_source(source)
        logger.info(f"Paper price source set to: {source}")
        return jsonify(
            {
                "success": True,
                "paper_price_source": source,
                "message": f"Paper price source set to {source}",
            }
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception(f"Error setting paper price source: {str(e)}")
        return jsonify({"error": "Failed to set paper price source"}), 500
