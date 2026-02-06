"""
Strategy Dashboard API — REST endpoints for the Strategy Risk Management dashboard.

Provides snapshot data for initial page load; SocketIO handles live updates.
All endpoints use session-based auth (same as strategy_bp).

Endpoints:
- GET  /strategy/api/dashboard                              — all strategies with positions & PnL summary
- GET  /strategy/api/strategy/<id>/positions                — positions for a strategy
- GET  /strategy/api/strategy/<id>/orders                   — strategy orderbook
- GET  /strategy/api/strategy/<id>/trades                   — strategy tradebook
- GET  /strategy/api/strategy/<id>/pnl                      — PnL + risk metrics + daily chart data
- PUT  /strategy/api/strategy/<id>/risk                     — update strategy risk defaults
- PUT  /strategy/api/strategy/<id>/symbol/<mid>/risk        — update symbol risk overrides
- POST /strategy/api/strategy/<id>/risk/activate            — activate risk monitoring
- POST /strategy/api/strategy/<id>/risk/deactivate          — deactivate risk monitoring
- POST /strategy/api/strategy/<id>/position/<pid>/close     — manual close
- POST /strategy/api/strategy/<id>/positions/close-all      — close all positions
- DELETE /strategy/api/strategy/<id>/position/<pid>         — delete closed position record
"""

from flask import Blueprint, jsonify, request, session

from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

strategy_dashboard_bp = Blueprint(
    "strategy_dashboard_bp", __name__, url_prefix="/strategy"
)


def _get_user_id():
    """Get current user ID from session."""
    return session.get("user")


def _verify_strategy_ownership(strategy_id, strategy_type, user_id):
    """Verify the user owns this strategy. Returns (strategy, error_response)."""
    if strategy_type == "chartink":
        from database.chartink_db import ChartinkStrategy, db_session

        strategy = db_session.query(ChartinkStrategy).get(strategy_id)
    else:
        from database.strategy_db import Strategy, db_session

        strategy = db_session.query(Strategy).get(strategy_id)

    if not strategy:
        return None, (jsonify({"status": "error", "message": "Strategy not found"}), 404)
    if strategy.user_id != user_id:
        return None, (jsonify({"status": "error", "message": "Unauthorized"}), 403)
    return strategy, None


# ──────────────────────────────────────────────────────────────
# Dashboard Overview
# ──────────────────────────────────────────────────────────────


