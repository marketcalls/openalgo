"""
Strategy Exit Executor — Pluggable Exit Execution

V1 implements MarketExecution only. The Strategy design pattern allows
future execution types (mid order, order chasing, TWAP) to be added
without modifying the risk engine.

The risk engine calls:
    executor = get_execution_strategy(position.exit_execution or 'market')
    orderids = executor.execute(position, exit_reason, api_key)

Each returned orderid is saved as a StrategyOrder and queued to the poller.
"""

from utils.logging import get_logger

logger = get_logger(__name__)


class ExitExecutionStrategy:
    """Base class for exit execution strategies."""

    def execute(self, position, exit_reason, exit_detail, api_key):
        """Execute exit for a position.

        Args:
            position: StrategyPosition ORM object (must have quantity > 0)
            exit_reason: High-level reason (stoploss/target/trailstop/manual/squareoff)
            exit_detail: Granular detail (leg_sl/combined_sl/breakeven_sl/manual/etc.)
            api_key: Decrypted API key for the user

        Returns:
            List of broker orderids (may be multiple if auto-split)
        """
        raise NotImplementedError


class MarketExecution(ExitExecutionStrategy):
    """V1 default: immediate MARKET order.

    Auto-splits if quantity exceeds freeze_qty for the symbol.
    Uses placeorder (NOT placesmartorder) to exit only this strategy's position.
    """

    def execute(self, position, exit_reason, exit_detail, api_key):
        """Place MARKET exit order(s) for the position."""
        # Reverse action: BUY position → SELL exit, SELL position → BUY exit
        exit_action = "SELL" if position.action == "BUY" else "BUY"
        quantity = position.quantity
        symbol = position.symbol
        exchange = position.exchange
        product_type = position.product_type

        # Check freeze qty for auto-split
        freeze_qty = self._get_freeze_qty(symbol, exchange)
        if freeze_qty and quantity > freeze_qty:
            chunks = self._split_quantity(quantity, freeze_qty)
        else:
            chunks = [quantity]

        orderids = []
        for chunk_qty in chunks:
            orderid = self._place_single_order(
                api_key=api_key,
                symbol=symbol,
                exchange=exchange,
                action=exit_action,
                quantity=chunk_qty,
                product_type=product_type,
                strategy_name=f"strategy_{position.strategy_id}",
            )
            if orderid:
                orderids.append(orderid)
                # Save StrategyOrder record
                self._save_exit_order(
                    position=position,
                    orderid=orderid,
                    action=exit_action,
                    quantity=chunk_qty,
                    exit_reason=exit_reason,
                )
                # Queue to poller
                self._queue_to_poller(
                    orderid=orderid,
                    position=position,
                    exit_reason=exit_reason,
                )
            else:
                logger.error(
                    f"Failed to place exit order for {symbol}/{exchange} qty={chunk_qty}"
                )

        return orderids

    def _place_single_order(self, api_key, symbol, exchange, action, quantity, product_type, strategy_name):
        """Place a single market order via the placeorder service."""
        try:
            from services.place_order_service import place_order

            order_data = {
                "apikey": api_key,
                "symbol": symbol,
                "exchange": exchange,
                "action": action,
                "quantity": str(quantity),
                "pricetype": "MARKET",
                "product": product_type,
                "price": "0",
                "trigger_price": "0",
                "disclosed_quantity": "0",
                "strategy": strategy_name,
            }

            success, response, status_code = place_order(order_data, api_key=api_key)

            if success and response.get("status") == "success":
                orderid = response.get("orderid")
                logger.info(f"Exit order placed: {symbol} {action} qty={quantity} orderid={orderid}")
                return orderid
            else:
                logger.error(
                    f"Exit order failed: {symbol} {action} qty={quantity} — "
                    f"{response.get('message', 'unknown error')}"
                )
                return None

        except Exception as e:
            logger.exception(f"Error placing exit order: {e}")
            return None

    def _save_exit_order(self, position, orderid, action, quantity, exit_reason):
        """Save the exit order to StrategyOrder table."""
        try:
            from database.strategy_position_db import create_strategy_order

            create_strategy_order(
                strategy_id=position.strategy_id,
                strategy_type=position.strategy_type,
                user_id=position.user_id,
                orderid=orderid,
                symbol=position.symbol,
                exchange=position.exchange,
                action=action,
                quantity=quantity,
                product_type=position.product_type,
                price_type="MARKET",
                order_status="pending",
                is_entry=False,
                exit_reason=exit_reason,
            )
        except Exception as e:
            logger.exception(f"Error saving exit order {orderid}: {e}")

    def _queue_to_poller(self, orderid, position, exit_reason):
        """Queue exit order to OrderStatusPoller."""
        try:
            from services.strategy_order_poller import order_poller

            order_poller.queue_order(
                orderid=orderid,
                strategy_id=position.strategy_id,
                strategy_type=position.strategy_type,
                user_id=position.user_id,
                is_entry=False,
                exit_reason=exit_reason,
            )
        except Exception as e:
            logger.exception(f"Error queuing exit order {orderid} to poller: {e}")

    def _get_freeze_qty(self, symbol, exchange):
        """Get freeze quantity for a symbol."""
        try:
            from database.qty_freeze_db import get_freeze_qty_for_option

            return get_freeze_qty_for_option(symbol, exchange)
        except Exception:
            return None

    def _split_quantity(self, total_qty, freeze_qty):
        """Split quantity into chunks of freeze_qty."""
        chunks = []
        remaining = total_qty
        while remaining > 0:
            chunk = min(remaining, freeze_qty)
            chunks.append(chunk)
            remaining -= chunk
        return chunks


# Registry of execution strategies
_strategies = {
    "market": MarketExecution(),
}


def get_execution_strategy(strategy_name="market"):
    """Get an exit execution strategy by name.

    Args:
        strategy_name: Name of the execution strategy (default: 'market')

    Returns:
        ExitExecutionStrategy instance
    """
    return _strategies.get(strategy_name, _strategies["market"])
