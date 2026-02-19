"""
Strategy PnL Service — calculates unrealized/realized PnL and daily snapshots.
"""

from datetime import date

from database.strategy_position_db import (
    StrategyDailyPnL,
    StrategyPosition,
    StrategyTrade,
    db_session,
    get_active_positions,
    get_daily_pnl_range,
    upsert_daily_pnl,
)
from utils.logging import get_logger

logger = get_logger(__name__)


def calculate_unrealized_pnl(position, ltp):
    """Calculate unrealized P&L for a position given current LTP.

    Returns (pnl_amount, pnl_percentage).
    """
    if not position or position.quantity <= 0 or not position.average_entry_price:
        return 0.0, 0.0

    if position.action == "BUY":
        pnl = (ltp - position.average_entry_price) * position.quantity
    else:  # SELL (short)
        pnl = (position.average_entry_price - ltp) * position.quantity

    pnl_pct = (pnl / (position.average_entry_price * position.quantity)) * 100 if position.average_entry_price else 0.0

    return round(pnl, 2), round(pnl_pct, 2)


def calculate_realized_pnl(position, exit_price, exit_qty):
    """Calculate realized P&L for an exit trade."""
    if not position or not position.average_entry_price:
        return 0.0

    if position.action == "BUY":
        pnl = (exit_price - position.average_entry_price) * exit_qty
    else:
        pnl = (position.average_entry_price - exit_price) * exit_qty

    return round(pnl, 2)


def snapshot_daily_pnl(strategy_id, strategy_type, user_id, pnl_date=None):
    """Aggregate and upsert daily PnL snapshot for a strategy.

    Collects all trades for the given date and computes summary stats.
    """
    if pnl_date is None:
        pnl_date = date.today()

    try:
        # Get all trades for this strategy on this date
        trades = (
            db_session.query(StrategyTrade)
            .filter(
                StrategyTrade.strategy_id == strategy_id,
                StrategyTrade.strategy_type == strategy_type,
                StrategyTrade.trade_type == "exit",
            )
            .all()
        )

        # Filter to today's trades
        day_trades = [t for t in trades if t.created_at and t.created_at.date() == pnl_date]

        total_trades = len(day_trades)
        winning_trades = sum(1 for t in day_trades if t.pnl > 0)
        losing_trades = sum(1 for t in day_trades if t.pnl < 0)
        gross_profit = sum(t.pnl for t in day_trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in day_trades if t.pnl < 0))
        realized_pnl = sum(t.pnl for t in day_trades)
        max_trade_profit = max((t.pnl for t in day_trades if t.pnl > 0), default=0)
        max_trade_loss = abs(min((t.pnl for t in day_trades if t.pnl < 0), default=0))

        # Get unrealized P&L from active positions
        active_positions = get_active_positions(strategy_id, strategy_type)
        unrealized_pnl = sum(p.unrealized_pnl or 0 for p in active_positions)

        total_pnl = realized_pnl + unrealized_pnl

        # Calculate cumulative PnL (from all prior days + today)
        prior_records = get_daily_pnl_range(strategy_id, strategy_type, end_date=pnl_date)
        prior_cumulative = 0
        prior_peak = 0
        prior_max_dd = 0
        prior_max_dd_pct = 0

        # Get the last prior record (before today)
        prior = [r for r in prior_records if r.date < pnl_date]
        if prior:
            last = prior[-1]
            prior_cumulative = last.cumulative_pnl or 0
            prior_peak = last.peak_cumulative_pnl or 0
            prior_max_dd = last.max_drawdown or 0
            prior_max_dd_pct = last.max_drawdown_pct or 0

        cumulative_pnl = prior_cumulative + realized_pnl
        peak_cumulative_pnl = max(prior_peak, cumulative_pnl)
        drawdown = max(0, peak_cumulative_pnl - cumulative_pnl)
        drawdown_pct = (drawdown / peak_cumulative_pnl * 100) if peak_cumulative_pnl > 0 else 0
        max_drawdown = max(prior_max_dd, drawdown)
        max_drawdown_pct = max(prior_max_dd_pct, drawdown_pct)

        return upsert_daily_pnl(
            strategy_id=strategy_id,
            strategy_type=strategy_type,
            user_id=user_id,
            pnl_date=pnl_date,
            realized_pnl=round(realized_pnl, 2),
            unrealized_pnl=round(unrealized_pnl, 2),
            total_pnl=round(total_pnl, 2),
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            gross_profit=round(gross_profit, 2),
            gross_loss=round(gross_loss, 2),
            max_trade_profit=round(max_trade_profit, 2),
            max_trade_loss=round(max_trade_loss, 2),
            cumulative_pnl=round(cumulative_pnl, 2),
            peak_cumulative_pnl=round(peak_cumulative_pnl, 2),
            drawdown=round(drawdown, 2),
            drawdown_pct=round(drawdown_pct, 2),
            max_drawdown=round(max_drawdown, 2),
            max_drawdown_pct=round(max_drawdown_pct, 2),
        )

    except Exception as e:
        logger.exception(f"Error creating daily PnL snapshot: {e}")
        return None


def get_strategy_summary(strategy_id, strategy_type, user_id=None):
    """Get aggregate PnL summary for a strategy.

    Returns dict with today's P&L, total realized, active position count, etc.
    """
    try:
        active_positions = get_active_positions(strategy_id, strategy_type)
        total_unrealized = sum(p.unrealized_pnl or 0 for p in active_positions)

        # Get today's daily PnL
        today = date.today()
        daily_records = get_daily_pnl_range(strategy_id, strategy_type, start_date=today, end_date=today)
        today_record = daily_records[0] if daily_records else None

        # Get all-time stats from most recent record
        all_records = get_daily_pnl_range(strategy_id, strategy_type)
        last_record = all_records[-1] if all_records else None

        return {
            "active_positions": len(active_positions),
            "total_unrealized_pnl": round(total_unrealized, 2),
            "today_realized_pnl": round(today_record.realized_pnl, 2) if today_record else 0,
            "today_total_pnl": round(today_record.total_pnl, 2) if today_record else round(total_unrealized, 2),
            "today_trades": today_record.total_trades if today_record else 0,
            "cumulative_pnl": round(last_record.cumulative_pnl, 2) if last_record else 0,
            "max_drawdown": round(last_record.max_drawdown, 2) if last_record else 0,
            "max_drawdown_pct": round(last_record.max_drawdown_pct, 2) if last_record else 0,
        }
    except Exception as e:
        logger.exception(f"Error getting strategy summary: {e}")
        return {
            "active_positions": 0,
            "total_unrealized_pnl": 0,
            "today_realized_pnl": 0,
            "today_total_pnl": 0,
            "today_trades": 0,
            "cumulative_pnl": 0,
            "max_drawdown": 0,
            "max_drawdown_pct": 0,
        }
