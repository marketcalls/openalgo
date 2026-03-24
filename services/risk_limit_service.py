# services/risk_limit_service.py
# Runtime risk-limit checks: gate on every order, PnL evaluation after closes.

import threading
from collections import defaultdict
from datetime import date

from database.auth_db import get_auth_token_broker, verify_api_key
from database.risk_limits_db import get_risk_limits, reset_if_new_day, set_breached
from utils.logging import get_logger

logger = get_logger(__name__)

# In-memory trade counter: {user: {date: count}}
_trade_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
_trade_lock = threading.Lock()


def check_risk_limits(api_key: str) -> tuple[bool, str]:
    """
    Gate check called before every order placement.
    Returns (is_blocked, reason). If is_blocked is True, the order should be rejected.
    """
    try:
        user = verify_api_key(api_key)
        if not user:
            return False, ""  # Can't check limits without a user — let auth handle it

        row = get_risk_limits(user)
        if row is None or not row.enabled:
            return False, ""

        # Auto-reset on new trading day
        reset_if_new_day(user)

        # Re-read after potential reset
        if row.breached:
            row = get_risk_limits(user)
            if row and row.breached:
                return True, f"Daily risk limit breached: {row.breached_reason}"

        # Check trade count limit
        if row.daily_trade_limit is not None:
            count = get_trade_count(user)
            if count >= row.daily_trade_limit:
                reason = f"Daily trade limit reached ({count}/{row.daily_trade_limit})"
                set_breached(user, reason)
                _trigger_close_all(api_key, user)
                return True, reason

        return False, ""
    except Exception as e:
        logger.exception(f"Error checking risk limits: {e}")
        return False, ""  # Fail open — don't block orders on internal errors


def evaluate_pnl_after_close(api_key: str) -> None:
    """
    Called after a position is closed. Computes realized PnL for the day
    and triggers close-all if profit target or loss limit is breached.
    """
    try:
        user = verify_api_key(api_key)
        if not user:
            return

        row = get_risk_limits(user)
        if row is None or not row.enabled or row.breached:
            return

        pnl = _compute_realized_pnl(api_key)
        if pnl is None:
            return

        # Check profit target
        if row.daily_profit_target is not None and pnl >= row.daily_profit_target:
            reason = f"Daily profit target hit (PnL: {pnl:.2f}, Target: {row.daily_profit_target:.2f})"
            set_breached(user, reason)
            _trigger_close_all(api_key, user)
            return

        # Check loss limit (loss_limit stored as positive, pnl will be negative)
        if row.daily_loss_limit is not None and pnl <= -row.daily_loss_limit:
            reason = f"Daily loss limit hit (PnL: {pnl:.2f}, Limit: -{row.daily_loss_limit:.2f})"
            set_breached(user, reason)
            _trigger_close_all(api_key, user)
            return

    except Exception as e:
        logger.exception(f"Error evaluating PnL after close: {e}")


def increment_trade_count(user: str) -> int:
    """Increment and return the trade count for today."""
    today = str(date.today())
    with _trade_lock:
        _trade_counts[user][today] += 1
        return _trade_counts[user][today]


def get_trade_count(user: str) -> int:
    """Get trade count for today."""
    today = str(date.today())
    with _trade_lock:
        return _trade_counts[user].get(today, 0)


def _compute_realized_pnl(api_key: str) -> float | None:
    """Compute realized PnL from the broker's position book for today."""
    try:
        auth_token, broker_name = get_auth_token_broker(api_key)
        if auth_token is None:
            return None

        import importlib

        module = importlib.import_module(f"broker.{broker_name}.api.order_api")
        positions_fn = getattr(module, "get_positions", None)
        if positions_fn is None:
            return None

        positions = positions_fn(auth_token)
        if not positions or not isinstance(positions, list):
            return None

        total_pnl = 0.0
        for pos in positions:
            pnl = pos.get("pnl", 0)
            if pnl is not None:
                try:
                    total_pnl += float(pnl)
                except (ValueError, TypeError):
                    pass

        return total_pnl
    except Exception as e:
        logger.exception(f"Error computing realized PnL: {e}")
        return None


def _trigger_close_all(api_key: str, user: str) -> None:
    """Cancel all open orders and close all positions."""
    try:
        logger.warning(f"Risk limit triggered for {user} — closing all positions and cancelling orders")

        from services.cancel_all_order_service import cancel_all_orders
        from services.close_position_service import close_position

        cancel_all_orders(api_key=api_key)
        close_position(api_key=api_key)

        # Emit socketio event so the UI gets notified
        try:
            from extensions import socketio

            socketio.emit("risk_limit_breached", {"user": user}, namespace="/")
        except Exception:
            pass  # Non-critical

    except Exception as e:
        logger.exception(f"Error triggering close-all for {user}: {e}")
