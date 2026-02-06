"""
Strategy Position Tracker

Creates/updates StrategyPosition records on order fills.
Computes SL/target/trailing stop/breakeven prices.
Manages position groups for combined P&L mode.
"""

import uuid
from datetime import datetime

from utils.logging import get_logger

logger = get_logger(__name__)


def round_to_tick(price, tick_size):
    """Round price to nearest valid tick size.

    All computed prices (SL, target, trailing stop, breakeven) must be
    rounded to the instrument's tick size for valid exchange order placement.
    """
    if not tick_size or tick_size <= 0:
        return round(price, 2)
    return round(round(price / tick_size) * tick_size, 10)


def _resolve(override, default):
    """Return override if explicitly set (not None), else fall back to default.

    IMPORTANT: Uses 'is not None' instead of 'or' because 0.0 is a valid
    deliberate value (e.g., disable SL for this symbol). Python 'or' treats
    0.0 as falsy and would incorrectly fall through to the default.
    """
    return override if override is not None else default


def resolve_risk_params(strategy, symbol_mapping):
    """Resolve effective risk parameters: symbol override takes priority over strategy default."""
    return {
        "stoploss_type": _resolve(symbol_mapping.stoploss_type, strategy.default_stoploss_type),
        "stoploss_value": _resolve(symbol_mapping.stoploss_value, strategy.default_stoploss_value),
        "target_type": _resolve(symbol_mapping.target_type, strategy.default_target_type),
        "target_value": _resolve(symbol_mapping.target_value, strategy.default_target_value),
        "trailstop_type": _resolve(symbol_mapping.trailstop_type, strategy.default_trailstop_type),
        "trailstop_value": _resolve(
            symbol_mapping.trailstop_value, strategy.default_trailstop_value
        ),
        "breakeven_type": _resolve(symbol_mapping.breakeven_type, strategy.default_breakeven_type),
        "breakeven_threshold": _resolve(
            symbol_mapping.breakeven_threshold, strategy.default_breakeven_threshold
        ),
    }


def compute_stoploss_price(action, average_price, sl_type, sl_value, tick_size):
    """Compute stoploss price from entry price."""
    if not sl_type or sl_value is None:
        return None
    if action == "BUY":
        if sl_type == "percentage":
            price = average_price * (1 - sl_value / 100)
        else:  # points
            price = average_price - sl_value
    else:  # SELL (short)
        if sl_type == "percentage":
            price = average_price * (1 + sl_value / 100)
        else:
            price = average_price + sl_value
    return round_to_tick(price, tick_size)


def compute_target_price(action, average_price, tgt_type, tgt_value, tick_size):
    """Compute target price from entry price."""
    if not tgt_type or tgt_value is None:
        return None
    if action == "BUY":
        if tgt_type == "percentage":
            price = average_price * (1 + tgt_value / 100)
        else:
            price = average_price + tgt_value
    else:  # SELL
        if tgt_type == "percentage":
            price = average_price * (1 - tgt_value / 100)
        else:
            price = average_price - tgt_value
    return round_to_tick(price, tick_size)


def compute_trailstop_price(action, peak_price, tsl_type, tsl_value, tick_size):
    """Compute trailing stop price from peak/trough price."""
    if not tsl_type or tsl_value is None:
        return None
    if action == "BUY":
        if tsl_type == "percentage":
            price = peak_price * (1 - tsl_value / 100)
        else:
            price = peak_price - tsl_value
    else:  # SELL (short — trough price is stored in peak_price)
        if tsl_type == "percentage":
            price = peak_price * (1 + tsl_value / 100)
        else:
            price = peak_price + tsl_value
    return round_to_tick(price, tick_size)


def _get_tick_size(symbol, exchange):
    """Get tick_size for a symbol from the master contract database."""
    try:
        from database.symbol import SymToken, db_session as sym_db_session

        result = (
            sym_db_session.query(SymToken)
            .filter(SymToken.symbol == symbol, SymToken.exchange == exchange)
            .first()
        )
        if result and result.tick_size:
            return float(result.tick_size)
    except Exception as e:
        logger.debug(f"Could not fetch tick_size for {symbol}/{exchange}: {e}")
    return 0.05  # Default tick size


