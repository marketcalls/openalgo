# blueprints/settings.py

from flask import Blueprint, jsonify, request, session

from database.settings_db import get_analyze_mode, set_analyze_mode
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


# ── Risk Limits ──────────────────────────────────────────────────────────────


@settings_bp.route("/risk-limits")
@check_session_validity
def get_risk_limits_route():
    """Get current risk limits for the logged-in user."""
    try:
        from database.risk_limits_db import get_risk_limits

        user = session.get("user")
        if not user:
            return jsonify({"error": "Not authenticated"}), 401

        row = get_risk_limits(user)
        if row is None:
            return jsonify({
                "enabled": False,
                "daily_profit_target": None,
                "daily_loss_limit": None,
                "daily_trade_limit": None,
                "breached": False,
                "breached_reason": None,
            })

        return jsonify({
            "enabled": row.enabled,
            "daily_profit_target": row.daily_profit_target,
            "daily_loss_limit": row.daily_loss_limit,
            "daily_trade_limit": row.daily_trade_limit,
            "breached": row.breached,
            "breached_reason": row.breached_reason,
        })
    except Exception as e:
        logger.exception(f"Error getting risk limits: {e}")
        return jsonify({"error": "Failed to get risk limits"}), 500


@settings_bp.route("/risk-limits", methods=["POST"])
@check_session_validity
def set_risk_limits_route():
    """Create or update risk limits for the logged-in user."""
    try:
        from database.risk_limits_db import upsert_risk_limits

        user = session.get("user")
        if not user:
            return jsonify({"error": "Not authenticated"}), 401

        data = request.get_json(silent=True) or {}

        raw_enabled = data.get("enabled", False)
        if not isinstance(raw_enabled, bool):
            return jsonify({"error": "enabled must be a boolean"}), 400
        enabled = raw_enabled
        daily_profit_target = data.get("daily_profit_target")
        daily_loss_limit = data.get("daily_loss_limit")
        daily_trade_limit = data.get("daily_trade_limit")

        # Validate: if enabled, at least one limit must be set
        if enabled and daily_profit_target is None and daily_loss_limit is None and daily_trade_limit is None:
            return jsonify({"error": "Please set at least one risk limit value"}), 400

        # Validate: values must be positive if provided
        if daily_profit_target is not None:
            daily_profit_target = float(daily_profit_target)
            if daily_profit_target <= 0:
                return jsonify({"error": "Profit target must be positive"}), 400

        if daily_loss_limit is not None:
            daily_loss_limit = float(daily_loss_limit)
            if daily_loss_limit <= 0:
                return jsonify({"error": "Loss limit must be positive"}), 400

        if daily_trade_limit is not None:
            daily_trade_limit = int(daily_trade_limit)
            if daily_trade_limit <= 0:
                return jsonify({"error": "Trade limit must be positive"}), 400

        ok = upsert_risk_limits(user, enabled, daily_profit_target, daily_loss_limit, daily_trade_limit)
        if ok:
            return jsonify({"success": True, "message": "Risk limits updated"})
        return jsonify({"error": "Failed to save risk limits"}), 500
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"Invalid value: {e}"}), 400
    except Exception as e:
        logger.exception(f"Error setting risk limits: {e}")
        return jsonify({"error": "Failed to set risk limits"}), 500


@settings_bp.route("/risk-limits/reset", methods=["POST"])
@check_session_validity
def reset_risk_limits_route():
    """Manually reset the breached latch for today."""
    try:
        from database.risk_limits_db import RiskLimits, db_session, _risk_limits_cache

        user = session.get("user")
        if not user:
            return jsonify({"error": "Not authenticated"}), 401

        row = RiskLimits.query.filter_by(user=user).first()
        if row and row.breached:
            row.breached = False
            row.breached_reason = None
            row.breached_at = None
            db_session.commit()
            _risk_limits_cache.pop(f"risk_limits:{user}", None)
            return jsonify({"success": True, "message": "Risk limits reset"})

        return jsonify({"success": True, "message": "No active breach to reset"})
    except Exception as e:
        logger.exception(f"Error resetting risk limits: {e}")
        return jsonify({"error": "Failed to reset risk limits"}), 500
