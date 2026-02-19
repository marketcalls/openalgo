"""
Strategy Dashboard Blueprint — REST API endpoints for strategy position tracking,
order history, trade history, P&L, and risk configuration.

All endpoints require session authentication and enforce ownership checks.
"""

import json
import uuid

from flask import Blueprint, jsonify, request, session

from database.strategy_db import (
    Strategy,
    StrategySymbolMapping,
    bulk_add_symbol_mappings,
    create_strategy,
    get_strategy,
    get_symbol_mappings,
    db_session as strategy_db_session,
)
from database.chartink_db import get_strategy as get_chartink_strategy
from database.strategy_position_db import (
    delete_closed_position,
    get_active_groups,
    get_active_positions,
    get_alert_logs,
    get_all_positions,
    get_position,
    get_strategy_orders,
    get_strategy_trades,
)
from services.strategy_pnl_service import get_strategy_summary, get_daily_pnl_range
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

strategy_dashboard_bp = Blueprint("strategy_dashboard", __name__, url_prefix="/strategy/api")


# ─── Helpers ──────────────────────────────────────────────────────────────


def _get_user_id():
    """Get current user ID from session, or None."""
    return session.get("user")


def _get_strategy_with_auth(strategy_id, strategy_type, user_id):
    """Fetch strategy and verify ownership. Returns (strategy, error_response, status_code)."""
    if strategy_type == "chartink":
        strategy = get_chartink_strategy(strategy_id)
    else:
        strategy = get_strategy(strategy_id)

    if not strategy:
        return None, {"status": "error", "message": "Strategy not found"}, 404

    if strategy.user_id != user_id:
        return None, {"status": "error", "message": "Unauthorized"}, 403

    return strategy, None, None


def _serialize_order(order):
    """Serialize a StrategyOrder to dict."""
    return {
        "id": order.id,
        "strategy_id": order.strategy_id,
        "strategy_type": order.strategy_type,
        "orderid": order.orderid,
        "symbol": order.symbol,
        "exchange": order.exchange,
        "action": order.action,
        "quantity": order.quantity,
        "product_type": order.product_type,
        "price_type": order.price_type,
        "price": order.price,
        "order_status": order.order_status,
        "average_price": order.average_price,
        "filled_quantity": order.filled_quantity,
        "is_entry": order.is_entry,
        "exit_reason": order.exit_reason,
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }


def _serialize_position(position):
    """Serialize a StrategyPosition to dict."""
    return {
        "id": position.id,
        "strategy_id": position.strategy_id,
        "strategy_type": position.strategy_type,
        "symbol": position.symbol,
        "exchange": position.exchange,
        "product_type": position.product_type,
        "action": position.action,
        "quantity": position.quantity,
        "intended_quantity": position.intended_quantity,
        "average_entry_price": position.average_entry_price,
        "ltp": position.ltp,
        "unrealized_pnl": position.unrealized_pnl,
        "unrealized_pnl_pct": position.unrealized_pnl_pct,
        "peak_price": position.peak_price,
        "position_state": position.position_state,
        "stoploss_type": position.stoploss_type,
        "stoploss_value": position.stoploss_value,
        "stoploss_price": position.stoploss_price,
        "target_type": position.target_type,
        "target_value": position.target_value,
        "target_price": position.target_price,
        "trailstop_type": position.trailstop_type,
        "trailstop_value": position.trailstop_value,
        "trailstop_price": position.trailstop_price,
        "breakeven_type": position.breakeven_type,
        "breakeven_threshold": position.breakeven_threshold,
        "breakeven_activated": position.breakeven_activated,
        "position_group_id": position.position_group_id,
        "risk_mode": position.risk_mode,
        "realized_pnl": position.realized_pnl,
        "exit_reason": position.exit_reason,
        "exit_detail": position.exit_detail,
        "exit_price": position.exit_price,
        "closed_at": position.closed_at.isoformat() if position.closed_at else None,
        "created_at": position.created_at.isoformat() if position.created_at else None,
    }


