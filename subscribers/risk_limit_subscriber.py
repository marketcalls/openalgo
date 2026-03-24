# subscribers/risk_limit_subscriber.py
# EventBus callbacks for daily risk limits: trade counting and PnL evaluation.

from database.auth_db import verify_api_key
from services.risk_limit_service import evaluate_pnl_after_close, increment_trade_count
from utils.logging import get_logger

logger = get_logger(__name__)


def on_order_placed(event) -> None:
    """Increment trade count when a live order is placed."""
    try:
        if getattr(event, "mode", None) != "live":
            return
        api_key = getattr(event, "api_key", None)
        if not api_key:
            return
        user = verify_api_key(api_key)
        if user:
            count = increment_trade_count(user)
            logger.debug(f"Risk: trade count for {user} = {count}")
    except Exception as e:
        logger.exception(f"risk_limit_subscriber.on_order_placed error: {e}")


def on_position_closed(event) -> None:
    """Evaluate PnL after a position close to check profit/loss limits."""
    try:
        api_key = getattr(event, "api_key", None)
        if not api_key:
            return
        evaluate_pnl_after_close(api_key)
    except Exception as e:
        logger.exception(f"risk_limit_subscriber.on_position_closed error: {e}")
