from flask import Blueprint, jsonify, request, session

from database.master_contract_status_db import check_if_ready, get_status
from utils.auth_utils import (
    MASTER_CONTRACT_BUSY_MESSAGE,
    get_master_contract_cutoff,
    is_master_contract_download_running,
    should_download_master_contract,
    try_start_master_contract_download,
)
from utils.logging import get_logger
from utils.runtime import gthread_active
from utils.session import check_session_validity

logger = get_logger(__name__)


def _cache_busy_response(broker: str | None):
    """The refusal for a manual cache reload or clear during a download, or None.

    While a master contract download runs, the symbol table is being deleted
    and rewritten, so a reload in the middle of it would load a partial
    universe. Refused only under the gthread worker, where requests run
    alongside the download; elsewhere the route behaves as it always has.
    """
    if broker and gthread_active() and is_master_contract_download_running(broker):
        return jsonify({"status": "error", "message": MASTER_CONTRACT_BUSY_MESSAGE}), 409
    return None

master_contract_status_bp = Blueprint("master_contract_status_bp", __name__, url_prefix="/api")


@master_contract_status_bp.route("/master-contract/status", methods=["GET"])
@check_session_validity
def get_master_contract_status():
    """Get the current master contract download status"""
    try:
        broker = session.get("broker")
        if not broker:
            return jsonify({"status": "error", "message": "No broker session found"}), 401

        status_data = get_status(broker)
        return jsonify(status_data), 200

    except Exception as e:
        logger.exception(f"Error getting master contract status: {str(e)}")
        return jsonify({"status": "error", "message": "Failed to get master contract status"}), 500


@master_contract_status_bp.route("/master-contract/ready", methods=["GET"])
@check_session_validity
def check_master_contract_ready():
    """Check if master contracts are ready for trading"""
    try:
        broker = session.get("broker")
        if not broker:
            return jsonify({"ready": False, "message": "No broker session found"}), 401

        is_ready = check_if_ready(broker)
        return jsonify(
            {
                "ready": is_ready,
                "message": "Master contracts are ready"
                if is_ready
                else "Master contracts not ready",
            }
        ), 200

    except Exception as e:
        logger.exception(f"Error checking master contract readiness: {str(e)}")
        return jsonify(
            {"ready": False, "message": "Failed to check master contract readiness"}
        ), 500


@master_contract_status_bp.route("/cache/status", methods=["GET"])
@check_session_validity
def get_cache_status():
    """Get the current symbol cache status and statistics"""
    try:
        from database.token_db_enhanced import get_cache_stats

        cache_info = get_cache_stats()
        return jsonify(cache_info), 200

    except ImportError:
        # Fallback if enhanced cache not available yet
        return jsonify(
            {"status": "not_available", "message": "Enhanced cache module not available"}
        ), 200
    except Exception as e:
        logger.exception(f"Error getting cache status: {str(e)}")
        return jsonify({"status": "error", "message": f"Failed to get cache status: {str(e)}"}), 500


@master_contract_status_bp.route("/cache/health", methods=["GET"])
@check_session_validity
def get_cache_health():
    """Get cache health metrics and recommendations"""
    try:
        from database.master_contract_cache_hook import get_cache_health

        health_info = get_cache_health()
        return jsonify(health_info), 200

    except ImportError:
        return jsonify(
            {
                "health_score": 0,
                "status": "not_available",
                "message": "Cache health monitoring not available",
            }
        ), 200
    except Exception as e:
        logger.exception(f"Error getting cache health: {str(e)}")
        return jsonify(
            {
                "health_score": 0,
                "status": "error",
                "message": f"Failed to get cache health: {str(e)}",
            }
        ), 500


@master_contract_status_bp.route("/cache/reload", methods=["POST"])
@check_session_validity
def reload_cache():
    """Manually trigger cache reload"""
    try:
        broker = session.get("broker")
        if not broker:
            return jsonify({"status": "error", "message": "No broker session found"}), 401

        busy = _cache_busy_response(broker)
        if busy is not None:
            return busy

        from database.master_contract_cache_hook import load_symbols_to_cache

        success = load_symbols_to_cache(broker)

        if success:
            return jsonify(
                {
                    "status": "success",
                    "message": f"Cache reloaded successfully for broker: {broker}",
                }
            ), 200
        else:
            return jsonify({"status": "error", "message": "Failed to reload cache"}), 500

    except ImportError:
        return jsonify(
            {"status": "error", "message": "Cache reload functionality not available"}
        ), 501
    except Exception as e:
        logger.exception(f"Error reloading cache: {str(e)}")
        return jsonify({"status": "error", "message": f"Failed to reload cache: {str(e)}"}), 500


@master_contract_status_bp.route("/cache/clear", methods=["POST"])
@check_session_validity
def clear_cache():
    """Manually clear the cache"""
    try:
        busy = _cache_busy_response(session.get("broker"))
        if busy is not None:
            return busy

        from database.token_db_enhanced import clear_cache as clear_symbol_cache

        clear_symbol_cache()

        return jsonify({"status": "success", "message": "Cache cleared successfully"}), 200

    except ImportError:
        return jsonify(
            {"status": "error", "message": "Cache clear functionality not available"}
        ), 501
    except Exception as e:
        logger.exception(f"Error clearing cache: {str(e)}")
        return jsonify({"status": "error", "message": f"Failed to clear cache: {str(e)}"}), 500


@master_contract_status_bp.route("/master-contract/download", methods=["POST"])
@check_session_validity
def force_master_contract_download():
    """Force a fresh master contract download regardless of smart download logic"""
    try:
        broker = session.get("broker")
        if not broker:
            return jsonify({"status": "error", "message": "No broker session found"}), 401

        # Get request body for force flag
        data = request.get_json(silent=True) or {}
        force = data.get("force", False)

        if not force:
            # Check if download is needed using smart logic
            should_download, reason = should_download_master_contract(broker)
            if not should_download:
                return jsonify({
                    "status": "skipped",
                    "message": reason,
                    "should_download": False
                }), 200

        # Claim the broker, then initialize status and start the download. A
        # download already running owns the status row: resetting it here and
        # then being refused would leave it pending after that download had
        # reported success, while telling the trader a new one had started.
        if not try_start_master_contract_download(broker, reset_status=True):
            return jsonify({
                "status": "error",
                "message": MASTER_CONTRACT_BUSY_MESSAGE,
                "started": False
            }), 409

        return jsonify({
            "status": "success",
            "message": "Master contract download started",
            "started": True
        }), 200

    except Exception as e:
        logger.exception(f"Error starting master contract download: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Failed to start download: {str(e)}"
        }), 500


@master_contract_status_bp.route("/master-contract/smart-status", methods=["GET"])
@check_session_validity
def get_smart_download_status():
    """Get detailed status including smart download information"""
    try:
        broker = session.get("broker")
        if not broker:
            return jsonify({"status": "error", "message": "No broker session found"}), 401

        # Get full status with smart download fields
        status_data = get_status(broker)

        # Add smart download recommendation
        should_download, reason = should_download_master_contract(broker)
        cutoff_hour, cutoff_minute, tz = get_master_contract_cutoff(broker)
        import pytz
        tz_label = "UTC" if tz is pytz.utc else "IST"
        status_data["smart_download"] = {
            "should_download": should_download,
            "reason": reason,
            "cutoff_time": f"{cutoff_hour:02d}:{cutoff_minute:02d}",
            "cutoff_timezone": tz_label
        }

        return jsonify(status_data), 200

    except Exception as e:
        logger.exception(f"Error getting smart download status: {str(e)}")
        return jsonify({"status": "error", "message": "Failed to get status"}), 500
