# blueprints/replay_data.py
"""
Replay Data Blueprint

API endpoints for uploading market data ZIP files (CM bhavcopy, FO bhavcopy, intraday 1m)
and managing replay sessions for sandbox paper trading.
"""

import os

from flask import Blueprint, jsonify, request

from limiter import limiter
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "50 per second")

replay_data_bp = Blueprint("replay_data_bp", __name__, url_prefix="/replay")


@replay_data_bp.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({"status": "error", "message": "Rate limit exceeded"}), 429


# =============================================================================
# Data Upload Endpoints
# =============================================================================


@replay_data_bp.route("/api/upload", methods=["POST"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def upload_data():
    """
    Upload a ZIP file containing market data.
    
    Form fields:
    - file: ZIP file (multipart/form-data)
    - upload_type: CM_BHAVCOPY | FO_BHAVCOPY | INTRADAY_1M
    """
    try:
        from services.replay_data_service import process_upload

        upload_type = request.form.get("upload_type", "").strip().upper()
        valid_types = {"CM_BHAVCOPY", "FO_BHAVCOPY", "INTRADAY_1M"}

        if upload_type not in valid_types:
            return jsonify({
                "status": "error",
                "message": f"Invalid upload_type. Must be one of: {', '.join(sorted(valid_types))}"
            }), 400

        if "file" not in request.files:
            return jsonify({"status": "error", "message": "No file provided"}), 400

        file = request.files["file"]
        result = process_upload(file, upload_type)

        status_code = 400 if result.get("status") == "error" else 200
        return jsonify(result), status_code

    except Exception as e:
        logger.exception(f"Error in upload: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# =============================================================================
# Replay Control Endpoints
# =============================================================================


@replay_data_bp.route("/api/replay/status", methods=["GET"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def replay_status():
    """Get current replay session status."""
    try:
        from services.replay_service import get_replay_session
        session = get_replay_session()
        return jsonify({"status": "success", "replay": session})
    except Exception as e:
        logger.exception(f"Error getting replay status: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@replay_data_bp.route("/api/replay/config", methods=["POST"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def replay_config():
    """
    Configure replay parameters.
    
    JSON body:
    - start_ts: Start timestamp (epoch seconds)
    - end_ts: End timestamp (epoch seconds)
    - speed: Speed multiplier (0.1 - 3600)
    - universe_mode: 'all' or 'active'
    """
    try:
        from services.replay_service import configure_replay

        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "JSON body required"}), 400

        result = configure_replay(
            start_ts=data.get("start_ts"),
            end_ts=data.get("end_ts"),
            speed=data.get("speed"),
            universe_mode=data.get("universe_mode"),
        )
        return jsonify({"status": "success", "replay": result})

    except Exception as e:
        logger.exception(f"Error configuring replay: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@replay_data_bp.route("/api/replay/start", methods=["POST"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def replay_start():
    """Start or resume replay."""
    try:
        from services.replay_service import start_replay
        success, message, state = start_replay()
        status_code = 200 if success else 400
        return jsonify({"status": "success" if success else "error", "message": message, "replay": state}), status_code
    except Exception as e:
        logger.exception(f"Error starting replay: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@replay_data_bp.route("/api/replay/pause", methods=["POST"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def replay_pause():
    """Pause replay."""
    try:
        from services.replay_service import pause_replay
        success, message, state = pause_replay()
        status_code = 200 if success else 400
        return jsonify({"status": "success" if success else "error", "message": message, "replay": state}), status_code
    except Exception as e:
        logger.exception(f"Error pausing replay: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@replay_data_bp.route("/api/replay/seek", methods=["POST"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def replay_seek():
    """
    Seek to a specific timestamp.
    
    JSON body:
    - target_ts: Target timestamp (epoch seconds)
    """
    try:
        from services.replay_service import seek_replay

        data = request.get_json()
        if not data or "target_ts" not in data:
            return jsonify({"status": "error", "message": "target_ts required"}), 400

        success, message, state = seek_replay(int(data["target_ts"]))
        status_code = 200 if success else 400
        return jsonify({"status": "success" if success else "error", "message": message, "replay": state}), status_code
    except Exception as e:
        logger.exception(f"Error seeking replay: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@replay_data_bp.route("/api/replay/stop", methods=["POST"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def replay_stop():
    """Stop replay and reset."""
    try:
        from services.replay_service import stop_replay
        success, message, state = stop_replay()
        return jsonify({"status": "success" if success else "error", "message": message, "replay": state})
    except Exception as e:
        logger.exception(f"Error stopping replay: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
