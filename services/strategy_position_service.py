"""
Strategy Position Tracker — tracks orders, positions, and trades per strategy.

Coordinates between webhook order placement, broker order status polling,
and local position state management.
"""

import math

from database.strategy_position_db import (
    close_position,
    create_strategy_order,
    create_strategy_position,
    create_strategy_trade,
    get_active_positions,
    get_position,
    update_order_status,
    update_position_state,
)
from utils.logging import get_logger

logger = get_logger(__name__)


def _resolve(override, default):
    """Return override if explicitly set (not None), else fall back to default.

    Uses 'is not None' instead of 'or' because 0.0 is a valid
    deliberate value (e.g., disable SL for this symbol).
    """
    return override if override is not None else default


def resolve_risk_params(strategy, symbol_mapping):
    """Resolve effective risk parameters (symbol override → strategy default).

    PRD §6: Resolution order: Symbol-level override → Strategy-level default → None (disabled).
    """
    return {
        "stoploss_type": _resolve(
            getattr(symbol_mapping, "stoploss_type", None),
            getattr(strategy, "default_stoploss_type", None),
        ),
        "stoploss_value": _resolve(
            getattr(symbol_mapping, "stoploss_value", None),
            getattr(strategy, "default_stoploss_value", None),
        ),
        "target_type": _resolve(
            getattr(symbol_mapping, "target_type", None),
            getattr(strategy, "default_target_type", None),
        ),
        "target_value": _resolve(
            getattr(symbol_mapping, "target_value", None),
            getattr(strategy, "default_target_value", None),
        ),
        "trailstop_type": _resolve(
            getattr(symbol_mapping, "trailstop_type", None),
            getattr(strategy, "default_trailstop_type", None),
        ),
        "trailstop_value": _resolve(
            getattr(symbol_mapping, "trailstop_value", None),
            getattr(strategy, "default_trailstop_value", None),
        ),
        "breakeven_type": _resolve(
            getattr(symbol_mapping, "breakeven_type", None),
            getattr(strategy, "default_breakeven_type", None),
        ),
        "breakeven_threshold": _resolve(
            getattr(symbol_mapping, "breakeven_threshold", None),
            getattr(strategy, "default_breakeven_threshold", None),
        ),
    }


def compute_risk_prices(action, entry_price, risk_params, tick_size=0.05):
    """Compute SL, target, and trailing stop prices from entry price and risk params.

    PRD §6 price formulas:
    - Long: SL = entry * (1 - sl_value/100) [pct] or entry - sl_value [pts]
    - Short: SL = entry * (1 + sl_value/100) [pct] or entry + sl_value [pts]
    """
    result = {}

    sl_type = risk_params.get("stoploss_type")
    sl_value = risk_params.get("stoploss_value")
    if sl_type and sl_value:
        if action == "BUY":
            if sl_type == "percentage":
                result["stoploss_price"] = entry_price * (1 - sl_value / 100)
            else:  # points
                result["stoploss_price"] = entry_price - sl_value
        else:  # SELL
            if sl_type == "percentage":
                result["stoploss_price"] = entry_price * (1 + sl_value / 100)
            else:
                result["stoploss_price"] = entry_price + sl_value

    tgt_type = risk_params.get("target_type")
    tgt_value = risk_params.get("target_value")
    if tgt_type and tgt_value:
        if action == "BUY":
            if tgt_type == "percentage":
                result["target_price"] = entry_price * (1 + tgt_value / 100)
            else:
                result["target_price"] = entry_price + tgt_value
        else:
            if tgt_type == "percentage":
                result["target_price"] = entry_price * (1 - tgt_value / 100)
            else:
                result["target_price"] = entry_price - tgt_value

    tsl_type = risk_params.get("trailstop_type")
    tsl_value = risk_params.get("trailstop_value")
    if tsl_type and tsl_value:
        if action == "BUY":
            if tsl_type == "percentage":
                result["trailstop_price"] = entry_price * (1 - tsl_value / 100)
            else:
                result["trailstop_price"] = entry_price - tsl_value
        else:
            if tsl_type == "percentage":
                result["trailstop_price"] = entry_price * (1 + tsl_value / 100)
            else:
                result["trailstop_price"] = entry_price + tsl_value

    # Round all prices to tick size
    if tick_size and tick_size > 0:
        for key in result:
            result[key] = round(result[key] / tick_size) * tick_size
            result[key] = round(result[key], 2)

    return result


def record_entry_order(
    strategy_id,
    strategy_type,
    user_id,
    orderid,
    symbol,
    exchange,
    action,
    quantity,
    product_type,
    price_type="MARKET",
    price=0,
):
    """Record an entry order placed via webhook.

    Creates a StrategyOrder record and a StrategyPosition in pending_entry state.
    Called from process_orders() after successful broker API response.
    """
    order = create_strategy_order(
        strategy_id=strategy_id,
        strategy_type=strategy_type,
        user_id=user_id,
        orderid=orderid,
        symbol=symbol,
        exchange=exchange,
        action=action,
        quantity=quantity,
        product_type=product_type,
        price_type=price_type,
        price=price,
        is_entry=True,
    )

    if not order:
        logger.error(f"Failed to create strategy order for {orderid}")
        return None, None

    # Create position in pending_entry state (actual entry price set on fill)
    position = create_strategy_position(
        strategy_id=strategy_id,
        strategy_type=strategy_type,
        user_id=user_id,
        symbol=symbol,
        exchange=exchange,
        product_type=product_type,
        action=action,
        quantity=quantity,
        intended_quantity=quantity,
        average_entry_price=0,  # will be updated on fill
        position_state="pending_entry",
    )

    if position:
        # Link order to position
        order.position_id = position.id
        from database.strategy_position_db import db_session

        db_session.commit()

    logger.info(
        f"Recorded entry order {orderid} for strategy {strategy_id} ({strategy_type}): "
        f"{action} {quantity} {symbol}@{exchange}"
    )

    return order, position