def _serialize_trade(trade):
    """Serialize a StrategyTrade to dict."""
    return {
        "id": trade.id,
        "strategy_id": trade.strategy_id,
        "strategy_type": trade.strategy_type,
        "orderid": trade.orderid,
        "symbol": trade.symbol,
        "exchange": trade.exchange,
        "action": trade.action,
        "quantity": trade.quantity,
        "price": trade.price,
        "trade_type": trade.trade_type,
        "exit_reason": trade.exit_reason,
        "pnl": trade.pnl,
        "created_at": trade.created_at.isoformat() if trade.created_at else None,
    }


def _serialize_daily_pnl(record):
    """Serialize a StrategyDailyPnL to dict."""
    return {
        "date": record.date.isoformat() if record.date else None,
        "realized_pnl": record.realized_pnl,
        "unrealized_pnl": record.unrealized_pnl,
        "total_pnl": record.total_pnl,
        "total_trades": record.total_trades,
        "winning_trades": record.winning_trades,
        "losing_trades": record.losing_trades,
        "gross_profit": record.gross_profit,
        "gross_loss": record.gross_loss,
        "cumulative_pnl": record.cumulative_pnl,
        "max_drawdown": record.max_drawdown,
        "max_drawdown_pct": record.max_drawdown_pct,
    }


# ─── Dashboard Overview ──────────────────────────────────────────────────


@strategy_dashboard_bp.route("/overview")
@check_session_validity
def overview():
    """Dashboard overview — active strategies with P&L summaries."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    try:
        # Get all active positions for user
        positions = get_active_positions(user_id=user_id)

        # Group by strategy
        strategy_map = {}
        for pos in positions:
            key = (pos.strategy_id, pos.strategy_type)
            if key not in strategy_map:
                strategy_map[key] = {
                    "strategy_id": pos.strategy_id,
                    "strategy_type": pos.strategy_type,
                    "active_positions": 0,
                    "total_unrealized_pnl": 0,
                }
            strategy_map[key]["active_positions"] += 1
            strategy_map[key]["total_unrealized_pnl"] += pos.unrealized_pnl or 0

        return jsonify({
            "status": "success",
            "data": {
                "total_active_positions": len(positions),
                "total_unrealized_pnl": round(sum(p.unrealized_pnl or 0 for p in positions), 2),
                "strategies": list(strategy_map.values()),
            },
        })
    except Exception as e:
        logger.exception(f"Error in dashboard overview: {e}")
        return jsonify({"status": "error", "message": "Failed to load overview"}), 500


# ─── Strategy Positions ───────────────────────────────────────────────────


@strategy_dashboard_bp.route("/strategy/<int:strategy_id>/positions")
@check_session_validity
def strategy_positions(strategy_id):
    """Get positions for a strategy."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy_type = request.args.get("type", "webhook")
    include_closed = request.args.get("include_closed", "false").lower() == "true"
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    strategy, error, status = _get_strategy_with_auth(strategy_id, strategy_type, user_id)
    if error:
        return jsonify(error), status

    positions = get_all_positions(strategy_id, strategy_type, include_closed, limit, offset)

    return jsonify({
        "status": "success",
        "data": [_serialize_position(p) for p in positions],
    })


# ─── Strategy Orders ─────────────────────────────────────────────────────


@strategy_dashboard_bp.route("/strategy/<int:strategy_id>/orders")
@check_session_validity
def strategy_orders(strategy_id):
    """Get order history for a strategy."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy_type = request.args.get("type", "webhook")
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    strategy, error, status = _get_strategy_with_auth(strategy_id, strategy_type, user_id)
    if error:
        return jsonify(error), status

    orders = get_strategy_orders(strategy_id, strategy_type, limit, offset)

    return jsonify({
        "status": "success",
        "data": [_serialize_order(o) for o in orders],
    })


# ─── Strategy Trades ─────────────────────────────────────────────────────


@strategy_dashboard_bp.route("/strategy/<int:strategy_id>/trades")
@check_session_validity
def strategy_trades(strategy_id):
    """Get trade history for a strategy."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy_type = request.args.get("type", "webhook")
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    strategy, error, status = _get_strategy_with_auth(strategy_id, strategy_type, user_id)
    if error:
        return jsonify(error), status

    trades = get_strategy_trades(strategy_id, strategy_type, limit, offset)

    return jsonify({
        "status": "success",
        "data": [_serialize_trade(t) for t in trades],
    })