@strategy_dashboard_bp.route("/api/dashboard")
@check_session_validity
def api_dashboard():
    """Get all strategies with positions and PnL summary for the current user."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    try:
        from database.strategy_db import get_user_strategies
        from database.chartink_db import get_user_strategies as get_chartink_strategies
        from database.strategy_position_db import get_active_positions, get_strategy_positions
        from services.strategy_pnl_service import (
            calculate_strategy_metrics,
            calculate_strategy_pnl_summary,
        )

        strategies_data = []
        total_pnl = 0
        total_open_positions = 0

        # Webhook strategies
        for s in get_user_strategies(user_id):
            pnl_summary = calculate_strategy_pnl_summary(s.id, "webhook")
            positions = get_strategy_positions(s.id, "webhook")
            metrics = calculate_strategy_metrics(s.id, "webhook")

            strategies_data.append({
                "id": s.id,
                "name": s.name,
                "strategy_type": "webhook",
                "is_active": s.is_active,
                "risk_monitoring": getattr(s, "risk_monitoring", "active"),
                "trading_mode": s.trading_mode,
                "positions": [_position_to_dict(p) for p in positions],
                "total_pnl": pnl_summary["total_pnl"],
                "realized_pnl": pnl_summary["realized_pnl"],
                "unrealized_pnl": pnl_summary["unrealized_pnl"],
                "position_count": pnl_summary["position_count"],
                "total_trades": metrics.get("total_trades", 0),
                "win_rate": metrics.get("win_rate", 0),
                "profit_factor": metrics.get("profit_factor", 0),
                "max_drawdown": metrics.get("max_drawdown", 0),
            })
            total_pnl += pnl_summary["total_pnl"]
            total_open_positions += pnl_summary["position_count"]

        # Chartink strategies
        for s in get_chartink_strategies(user_id):
            pnl_summary = calculate_strategy_pnl_summary(s.id, "chartink")
            positions = get_strategy_positions(s.id, "chartink")
            metrics = calculate_strategy_metrics(s.id, "chartink")

            strategies_data.append({
                "id": s.id,
                "name": s.name,
                "strategy_type": "chartink",
                "is_active": s.is_active,
                "risk_monitoring": getattr(s, "risk_monitoring", "active"),
                "trading_mode": getattr(s, "trading_mode", "LONG"),
                "positions": [_position_to_dict(p) for p in positions],
                "total_pnl": pnl_summary["total_pnl"],
                "realized_pnl": pnl_summary["realized_pnl"],
                "unrealized_pnl": pnl_summary["unrealized_pnl"],
                "position_count": pnl_summary["position_count"],
                "total_trades": metrics.get("total_trades", 0),
                "win_rate": metrics.get("win_rate", 0),
                "profit_factor": metrics.get("profit_factor", 0),
                "max_drawdown": metrics.get("max_drawdown", 0),
            })
            total_pnl += pnl_summary["total_pnl"]
            total_open_positions += pnl_summary["position_count"]

        active_count = sum(1 for s in strategies_data if s["risk_monitoring"] == "active")
        paused_count = sum(1 for s in strategies_data if s["risk_monitoring"] == "paused")

        return jsonify({
            "status": "success",
            "strategies": strategies_data,
            "summary": {
                "active_strategies": active_count,
                "paused_strategies": paused_count,
                "open_positions": total_open_positions,
                "total_pnl": round(total_pnl, 2),
            },
        })

    except Exception as e:
        logger.exception(f"Error fetching dashboard: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# ──────────────────────────────────────────────────────────────
# Positions
# ──────────────────────────────────────────────────────────────


@strategy_dashboard_bp.route("/api/strategy/<int:strategy_id>/positions")
@check_session_validity
def api_get_positions(strategy_id):
    """Get all positions for a strategy (open by default, ?include_closed=true for all)."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy_type = request.args.get("type", "webhook")
    strategy, err = _verify_strategy_ownership(strategy_id, strategy_type, user_id)
    if err:
        return err

    try:
        from database.strategy_position_db import get_strategy_positions

        include_closed = request.args.get("include_closed", "false").lower() == "true"
        positions = get_strategy_positions(strategy_id, strategy_type, include_closed=include_closed)

        return jsonify({
            "status": "success",
            "positions": [_position_to_dict(p) for p in positions],
        })

    except Exception as e:
        logger.exception(f"Error fetching positions: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# ──────────────────────────────────────────────────────────────
# Orders & Trades
# ──────────────────────────────────────────────────────────────


@strategy_dashboard_bp.route("/api/strategy/<int:strategy_id>/orders")
@check_session_validity
def api_get_orders(strategy_id):
    """Get all orders for a strategy."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy_type = request.args.get("type", "webhook")
    strategy, err = _verify_strategy_ownership(strategy_id, strategy_type, user_id)
    if err:
        return err

    try:
        from database.strategy_position_db import get_strategy_orders

        orders = get_strategy_orders(strategy_id, strategy_type)
        return jsonify({
            "status": "success",
            "orders": [
                {
                    "id": o.id,
                    "orderid": o.orderid,
                    "symbol": o.symbol,
                    "exchange": o.exchange,
                    "action": o.action,
                    "quantity": o.quantity,
                    "product_type": o.product_type,
                    "price_type": o.price_type,
                    "order_status": o.order_status,
                    "average_price": o.average_price,
                    "filled_quantity": o.filled_quantity,
                    "is_entry": o.is_entry,
                    "exit_reason": o.exit_reason,
                    "created_at": o.created_at.isoformat() if o.created_at else None,
                    "updated_at": o.updated_at.isoformat() if o.updated_at else None,
                }
                for o in orders
            ],
        })

    except Exception as e:
        logger.exception(f"Error fetching orders: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@strategy_dashboard_bp.route("/api/strategy/<int:strategy_id>/trades")
@check_session_validity
def api_get_trades(strategy_id):
    """Get all trades for a strategy."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy_type = request.args.get("type", "webhook")
    strategy, err = _verify_strategy_ownership(strategy_id, strategy_type, user_id)
    if err:
        return err

    try:
        from database.strategy_position_db import get_strategy_trades

        trades = get_strategy_trades(strategy_id, strategy_type)
        return jsonify({
            "status": "success",
            "trades": [
                {
                    "id": t.id,
                    "orderid": t.orderid,
                    "symbol": t.symbol,
                    "exchange": t.exchange,
                    "action": t.action,
                    "quantity": t.quantity,
                    "price": t.price,
                    "trade_type": t.trade_type,
                    "exit_reason": t.exit_reason,
                    "pnl": round(t.pnl or 0, 2),
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in trades
            ],
        })

    except Exception as e:
        logger.exception(f"Error fetching trades: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# ──────────────────────────────────────────────────────────────
# PnL & Risk Metrics
# ──────────────────────────────────────────────────────────────


@strategy_dashboard_bp.route("/api/strategy/<int:strategy_id>/pnl")
@check_session_validity
def api_get_pnl(strategy_id):
    """Get PnL, risk metrics, exit breakdown, and daily chart data for a strategy."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy_type = request.args.get("type", "webhook")
    strategy, err = _verify_strategy_ownership(strategy_id, strategy_type, user_id)
    if err:
        return err

    try:
        from services.strategy_pnl_service import (
            calculate_strategy_metrics,
            calculate_strategy_pnl_summary,
            get_equity_curve_data,
            get_exit_breakdown,
        )

        pnl_summary = calculate_strategy_pnl_summary(strategy_id, strategy_type)
        metrics = calculate_strategy_metrics(strategy_id, strategy_type)
        breakdown = get_exit_breakdown(strategy_id, strategy_type)
        daily_pnl = get_equity_curve_data(strategy_id, strategy_type)

        return jsonify({
            "status": "success",
            "pnl": pnl_summary,
            "risk_metrics": metrics,
            "exit_breakdown": breakdown,
            "daily_pnl": daily_pnl,
        })

    except Exception as e:
        logger.exception(f"Error fetching PnL: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# ──────────────────────────────────────────────────────────────
# Risk Configuration
# ──────────────────────────────────────────────────────────────


RISK_FIELDS = {
    "default_stoploss_type", "default_stoploss_value",
    "default_target_type", "default_target_value",
    "default_trailstop_type", "default_trailstop_value",
    "default_breakeven_type", "default_breakeven_threshold",
    "risk_monitoring", "auto_squareoff_time", "default_exit_execution",
}

SYMBOL_RISK_FIELDS = {
    "stoploss_type", "stoploss_value",
    "target_type", "target_value",
    "trailstop_type", "trailstop_value",
    "breakeven_type", "breakeven_threshold",
    "exit_execution",
    "combined_stoploss_type", "combined_stoploss_value",
    "combined_target_type", "combined_target_value",
    "combined_trailstop_type", "combined_trailstop_value",
}


@strategy_dashboard_bp.route("/api/strategy/<int:strategy_id>/risk", methods=["PUT"])
@check_session_validity
def api_update_risk(strategy_id):
    """Update strategy-level risk defaults."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy_type = request.args.get("type", "webhook")
    strategy, err = _verify_strategy_ownership(strategy_id, strategy_type, user_id)
    if err:
        return err

    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No data provided"}), 400

        # Only allow known risk fields
        updates = {k: v for k, v in data.items() if k in RISK_FIELDS}
        if not updates:
            return jsonify({"status": "error", "message": "No valid risk fields provided"}), 400

        if strategy_type == "chartink":
            from database.chartink_db import db_session
        else:
            from database.strategy_db import db_session

        for key, value in updates.items():
            setattr(strategy, key, value)
        db_session.commit()

        return jsonify({
            "status": "success",
            "message": "Risk configuration updated",
            "data": updates,
        })

    except Exception as e:
        logger.exception(f"Error updating risk config: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@strategy_dashboard_bp.route(
    "/api/strategy/<int:strategy_id>/symbol/<int:mapping_id>/risk", methods=["PUT"]
)
@check_session_validity
def api_update_symbol_risk(strategy_id, mapping_id):
    """Update symbol-level risk overrides."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy_type = request.args.get("type", "webhook")
    strategy, err = _verify_strategy_ownership(strategy_id, strategy_type, user_id)
    if err:
        return err

    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No data provided"}), 400

        # Get the mapping
        if strategy_type == "chartink":
            from database.chartink_db import ChartinkSymbolMapping, db_session

            mapping = db_session.query(ChartinkSymbolMapping).get(mapping_id)
        else:
            from database.strategy_db import StrategySymbolMapping, db_session

            mapping = db_session.query(StrategySymbolMapping).get(mapping_id)

        if not mapping or mapping.strategy_id != strategy_id:
            return jsonify({"status": "error", "message": "Symbol mapping not found"}), 404

        updates = {k: v for k, v in data.items() if k in SYMBOL_RISK_FIELDS}
        if not updates:
            return jsonify({"status": "error", "message": "No valid risk fields provided"}), 400

        for key, value in updates.items():
            setattr(mapping, key, value)
        db_session.commit()

        return jsonify({
            "status": "success",
            "message": "Symbol risk configuration updated",
            "data": updates,
        })

    except Exception as e:
        logger.exception(f"Error updating symbol risk config: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# ──────────────────────────────────────────────────────────────
# Risk Monitoring Control
# ──────────────────────────────────────────────────────────────


@strategy_dashboard_bp.route(
    "/api/strategy/<int:strategy_id>/risk/activate", methods=["POST"]
)
@check_session_validity
def api_activate_risk(strategy_id):
    """Activate risk monitoring for a strategy."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy_type = request.args.get("type", "webhook")
    strategy, err = _verify_strategy_ownership(strategy_id, strategy_type, user_id)
    if err:
        return err

    try:
        if strategy_type == "chartink":
            from database.chartink_db import db_session
        else:
            from database.strategy_db import db_session

        strategy.risk_monitoring = "active"
        db_session.commit()

        # Tell risk engine to subscribe this strategy's positions
        from services.strategy_risk_engine import risk_engine

        risk_engine.activate_strategy(strategy_id)

        return jsonify({
            "status": "success",
            "message": "Risk monitoring activated",
        })

    except Exception as e:
        logger.exception(f"Error activating risk: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@strategy_dashboard_bp.route(
    "/api/strategy/<int:strategy_id>/risk/deactivate", methods=["POST"]
)
@check_session_validity
def api_deactivate_risk(strategy_id):
    """Deactivate risk monitoring for a strategy."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy_type = request.args.get("type", "webhook")
    strategy, err = _verify_strategy_ownership(strategy_id, strategy_type, user_id)
    if err:
        return err

    try:
        if strategy_type == "chartink":
            from database.chartink_db import db_session
        else:
            from database.strategy_db import db_session

        strategy.risk_monitoring = "paused"
        db_session.commit()

        # Tell risk engine to unsubscribe this strategy's positions
        from services.strategy_risk_engine import risk_engine

        risk_engine.deactivate_strategy(strategy_id)

        return jsonify({
            "status": "success",
            "message": "Risk monitoring deactivated",
        })

    except Exception as e:
        logger.exception(f"Error deactivating risk: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# ──────────────────────────────────────────────────────────────
# Manual Close
# ──────────────────────────────────────────────────────────────


@strategy_dashboard_bp.route(
    "/api/strategy/<int:strategy_id>/position/<int:position_id>/close", methods=["POST"]
)
@check_session_validity
def api_close_position(strategy_id, position_id):
    """Manually close a single position."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy_type = request.args.get("type", "webhook")
    strategy, err = _verify_strategy_ownership(strategy_id, strategy_type, user_id)
    if err:
        return err

    try:
        # Verify position belongs to this strategy
        from database.strategy_position_db import get_position

        position = get_position(position_id)
        if not position or position.strategy_id != strategy_id:
            return jsonify({"status": "error", "message": "Position not found"}), 404
        if position.quantity == 0:
            return jsonify({"status": "error", "message": "Position already closed"}), 400

        from services.strategy_risk_engine import risk_engine

        success = risk_engine.close_position(position_id)
        if success:
            return jsonify({
                "status": "success",
                "message": f"Close order placed for {position.symbol}",
            })
        else:
            return jsonify({
                "status": "error",
                "message": "Position is not in active state or already being closed",
            }), 409

    except Exception as e:
        logger.exception(f"Error closing position: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@strategy_dashboard_bp.route(
    "/api/strategy/<int:strategy_id>/positions/close-all", methods=["POST"]
)
@check_session_validity
def api_close_all_positions(strategy_id):
    """Close all active positions for a strategy."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy_type = request.args.get("type", "webhook")
    strategy, err = _verify_strategy_ownership(strategy_id, strategy_type, user_id)
    if err:
        return err

    try:
        from services.strategy_risk_engine import risk_engine

        count = risk_engine.close_all_positions(strategy_id)
        return jsonify({
            "status": "success",
            "message": f"Close orders placed for {count} positions",
            "data": {"positions_closed": count},
        })

    except Exception as e:
        logger.exception(f"Error closing all positions: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# ──────────────────────────────────────────────────────────────
# Position Deletion
# ──────────────────────────────────────────────────────────────


@strategy_dashboard_bp.route(
    "/api/strategy/<int:strategy_id>/position/<int:position_id>", methods=["DELETE"]
)
@check_session_validity
def api_delete_position(strategy_id, position_id):
    """Delete a closed position record (quantity must be 0)."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy_type = request.args.get("type", "webhook")
    strategy, err = _verify_strategy_ownership(strategy_id, strategy_type, user_id)
    if err:
        return err

    try:
        from database.strategy_position_db import get_position

        position = get_position(position_id)
        if not position or position.strategy_id != strategy_id:
            return jsonify({"status": "error", "message": "Position not found"}), 404

        from database.strategy_position_db import delete_position

        success, message = delete_position(position_id)
        if success:
            return jsonify({"status": "success", "message": message})
        else:
            return jsonify({"status": "error", "message": message}), 400

    except Exception as e:
        logger.exception(f"Error deleting position: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────


def _position_to_dict(p):
    """Convert a StrategyPosition ORM object to a JSON-serializable dict."""
    return {
        "id": p.id,
        "symbol": p.symbol,
        "exchange": p.exchange,
        "product_type": p.product_type,
        "action": p.action,
        "quantity": p.quantity,
        "average_entry_price": float(p.average_entry_price or 0),
        "ltp": float(p.ltp or 0),
        "unrealized_pnl": round(float(p.unrealized_pnl or 0), 2),
        "realized_pnl": round(float(p.realized_pnl or 0), 2),
        "peak_price": float(p.peak_price or 0),
        "stoploss_price": float(p.stoploss_price) if p.stoploss_price else None,
        "target_price": float(p.target_price) if p.target_price else None,
        "trailstop_price": float(p.trailstop_price) if p.trailstop_price else None,
        "breakeven_activated": bool(p.breakeven_activated) if p.breakeven_activated else False,
        "position_state": p.position_state,
        "exit_reason": p.exit_reason,
        "exit_detail": p.exit_detail,
        "exit_price": float(p.exit_price) if p.exit_price else None,
        "risk_mode": p.risk_mode,
        "position_group_id": p.position_group_id,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "closed_at": p.closed_at.isoformat() if p.closed_at else None,
        "risk_status": (
            "monitoring" if p.position_state == "active"
            else "closed" if p.quantity == 0
            else p.position_state or "unknown"
        ),
    }