def confirm_fill(orderid, average_price, filled_quantity, strategy=None, symbol_mapping=None):
    """Confirm order fill — update order status, create trade, activate position.

    Called by OrderStatusPoller when broker confirms fill.
    """
    order = update_order_status(
        orderid=orderid,
        status="complete",
        average_price=average_price,
        filled_quantity=filled_quantity,
    )

    if not order:
        logger.warning(f"Order {orderid} not found for fill confirmation")
        return None

    if order.is_entry:
        # Update position to active with fill price
        position = get_position(order.position_id) if order.position_id else None
        if position:
            position.average_entry_price = average_price
            position.quantity = filled_quantity
            position.peak_price = average_price
            position.position_state = "active"

            # Resolve and apply risk parameters if strategy/mapping provided
            if strategy and symbol_mapping:
                risk_params = resolve_risk_params(strategy, symbol_mapping)
                tick_size = getattr(position, "tick_size", 0.05) or 0.05

                position.stoploss_type = risk_params["stoploss_type"]
                position.stoploss_value = risk_params["stoploss_value"]
                position.target_type = risk_params["target_type"]
                position.target_value = risk_params["target_value"]
                position.trailstop_type = risk_params["trailstop_type"]
                position.trailstop_value = risk_params["trailstop_value"]
                position.breakeven_type = risk_params["breakeven_type"]
                position.breakeven_threshold = risk_params["breakeven_threshold"]

                prices = compute_risk_prices(
                    position.action, average_price, risk_params, tick_size
                )
                position.stoploss_price = prices.get("stoploss_price")
                position.target_price = prices.get("target_price")
                position.trailstop_price = prices.get("trailstop_price")

            from database.strategy_position_db import db_session

            db_session.commit()

        # Create entry trade record
        create_strategy_trade(
            strategy_id=order.strategy_id,
            strategy_type=order.strategy_type,
            user_id=order.user_id,
            orderid=orderid,
            symbol=order.symbol,
            exchange=order.exchange,
            action=order.action,
            quantity=filled_quantity,
            price=average_price,
            trade_type="entry",
            position_id=order.position_id,
        )

        logger.info(
            f"Entry fill confirmed: {orderid} — {order.action} {filled_quantity} "
            f"{order.symbol}@{average_price}"
        )
    else:
        # Exit fill — close position
        position = get_position(order.position_id) if order.position_id else None
        if position:
            # Calculate realized PnL
            if position.action == "BUY":
                pnl = (average_price - position.average_entry_price) * filled_quantity
            else:
                pnl = (position.average_entry_price - average_price) * filled_quantity

            close_position(
                position_id=position.id,
                exit_reason=order.exit_reason or "manual",
                exit_price=average_price,
                realized_pnl=pnl,
            )

            # Create exit trade record
            create_strategy_trade(
                strategy_id=order.strategy_id,
                strategy_type=order.strategy_type,
                user_id=order.user_id,
                orderid=orderid,
                symbol=order.symbol,
                exchange=order.exchange,
                action=order.action,
                quantity=filled_quantity,
                price=average_price,
                trade_type="exit",
                exit_reason=order.exit_reason,
                pnl=pnl,
                position_id=order.position_id,
            )

            logger.info(
                f"Exit fill confirmed: {orderid} — {order.action} {filled_quantity} "
                f"{order.symbol}@{average_price}, PnL: {pnl:.2f}"
            )

    return order


def record_exit_order(
    position_id,
    orderid,
    exit_reason,
    exit_detail=None,
    quantity=None,
):
    """Record an exit order for a position.

    Sets position to 'exiting' state and creates a StrategyOrder record.
    """
    position = get_position(position_id)
    if not position or position.quantity <= 0:
        logger.warning(f"Cannot exit position {position_id}: not found or already closed")
        return None

    exit_qty = quantity or position.quantity
    exit_action = "SELL" if position.action == "BUY" else "BUY"

    order = create_strategy_order(
        strategy_id=position.strategy_id,
        strategy_type=position.strategy_type,
        user_id=position.user_id,
        orderid=orderid,
        symbol=position.symbol,
        exchange=position.exchange,
        action=exit_action,
        quantity=exit_qty,
        product_type=position.product_type,
        price_type="MARKET",
        is_entry=False,
        exit_reason=exit_reason,
        position_id=position_id,
    )

    if order:
        update_position_state(position_id, "exiting")
        logger.info(
            f"Exit order {orderid} recorded for position {position_id}: "
            f"{exit_action} {exit_qty} {position.symbol} (reason: {exit_reason})"
        )

    return order