# ─── Strategy P&L ────────────────────────────────────────────────────────


@strategy_dashboard_bp.route("/strategy/<int:strategy_id>/pnl")
@check_session_validity
def strategy_pnl(strategy_id):
    """Get P&L summary and daily history for a strategy."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy_type = request.args.get("type", "webhook")

    strategy, error, status = _get_strategy_with_auth(strategy_id, strategy_type, user_id)
    if error:
        return jsonify(error), status

    summary = get_strategy_summary(strategy_id, strategy_type, user_id)

    # Get daily history
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    daily_records = get_daily_pnl_range(strategy_id, strategy_type, start_date, end_date)

    return jsonify({
        "status": "success",
        "data": {
            "summary": summary,
            "daily": [_serialize_daily_pnl(r) for r in daily_records],
        },
    })


# ─── Risk Configuration ──────────────────────────────────────────────────


@strategy_dashboard_bp.route("/strategy/<int:strategy_id>/risk-config")
@check_session_validity
def get_risk_config(strategy_id):
    """Get current risk configuration for a strategy."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy_type = request.args.get("type", "webhook")

    strategy, error, status = _get_strategy_with_auth(strategy_id, strategy_type, user_id)
    if error:
        return jsonify(error), status

    return jsonify({
        "status": "success",
        "data": {
            "default_stoploss_type": getattr(strategy, "default_stoploss_type", None),
            "default_stoploss_value": getattr(strategy, "default_stoploss_value", None),
            "default_target_type": getattr(strategy, "default_target_type", None),
            "default_target_value": getattr(strategy, "default_target_value", None),
            "default_trailstop_type": getattr(strategy, "default_trailstop_type", None),
            "default_trailstop_value": getattr(strategy, "default_trailstop_value", None),
            "default_breakeven_type": getattr(strategy, "default_breakeven_type", None),
            "default_breakeven_threshold": getattr(strategy, "default_breakeven_threshold", None),
            "risk_monitoring": getattr(strategy, "risk_monitoring", "active"),
            "auto_squareoff_time": getattr(strategy, "auto_squareoff_time", "15:15"),
        },
    })


@strategy_dashboard_bp.route("/strategy/<int:strategy_id>/risk-config", methods=["PUT"])
@check_session_validity
def update_risk_config(strategy_id):
    """Update risk configuration for a strategy."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy_type = request.json.get("type", "webhook") if request.json else "webhook"

    strategy, error, status = _get_strategy_with_auth(strategy_id, strategy_type, user_id)
    if error:
        return jsonify(error), status

    data = request.json or {}

    # Allowed fields for update
    risk_fields = [
        "default_stoploss_type", "default_stoploss_value",
        "default_target_type", "default_target_value",
        "default_trailstop_type", "default_trailstop_value",
        "default_breakeven_type", "default_breakeven_threshold",
        "auto_squareoff_time",
    ]

    try:
        for field in risk_fields:
            if field in data:
                setattr(strategy, field, data[field])

        if strategy_type == "chartink":
            from database.chartink_db import db_session as chartink_db_session
            chartink_db_session.commit()
        else:
            from database.strategy_db import db_session as strategy_db_session
            strategy_db_session.commit()

        return jsonify({"status": "success", "message": "Risk config updated"})
    except Exception as e:
        logger.exception(f"Error updating risk config: {e}")
        return jsonify({"status": "error", "message": "Failed to update"}), 500


# ─── Risk Monitoring ─────────────────────────────────────────────────────


@strategy_dashboard_bp.route("/strategy/<int:strategy_id>/risk/activate", methods=["POST"])
@check_session_validity
def activate_risk(strategy_id):
    """Activate risk monitoring for a strategy."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy_type = request.json.get("type", "webhook") if request.json else "webhook"

    strategy, error, status = _get_strategy_with_auth(strategy_id, strategy_type, user_id)
    if error:
        return jsonify(error), status

    try:
        strategy.risk_monitoring = "active"
        if strategy_type == "chartink":
            from database.chartink_db import db_session as chartink_db_session
            chartink_db_session.commit()
        else:
            from database.strategy_db import db_session as strategy_db_session
            strategy_db_session.commit()

        return jsonify({"status": "success", "message": "Risk monitoring activated"})
    except Exception as e:
        logger.exception(f"Error activating risk: {e}")
        return jsonify({"status": "error", "message": "Failed to activate"}), 500