class StrategyPositionTracker:
    """Manages strategy positions based on order fills."""

    def on_entry_fill(self, order_item, average_price, filled_quantity):
        """Handle an entry order fill — create a new StrategyPosition.

        Args:
            order_item: Dict from poller queue with strategy_id, strategy_type, user_id, orderid, etc.
            average_price: Fill price from OrderStatus
            filled_quantity: Filled quantity from OrderStatus
        """
        strategy_id = order_item["strategy_id"]
        strategy_type = order_item["strategy_type"]
        user_id = order_item["user_id"]
        orderid = order_item["orderid"]

        try:
            from database.strategy_position_db import (
                StrategyOrder,
                create_strategy_position,
                create_strategy_trade,
                db_session,
            )

            # Get the order record for symbol/exchange/action details
            order = StrategyOrder.query.filter_by(orderid=orderid).first()
            if not order:
                logger.error(f"Order {orderid} not found in DB, cannot create position")
                return

            symbol = order.symbol
            exchange = order.exchange
            action = order.action
            product_type = order.product_type

            # Resolve risk parameters from strategy + symbol mapping
            risk_params = self._resolve_risk_for_order(strategy_id, strategy_type, symbol)
            tick_size = _get_tick_size(symbol, exchange)

            # Compute risk prices
            sl_price = compute_stoploss_price(
                action, average_price,
                risk_params.get("stoploss_type"), risk_params.get("stoploss_value"),
                tick_size,
            )
            tgt_price = compute_target_price(
                action, average_price,
                risk_params.get("target_type"), risk_params.get("target_value"),
                tick_size,
            )
            tsl_price = compute_trailstop_price(
                action, average_price,  # initial peak = entry price
                risk_params.get("trailstop_type"), risk_params.get("trailstop_value"),
                tick_size,
            )

            # Resolve position_group_id and risk_mode from symbol mapping
            group_id, risk_mode = self._resolve_group_info(strategy_id, strategy_type, symbol)

            # Create position
            position = create_strategy_position(
                strategy_id=strategy_id,
                strategy_type=strategy_type,
                user_id=user_id,
                symbol=symbol,
                exchange=exchange,
                product_type=product_type,
                action=action,
                quantity=filled_quantity,
                intended_quantity=order.quantity,
                average_entry_price=average_price,
                position_state="active",
                stoploss_type=risk_params.get("stoploss_type"),
                stoploss_value=risk_params.get("stoploss_value"),
                stoploss_price=sl_price,
                target_type=risk_params.get("target_type"),
                target_value=risk_params.get("target_value"),
                target_price=tgt_price,
                trailstop_type=risk_params.get("trailstop_type"),
                trailstop_value=risk_params.get("trailstop_value"),
                trailstop_price=tsl_price,
                breakeven_type=risk_params.get("breakeven_type"),
                breakeven_threshold=risk_params.get("breakeven_threshold"),
                tick_size=tick_size,
                position_group_id=group_id,
                risk_mode=risk_mode,
            )

            if not position:
                logger.error(f"Failed to create position for order {orderid}")
                return

            # Create entry trade record
            create_strategy_trade(
                strategy_id=strategy_id,
                strategy_type=strategy_type,
                user_id=user_id,
                orderid=orderid,
                symbol=symbol,
                exchange=exchange,
                action=action,
                quantity=filled_quantity,
                price=average_price,
                trade_type="entry",
            )

            # If combined mode, update position group
            if group_id:
                self._update_group_on_fill(group_id)

            # Emit SocketIO event
            self._emit_position_opened(position)

            logger.info(
                f"Position created: {symbol}/{exchange} {action} qty={filled_quantity} "
                f"@ {average_price} SL={sl_price} TGT={tgt_price} TSL={tsl_price}"
            )

        except Exception as e:
            logger.exception(f"Error handling entry fill for {orderid}: {e}")
        finally:
            try:
                from database.strategy_position_db import db_session

                db_session.remove()
            except Exception:
                pass

    def on_exit_fill(self, order_item, average_price, filled_quantity):
        """Handle an exit order fill — close the StrategyPosition.

        Args:
            order_item: Dict from poller queue
            average_price: Exit fill price
            filled_quantity: Exit filled quantity
        """
        orderid = order_item["orderid"]
        strategy_id = order_item["strategy_id"]
        strategy_type = order_item["strategy_type"]
        user_id = order_item["user_id"]
        exit_reason = order_item.get("exit_reason", "manual")

        try:
            from database.strategy_position_db import (
                StrategyOrder,
                StrategyPosition,
                create_strategy_trade,
                db_session,
                update_position,
            )

            # Get the order record
            order = StrategyOrder.query.filter_by(orderid=orderid).first()
            if not order:
                logger.error(f"Exit order {orderid} not found in DB")
                return

            symbol = order.symbol
            exchange = order.exchange
            action = order.action

            # Find the active position being closed
            # The exit action is the reverse: BUY exit → closes a SELL position, etc.
            entry_action = "SELL" if action == "BUY" else "BUY"
            position = (
                StrategyPosition.query.filter(
                    StrategyPosition.strategy_id == strategy_id,
                    StrategyPosition.strategy_type == strategy_type,
                    StrategyPosition.symbol == symbol,
                    StrategyPosition.exchange == exchange,
                    StrategyPosition.action == entry_action,
                    StrategyPosition.quantity > 0,
                )
                .first()
            )

            if not position:
                logger.warning(f"No active position found for exit order {orderid}")
                return

            # Calculate realized PnL
            if entry_action == "BUY":  # Long position being closed
                trade_pnl = (average_price - position.average_entry_price) * filled_quantity
            else:  # Short position being closed
                trade_pnl = (position.average_entry_price - average_price) * filled_quantity

            # Create exit trade
            create_strategy_trade(
                strategy_id=strategy_id,
                strategy_type=strategy_type,
                user_id=user_id,
                orderid=orderid,
                symbol=symbol,
                exchange=exchange,
                action=action,
                quantity=filled_quantity,
                price=average_price,
                trade_type="exit",
                exit_reason=exit_reason,
                pnl=trade_pnl,
            )

            # Update daily circuit breaker realized PnL
            try:
                from services.strategy_risk_engine import risk_engine
                risk_engine.update_daily_realized_pnl(strategy_id, strategy_type, trade_pnl)
            except Exception as e:
                logger.debug(f"Error updating circuit breaker realized PnL: {e}")

            # Update position
            now = datetime.utcnow()
            new_qty = max(0, position.quantity - filled_quantity)
            update_data = {
                "quantity": new_qty,
                "realized_pnl": position.realized_pnl + trade_pnl,
                "exit_price": average_price,
                "exit_reason": exit_reason,
            }
            if new_qty == 0:
                update_data["closed_at"] = now
                update_data["position_state"] = "active"  # Historical — no longer "exiting"

            update_position(position.id, **update_data)

            # If combined mode, update position group
            if position.position_group_id:
                self._update_group_on_close(position.position_group_id)

            # Emit SocketIO event
            self._emit_position_closed(position, trade_pnl, exit_reason)

            logger.info(
                f"Position closed: {symbol}/{exchange} {entry_action} qty={filled_quantity} "
                f"@ {average_price} PnL={trade_pnl:.2f} reason={exit_reason}"
            )

        except Exception as e:
            logger.exception(f"Error handling exit fill for {orderid}: {e}")
        finally:
            try:
                from database.strategy_position_db import db_session

                db_session.remove()
            except Exception:
                pass

    def _resolve_risk_for_order(self, strategy_id, strategy_type, symbol):
        """Resolve risk parameters for a strategy/symbol combination."""
        try:
            if strategy_type == "webhook":
                from database.strategy_db import Strategy, StrategySymbolMapping, db_session

                strategy = Strategy.query.get(strategy_id)
                if not strategy:
                    return {}
                mapping = StrategySymbolMapping.query.filter_by(
                    strategy_id=strategy_id, symbol=symbol
                ).first()
                if not mapping:
                    # Return strategy defaults only
                    return {
                        "stoploss_type": strategy.default_stoploss_type,
                        "stoploss_value": strategy.default_stoploss_value,
                        "target_type": strategy.default_target_type,
                        "target_value": strategy.default_target_value,
                        "trailstop_type": strategy.default_trailstop_type,
                        "trailstop_value": strategy.default_trailstop_value,
                        "breakeven_type": strategy.default_breakeven_type,
                        "breakeven_threshold": strategy.default_breakeven_threshold,
                    }
                return resolve_risk_params(strategy, mapping)

            elif strategy_type == "chartink":
                from database.chartink_db import (
                    ChartinkStrategy,
                    ChartinkSymbolMapping,
                    db_session,
                )

                strategy = ChartinkStrategy.query.get(strategy_id)
                if not strategy:
                    return {}
                mapping = ChartinkSymbolMapping.query.filter_by(
                    strategy_id=strategy_id
                ).first()
                if not mapping:
                    return {
                        "stoploss_type": strategy.default_stoploss_type,
                        "stoploss_value": strategy.default_stoploss_value,
                        "target_type": strategy.default_target_type,
                        "target_value": strategy.default_target_value,
                        "trailstop_type": strategy.default_trailstop_type,
                        "trailstop_value": strategy.default_trailstop_value,
                        "breakeven_type": strategy.default_breakeven_type,
                        "breakeven_threshold": strategy.default_breakeven_threshold,
                    }
                return resolve_risk_params(strategy, mapping)

        except Exception as e:
            logger.exception(f"Error resolving risk params: {e}")
        return {}

    def _resolve_group_info(self, strategy_id, strategy_type, symbol):
        """Resolve position_group_id and risk_mode for multi-leg positions."""
        try:
            if strategy_type == "webhook":
                from database.strategy_db import StrategySymbolMapping

                mapping = StrategySymbolMapping.query.filter_by(
                    strategy_id=strategy_id, symbol=symbol
                ).first()
            else:
                from database.chartink_db import ChartinkSymbolMapping

                mapping = ChartinkSymbolMapping.query.filter_by(
                    strategy_id=strategy_id
                ).first()

            if mapping and mapping.order_mode == "multi_leg" and mapping.risk_mode == "combined":
                # For combined mode, generate a group ID per webhook trigger
                # The actual group management happens during webhook processing
                return None, "combined"  # group_id set by webhook handler
            elif mapping and mapping.risk_mode:
                return None, mapping.risk_mode
        except Exception as e:
            logger.debug(f"Error resolving group info: {e}")
        return None, None

    def _update_group_on_fill(self, group_id):
        """Update position group when a leg fills.

        When all expected legs are filled, computes entry_value and initializes
        AFL-style trailing stop from the combined net premium at entry.
        """
        try:
            from database.strategy_position_db import StrategyPositionGroup, db_session

            grp = StrategyPositionGroup.query.get(group_id)
            if not grp:
                return

            grp.filled_legs = (grp.filled_legs or 0) + 1
            if grp.filled_legs >= grp.expected_legs:
                grp.group_status = "active"
                logger.info(f"Position group {group_id} all legs filled — now active")
                # Initialize combined risk (entry_value + TSL)
                self._initialize_group_risk(grp)
            db_session.commit()
        except Exception as e:
            logger.exception(f"Error updating group on fill: {e}")

    def _initialize_group_risk(self, group):
        """Compute entry_value and initial TSL for a newly-active position group.

        AFL-style TSL initialization (Phase 1):
        1. Calculate net premium: SELL legs = +price, BUY legs = -price
        2. entry_value = abs(Σ signed_price × quantity)
        3. Compute initial_stop from trail config:
           - Percentage: initial_stop = -entry_value × (trail% / 100)
           - Points:     initial_stop = -trail_value
           - Amount:     initial_stop = -trail_value
        4. Set current_stop = initial_stop, peak_pnl = 0
        """
        try:
            from database.strategy_position_db import get_positions_by_group

            legs = get_positions_by_group(group.id)
            if not legs:
                return

            # Compute entry_value: abs(Σ signed_entry_price × quantity)
            # SELL legs contribute positive premium (credit received)
            # BUY legs contribute negative premium (debit paid)
            net_premium = 0
            for leg in legs:
                if leg.quantity > 0:  # only open legs
                    signed_price = leg.average_entry_price
                    if leg.action == "BUY":
                        signed_price = -signed_price
                    # else SELL: positive (credit)
                    net_premium += signed_price * leg.quantity

            entry_value = abs(net_premium)
            group.entry_value = round(entry_value, 2)
            group.combined_peak_pnl = 0  # TSL starts from zero

            # Get trailing stop config from symbol mapping
            mapping = self._get_combined_risk_mapping(group)
            if not mapping:
                logger.info(
                    f"Group {group.id}: entry_value={entry_value:.2f}, no TSL config"
                )
                return

            tsl_type = mapping.get("combined_trailstop_type")
            tsl_value = mapping.get("combined_trailstop_value")

            if tsl_type and tsl_value is not None and entry_value > 0:
                # Compute initial stop based on configured type
                if tsl_type == "percentage":
                    initial_stop = -entry_value * (tsl_value / 100)
                else:  # points or amount — absolute value
                    initial_stop = -tsl_value

                group.initial_stop = round(initial_stop, 2)
                group.current_stop = round(initial_stop, 2)

                logger.info(
                    f"Group {group.id}: entry_value={entry_value:.2f}, "
                    f"initial_stop={initial_stop:.2f} ({tsl_type} {tsl_value})"
                )
            else:
                logger.info(
                    f"Group {group.id}: entry_value={entry_value:.2f}, TSL not configured"
                )

        except Exception as e:
            logger.exception(f"Error initializing group risk for {group.id}: {e}")

    def _get_combined_risk_mapping(self, group):
        """Get the combined risk params from the symbol mapping for a group."""
        try:
            strategy_type = group.strategy_type
            if strategy_type == "webhook":
                from database.strategy_db import StrategySymbolMapping
                mapping = StrategySymbolMapping.query.get(group.symbol_mapping_id)
            else:
                from database.chartink_db import ChartinkSymbolMapping
                mapping = ChartinkSymbolMapping.query.get(group.symbol_mapping_id)

            if mapping:
                return {
                    "combined_stoploss_type": mapping.combined_stoploss_type,
                    "combined_stoploss_value": mapping.combined_stoploss_value,
                    "combined_target_type": mapping.combined_target_type,
                    "combined_target_value": mapping.combined_target_value,
                    "combined_trailstop_type": mapping.combined_trailstop_type,
                    "combined_trailstop_value": mapping.combined_trailstop_value,
                }
        except Exception as e:
            logger.debug(f"Error fetching combined risk mapping for group {group.id}: {e}")
        return None

    def _update_group_on_close(self, group_id):
        """Update position group when a leg closes."""
        try:
            from database.strategy_position_db import (
                StrategyPositionGroup,
                db_session,
                get_positions_by_group,
            )

            legs = get_positions_by_group(group_id)
            all_closed = all(leg.quantity == 0 for leg in legs)
            if all_closed:
                grp = StrategyPositionGroup.query.get(group_id)
                if grp:
                    grp.group_status = "closed"
                    db_session.commit()
                    logger.info(f"Position group {group_id} all legs closed")
        except Exception as e:
            logger.exception(f"Error updating group on close: {e}")

    def _emit_position_opened(self, position):
        """Emit SocketIO event for new position."""
        try:
            from extensions import socketio

            socketio.emit("strategy_position_opened", {
                "strategy_id": position.strategy_id,
                "strategy_type": position.strategy_type,
                "position_id": position.id,
                "symbol": position.symbol,
                "exchange": position.exchange,
                "action": position.action,
                "quantity": position.quantity,
                "average_entry_price": position.average_entry_price,
                "stoploss_price": position.stoploss_price,
                "target_price": position.target_price,
                "trailstop_price": position.trailstop_price,
            })
        except Exception as e:
            logger.debug(f"Error emitting position_opened: {e}")

    def _emit_position_closed(self, position, pnl, exit_reason):
        """Emit SocketIO event for closed position."""
        try:
            from extensions import socketio

            socketio.emit("strategy_position_closed", {
                "strategy_id": position.strategy_id,
                "strategy_type": position.strategy_type,
                "position_id": position.id,
                "symbol": position.symbol,
                "exchange": position.exchange,
                "exit_reason": exit_reason,
                "exit_detail": position.exit_detail,
                "pnl": pnl,
                "exit_price": position.exit_price,
            })
        except Exception as e:
            logger.debug(f"Error emitting position_closed: {e}")


# Module-level singleton
position_tracker = StrategyPositionTracker()