@strategy_dashboard_bp.route("/strategy/<int:strategy_id>/risk/deactivate", methods=["POST"])
@check_session_validity
def deactivate_risk(strategy_id):
    """Pause risk monitoring for a strategy."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy_type = request.json.get("type", "webhook") if request.json else "webhook"

    strategy, error, status = _get_strategy_with_auth(strategy_id, strategy_type, user_id)
    if error:
        return jsonify(error), status

    try:
        strategy.risk_monitoring = "paused"
        if strategy_type == "chartink":
            from database.chartink_db import db_session as chartink_db_session
            chartink_db_session.commit()
        else:
            from database.strategy_db import db_session as strategy_db_session
            strategy_db_session.commit()

        return jsonify({"status": "success", "message": "Risk monitoring paused"})
    except Exception as e:
        logger.exception(f"Error deactivating risk: {e}")
        return jsonify({"status": "error", "message": "Failed to deactivate"}), 500


# ─── Position Management ─────────────────────────────────────────────────


@strategy_dashboard_bp.route("/strategy/<int:strategy_id>/position/<int:position_id>/close", methods=["POST"])
@check_session_validity
def close_position_route(strategy_id, position_id):
    """Close an individual position (place exit order)."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy_type = request.json.get("type", "webhook") if request.json else "webhook"

    strategy, error, status = _get_strategy_with_auth(strategy_id, strategy_type, user_id)
    if error:
        return jsonify(error), status

    position = get_position(position_id)
    if not position or position.strategy_id != strategy_id:
        return jsonify({"status": "error", "message": "Position not found"}), 404

    if position.quantity <= 0:
        return jsonify({"status": "error", "message": "Position already closed"}), 400

    # Place exit order via API
    try:
        from database.auth_db import get_auth_token_broker
        from services.websocket_service import get_user_api_key

        api_key = get_user_api_key(user_id)
        if not api_key:
            return jsonify({"status": "error", "message": "No API key found"}), 400

        exit_action = "SELL" if position.action == "BUY" else "BUY"

        import requests as http_requests

        base_url = f"http://127.0.0.1:{request.environ.get('SERVER_PORT', 5000)}"
        order_payload = {
            "apikey": api_key,
            "strategy": f"strategy_{strategy_id}",
            "symbol": position.symbol,
            "exchange": position.exchange,
            "action": exit_action,
            "quantity": str(position.quantity),
            "product": position.product_type,
            "pricetype": "MARKET",
            "price": "0",
        }

        response = http_requests.post(f"{base_url}/api/v1/placeorder", json=order_payload)
        if response.ok:
            result = response.json()
            orderid = result.get("orderid", "")

            if orderid:
                from services.strategy_position_service import record_exit_order

                record_exit_order(
                    position_id=position_id,
                    orderid=orderid,
                    exit_reason="manual",
                )

                from services.order_status_poller import enqueue_order

                enqueue_order(orderid, strategy_id, strategy_type, user_id, is_entry=False)

            return jsonify({"status": "success", "orderid": orderid})
        else:
            return jsonify({"status": "error", "message": "Failed to place exit order"}), 500

    except Exception as e:
        logger.exception(f"Error closing position: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@strategy_dashboard_bp.route("/strategy/<int:strategy_id>/positions/close-all", methods=["POST"])
@strategy_dashboard_bp.route("/strategy/<int:strategy_id>/close-all", methods=["POST"])
@check_session_validity
def close_all_positions(strategy_id):
    """Close all active positions for a strategy."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy_type = request.json.get("type", "webhook") if request.json else "webhook"

    strategy, error, status = _get_strategy_with_auth(strategy_id, strategy_type, user_id)
    if error:
        return jsonify(error), status

    positions = get_active_positions(strategy_id, strategy_type)
    if not positions:
        return jsonify({"status": "success", "message": "No active positions", "closed": 0})

    closed = 0
    errors = []
    for pos in positions:
        try:
            # Reuse close_position_route logic
            from database.auth_db import get_auth_token_broker
            from services.websocket_service import get_user_api_key

            api_key = get_user_api_key(user_id)
            if not api_key:
                errors.append(f"No API key for position {pos.id}")
                continue

            exit_action = "SELL" if pos.action == "BUY" else "BUY"

            import requests as http_requests

            base_url = f"http://127.0.0.1:{request.environ.get('SERVER_PORT', 5000)}"
            order_payload = {
                "apikey": api_key,
                "strategy": f"strategy_{strategy_id}",
                "symbol": pos.symbol,
                "exchange": pos.exchange,
                "action": exit_action,
                "quantity": str(pos.quantity),
                "product": pos.product_type,
                "pricetype": "MARKET",
                "price": "0",
            }

            response = http_requests.post(f"{base_url}/api/v1/placeorder", json=order_payload)
            if response.ok:
                result = response.json()
                orderid = result.get("orderid", "")
                if orderid:
                    from services.strategy_position_service import record_exit_order

                    record_exit_order(pos.id, orderid, "manual")

                    from services.order_status_poller import enqueue_order

                    enqueue_order(orderid, strategy_id, strategy_type, user_id, is_entry=False)

                closed += 1
            else:
                errors.append(f"Failed to close position {pos.id}")
        except Exception as e:
            errors.append(f"Error closing position {pos.id}: {str(e)}")

    result = {"status": "success", "closed": closed, "total": len(positions)}
    if errors:
        result["errors"] = errors

    return jsonify(result)


# ─── Position Delete ─────────────────────────────────────────────────────


@strategy_dashboard_bp.route("/strategy/<int:strategy_id>/position/<int:position_id>", methods=["DELETE"])
@check_session_validity
def delete_position(strategy_id, position_id):
    """Delete a closed position record."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy_type = request.args.get("type", "webhook")

    strategy, error, status = _get_strategy_with_auth(strategy_id, strategy_type, user_id)
    if error:
        return jsonify(error), status

    position = get_position(position_id)
    if not position or position.strategy_id != strategy_id:
        return jsonify({"status": "error", "message": "Position not found"}), 404

    if position.quantity > 0:
        return jsonify({"status": "error", "message": "Cannot delete active position"}), 400

    if delete_closed_position(position_id):
        return jsonify({"status": "success", "message": "Position deleted"})
    else:
        return jsonify({"status": "error", "message": "Failed to delete"}), 500


# ─── Risk Events (Alert Log) ─────────────────────────────────────────────


@strategy_dashboard_bp.route("/strategy/<int:strategy_id>/risk-events")
@check_session_validity
def risk_events(strategy_id):
    """Get risk events/alert log for a strategy."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy_type = request.args.get("type", "webhook")
    limit = min(int(request.args.get("limit", 20)), 100)
    offset = int(request.args.get("offset", 0))

    strategy, error, status = _get_strategy_with_auth(strategy_id, strategy_type, user_id)
    if error:
        return jsonify(error), status

    alerts = get_alert_logs(strategy_id, strategy_type, limit, offset)

    return jsonify({
        "status": "success",
        "data": [
            {
                "id": a.id,
                "alert_id": a.alert_id,
                "alert_type": a.alert_type,
                "symbol": a.symbol,
                "exchange": a.exchange,
                "trigger_reason": a.trigger_reason,
                "trigger_price": a.trigger_price,
                "ltp_at_trigger": a.ltp_at_trigger,
                "pnl": a.pnl,
                "message": a.message,
                "priority": a.priority,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in alerts
        ],
    })


# ─── Clone Strategy ─────────────────────────────────────────────────────


@strategy_dashboard_bp.route("/strategy/<int:strategy_id>/clone", methods=["POST"])
@check_session_validity
def clone_strategy(strategy_id):
    """Deep-copy a strategy and its symbol mappings."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy_type = request.json.get("type", "webhook") if request.json else "webhook"

    if strategy_type == "chartink":
        return jsonify({"status": "error", "message": "Chartink strategy cloning not supported"}), 400

    strategy, error, status = _get_strategy_with_auth(strategy_id, strategy_type, user_id)
    if error:
        return jsonify(error), status

    try:
        new_webhook_id = str(uuid.uuid4())
        new_strategy = create_strategy(
            name=f"{strategy.name} (Copy)",
            webhook_id=new_webhook_id,
            user_id=user_id,
            is_intraday=strategy.is_intraday,
            trading_mode=strategy.trading_mode,
            start_time=strategy.start_time,
            end_time=strategy.end_time,
            squareoff_time=strategy.squareoff_time,
            platform=strategy.platform,
        )

        if not new_strategy:
            return jsonify({"status": "error", "message": "Failed to clone strategy"}), 500

        # Copy risk defaults
        for field in [
            "default_stoploss_type", "default_stoploss_value",
            "default_target_type", "default_target_value",
            "default_trailstop_type", "default_trailstop_value",
            "default_breakeven_type", "default_breakeven_threshold",
            "risk_monitoring", "auto_squareoff_time", "daily_cb_behavior",
            "schedule_enabled", "schedule_start_time", "schedule_stop_time",
            "schedule_days", "schedule_auto_entry", "schedule_auto_exit",
        ]:
            setattr(new_strategy, field, getattr(strategy, field, None))
        strategy_db_session.commit()

        # Copy symbol mappings
        mappings = get_symbol_mappings(strategy_id)
        if mappings:
            mapping_dicts = []
            for m in mappings:
                d = {
                    "symbol": m.symbol,
                    "exchange": m.exchange,
                    "quantity": m.quantity,
                    "product_type": m.product_type,
                    "order_mode": m.order_mode,
                    "underlying": m.underlying,
                    "underlying_exchange": m.underlying_exchange,
                    "expiry_type": m.expiry_type,
                    "offset": m.offset,
                    "option_type": m.option_type,
                    "risk_mode": m.risk_mode,
                    "preset": m.preset,
                    "legs_config": m.legs_config,
                    "stoploss_type": m.stoploss_type,
                    "stoploss_value": m.stoploss_value,
                    "target_type": m.target_type,
                    "target_value": m.target_value,
                    "trailstop_type": m.trailstop_type,
                    "trailstop_value": m.trailstop_value,
                    "breakeven_type": m.breakeven_type,
                    "breakeven_threshold": m.breakeven_threshold,
                    "combined_stoploss_type": m.combined_stoploss_type,
                    "combined_stoploss_value": m.combined_stoploss_value,
                    "combined_target_type": m.combined_target_type,
                    "combined_target_value": m.combined_target_value,
                    "combined_trailstop_type": m.combined_trailstop_type,
                    "combined_trailstop_value": m.combined_trailstop_value,
                }
                mapping_dicts.append(d)
            bulk_add_symbol_mappings(new_strategy.id, mapping_dicts)

        return jsonify({
            "status": "success",
            "message": "Strategy cloned",
            "data": {"strategy_id": new_strategy.id, "webhook_id": new_webhook_id},
        })
    except Exception as e:
        logger.exception(f"Error cloning strategy: {e}")
        return jsonify({"status": "error", "message": "Failed to clone strategy"}), 500


# ─── Market Status ──────────────────────────────────────────────────────


@strategy_dashboard_bp.route("/market-status")
@check_session_validity
def market_status():
    """Return current market phase for the dashboard header."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    try:
        from database.market_calendar_db import (
            get_market_hours_status,
            is_market_holiday,
        )
        from datetime import datetime
        import pytz

        IST = pytz.timezone("Asia/Kolkata")
        now = datetime.now(IST)
        today = now.date()
        current_ms = (now.hour * 3600 + now.minute * 60 + now.second) * 1000

        status = get_market_hours_status()

        # Determine phase
        # 33300000ms = 09:15 IST, 55800000ms = 15:30 IST
        earliest_open_ms = status.get("earliest_open_ms") or 33300000
        latest_close_ms = status.get("latest_close_ms") or 55800000
        if today.weekday() >= 5:
            phase = "weekend"
        elif is_market_holiday(today):
            phase = "holiday"
        elif status["any_market_open"]:
            phase = "market_open"
        elif current_ms < earliest_open_ms:
            phase = "pre_market"
        elif current_ms > latest_close_ms:
            phase = "post_market"
        else:
            phase = "market_closed"

        return jsonify({
            "status": "success",
            "data": {
                "phase": phase,
                "current_time": now.strftime("%H:%M:%S IST"),
                "is_trading_day": status.get("is_trading_day", False),
                "exchanges": status.get("exchanges", {}),
            },
        })
    except Exception as e:
        logger.exception(f"Error getting market status: {e}")
        return jsonify({"status": "error", "message": "Failed to get market status"}), 500


# ─── Close Position Group ───────────────────────────────────────────────


@strategy_dashboard_bp.route("/strategy/<int:strategy_id>/group/<group_id>/close", methods=["POST"])
@check_session_validity
def close_position_group(strategy_id, group_id):
    """Close all active positions in a position group."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy_type = request.json.get("type", "webhook") if request.json else "webhook"

    strategy, error, status = _get_strategy_with_auth(strategy_id, strategy_type, user_id)
    if error:
        return jsonify(error), status

    # Get active positions belonging to this group
    all_positions = get_active_positions(strategy_id, strategy_type)
    group_positions = [p for p in all_positions if p.position_group_id == group_id]

    if not group_positions:
        return jsonify({"status": "success", "message": "No active positions in group", "closed": 0})

    closed = 0
    errors = []
    for pos in group_positions:
        try:
            from services.websocket_service import get_user_api_key

            api_key = get_user_api_key(user_id)
            if not api_key:
                errors.append(f"No API key for position {pos.id}")
                continue

            exit_action = "SELL" if pos.action == "BUY" else "BUY"

            import requests as http_requests

            base_url = f"http://127.0.0.1:{request.environ.get('SERVER_PORT', 5000)}"
            order_payload = {
                "apikey": api_key,
                "strategy": f"strategy_{strategy_id}",
                "symbol": pos.symbol,
                "exchange": pos.exchange,
                "action": exit_action,
                "quantity": str(pos.quantity),
                "product": pos.product_type,
                "pricetype": "MARKET",
                "price": "0",
            }

            response = http_requests.post(f"{base_url}/api/v1/placeorder", json=order_payload)
            if response.ok:
                result = response.json()
                orderid = result.get("orderid", "")
                if orderid:
                    from services.strategy_position_service import record_exit_order
                    from services.order_status_poller import enqueue_order

                    record_exit_order(pos.id, orderid, "group_close")
                    enqueue_order(orderid, strategy_id, strategy_type, user_id, is_entry=False)

                closed += 1
            else:
                errors.append(f"Failed to close position {pos.id}")
        except Exception as e:
            errors.append(f"Error closing position {pos.id}: {str(e)}")

    result = {"status": "success", "closed": closed, "total": len(group_positions)}
    if errors:
        result["errors"] = errors

    return jsonify(result)


# ─── Circuit Breaker ────────────────────────────────────────────────────


@strategy_dashboard_bp.route("/strategy/<int:strategy_id>/circuit-breaker", methods=["PUT"])
@check_session_validity
def update_circuit_breaker(strategy_id):
    """Update circuit breaker behavior for a strategy."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy_type = request.json.get("type", "webhook") if request.json else "webhook"

    strategy, error, status = _get_strategy_with_auth(strategy_id, strategy_type, user_id)
    if error:
        return jsonify(error), status

    data = request.json or {}
    behavior = data.get("daily_cb_behavior")

    valid_behaviors = ["alert_only", "stop_entries", "close_all_positions"]
    if behavior not in valid_behaviors:
        return jsonify({
            "status": "error",
            "message": f"Invalid behavior. Must be one of: {', '.join(valid_behaviors)}",
        }), 400

    try:
        strategy.daily_cb_behavior = behavior

        if strategy_type == "chartink":
            from database.chartink_db import db_session as chartink_db_session
            chartink_db_session.commit()
        else:
            strategy_db_session.commit()

        return jsonify({
            "status": "success",
            "message": f"Circuit breaker set to {behavior}",
            "data": {"daily_cb_behavior": behavior},
        })
    except Exception as e:
        logger.exception(f"Error updating circuit breaker: {e}")
        return jsonify({"status": "error", "message": "Failed to update"}), 500


# ─── Builder Save ──────────────────────────────────────────────────────


@strategy_dashboard_bp.route("/builder/save", methods=["POST"])
@check_session_validity
def builder_save():
    """Create a strategy from the F&O builder wizard."""
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    data = request.json or {}
    basics = data.get("basics", {})
    legs = data.get("legs", [])
    risk_config = data.get("riskConfig", {})
    preset = data.get("preset")

    name = basics.get("name", "").strip()
    if not name:
        return jsonify({"status": "error", "message": "Strategy name is required"}), 400
    if not legs:
        return jsonify({"status": "error", "message": "At least one leg is required"}), 400

    try:
        new_webhook_id = str(uuid.uuid4())
        strategy = create_strategy(
            name=name,
            webhook_id=new_webhook_id,
            user_id=user_id,
            is_intraday=basics.get("is_intraday", True),
            trading_mode=basics.get("trading_mode", "BOTH"),
            platform="builder",
        )

        if not strategy:
            return jsonify({"status": "error", "message": "Failed to create strategy"}), 500

        # Apply risk defaults from builder config
        for field in [
            "default_stoploss_type", "default_stoploss_value",
            "default_target_type", "default_target_value",
            "default_trailstop_type", "default_trailstop_value",
            "default_breakeven_type", "default_breakeven_threshold",
        ]:
            val = risk_config.get(field)
            if val is not None:
                setattr(strategy, field, val)
        strategy_db_session.commit()

        # Create a single symbol mapping with multi-leg configuration
        exchange = basics.get("exchange", "NFO")
        underlying = basics.get("underlying", "NIFTY")
        product_type = basics.get("product_type", "MIS")
        risk_mode = risk_config.get("risk_mode", "combined")

        # Resolve the correct quote exchange for underlying
        # Index symbols use NSE_INDEX/BSE_INDEX; stock symbols use NSE/BSE
        NSE_INDEX_SYMBOLS = {
            "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50",
        }
        BSE_INDEX_SYMBOLS = {"SENSEX", "BANKEX", "SENSEX50"}
        if underlying.upper() in NSE_INDEX_SYMBOLS:
            underlying_exchange = "NSE_INDEX"
        elif underlying.upper() in BSE_INDEX_SYMBOLS:
            underlying_exchange = "BSE_INDEX"
        elif exchange in ("BFO", "BSE"):
            underlying_exchange = "BSE"
        else:
            underlying_exchange = "NSE"

        mapping_data = {
            "symbol": underlying,
            "exchange": exchange,
            "quantity": legs[0].get("quantity_lots", 1) if legs else 1,
            "product_type": product_type,
            "order_mode": "multi_leg",
            "underlying": underlying,
            "underlying_exchange": underlying_exchange,
            "expiry_type": basics.get("expiry_type", "current_week"),
            "risk_mode": risk_mode,
            "preset": preset,
            "legs_config": json.dumps(legs),
        }

        # Add combined risk fields if combined mode
        if risk_mode == "combined":
            for field in [
                "combined_stoploss_type", "combined_stoploss_value",
                "combined_target_type", "combined_target_value",
                "combined_trailstop_type", "combined_trailstop_value",
            ]:
                val = risk_config.get(field)
                if val is not None:
                    mapping_data[field] = val

        bulk_add_symbol_mappings(strategy.id, [mapping_data])

        return jsonify({
            "status": "success",
            "message": "Strategy created",
            "data": {"strategy_id": strategy.id, "webhook_id": new_webhook_id},
        })
    except Exception as e:
        logger.exception(f"Error saving builder strategy: {e}")
        return jsonify({"status": "error", "message": "Failed to save strategy"}), 500
