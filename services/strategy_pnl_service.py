"""
Strategy PnL Service — PnL Calculation, Daily Snapshots & Risk Metrics

Provides:
1. Unrealized PnL calculation for open positions
2. Strategy-level risk metrics (win rate, profit factor, expectancy, drawdown, etc.)
3. Daily PnL snapshots (scheduled at 15:35 IST via APScheduler)
4. Exit breakdown aggregation by trigger type
5. Streak metrics (max consecutive wins/losses)
"""

import os
from collections import defaultdict
from datetime import datetime

import pytz
from sqlalchemy import func as sqlfunc

from utils.logging import get_logger

logger = get_logger(__name__)

IST = pytz.timezone("Asia/Kolkata")

PNL_SNAPSHOT_TIME = os.getenv("STRATEGY_PNL_SNAPSHOT_TIME", "15:35")


# ──────────────────────────────────────────────────────────────
# Today's Realized PnL (for circuit breaker startup recovery)
# ──────────────────────────────────────────────────────────────


def get_todays_realized_pnl_by_strategy():
    """Get today's realized PnL grouped by (strategy_id, strategy_type).

    Used by the risk engine on startup to recover daily circuit breaker state.
    Queries strategy_trade for today's exit trades and sums their PnL.

    Returns:
        dict of {(strategy_id, strategy_type): float}
    """
    try:
        from database.strategy_position_db import StrategyTrade, db_session

        today = datetime.now(IST).date()

        results = (
            db_session.query(
                StrategyTrade.strategy_id,
                StrategyTrade.strategy_type,
                sqlfunc.sum(StrategyTrade.pnl),
            )
            .filter(
                StrategyTrade.trade_type == "exit",
                sqlfunc.date(StrategyTrade.created_at) == today,
            )
            .group_by(StrategyTrade.strategy_id, StrategyTrade.strategy_type)
            .all()
        )

        return {
            (row[0], row[1]): round(row[2] or 0, 2)
            for row in results
        }

    except Exception as e:
        logger.exception(f"Error getting today's realized PnL: {e}")
        return {}
    finally:
        try:
            from database.strategy_position_db import db_session
            db_session.remove()
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────
# PnL Calculations
# ──────────────────────────────────────────────────────────────


def calculate_unrealized_pnl(position, ltp):
    """Calculate unrealized PnL for a single position.

    Args:
        position: StrategyPosition object or dict with action, average_entry_price, quantity
        ltp: Current last traded price

    Returns:
        float: Unrealized PnL amount
    """
    if isinstance(position, dict):
        action = position.get("action")
        entry = position.get("average_entry_price", 0)
        qty = position.get("quantity", 0)
    else:
        action = position.action
        entry = float(position.average_entry_price or 0)
        qty = position.quantity or 0

    if not entry or not qty or not ltp:
        return 0.0

    if action == "BUY":
        return (ltp - entry) * qty
    else:  # SELL (short)
        return (entry - ltp) * qty


def calculate_strategy_pnl_summary(strategy_id, strategy_type):
    """Calculate realized + unrealized PnL summary for a strategy.

    Returns:
        dict with realized_pnl, unrealized_pnl, total_pnl, position_count
    """
    try:
        from database.strategy_position_db import get_active_positions, get_strategy_trades

        # Realized PnL from closed trades
        trades = get_strategy_trades(strategy_id, strategy_type)
        realized_pnl = sum(t.pnl or 0 for t in trades if t.trade_type == "exit")

        # Unrealized PnL from open positions
        positions = get_active_positions(strategy_id=strategy_id)
        unrealized_pnl = sum(float(p.unrealized_pnl or 0) for p in positions)

        return {
            "realized_pnl": round(realized_pnl, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "total_pnl": round(realized_pnl + unrealized_pnl, 2),
            "position_count": len(positions),
        }
    except Exception as e:
        logger.exception(f"Error calculating PnL summary: {e}")
        return {
            "realized_pnl": 0,
            "unrealized_pnl": 0,
            "total_pnl": 0,
            "position_count": 0,
        }


# ──────────────────────────────────────────────────────────────
# Strategy Risk Metrics
# ──────────────────────────────────────────────────────────────


def calculate_strategy_metrics(strategy_id, strategy_type):
    """Calculate comprehensive risk metrics for a strategy.

    Computed from StrategyTrade (trade-level) and StrategyDailyPnL (daily snapshots).

    Returns:
        dict with all metrics from PRD Section 12.7.1
    """
    try:
        from database.strategy_position_db import get_daily_pnl, get_strategy_trades

        # Get all exit trades (entries don't have P&L)
        all_trades = get_strategy_trades(strategy_id, strategy_type)
        exit_trades = [t for t in all_trades if t.trade_type == "exit"]

        # Trade-level metrics
        total_trades = len(exit_trades)
        if total_trades == 0:
            return _empty_metrics()

        winning_trades = [t for t in exit_trades if (t.pnl or 0) > 0]
        losing_trades = [t for t in exit_trades if (t.pnl or 0) < 0]
        breakeven_trades = [t for t in exit_trades if (t.pnl or 0) == 0]

        gross_profit = sum(t.pnl for t in winning_trades)
        gross_loss = abs(sum(t.pnl for t in losing_trades))

        win_count = len(winning_trades)
        loss_count = len(losing_trades)
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0

        avg_win = (gross_profit / win_count) if win_count > 0 else 0
        avg_loss = (gross_loss / loss_count) if loss_count > 0 else 0

        risk_reward = (avg_win / avg_loss) if avg_loss > 0 else 0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0
        loss_rate = (loss_count / total_trades * 100) if total_trades > 0 else 0
        expectancy = (win_rate / 100 * avg_win) - (loss_rate / 100 * avg_loss)

        pnl_values = [t.pnl or 0 for t in exit_trades]
        best_trade = max(pnl_values) if pnl_values else 0
        worst_trade = min(pnl_values) if pnl_values else 0

        realized_pnl = sum(pnl_values)

        # Streak metrics
        max_wins, max_losses = _compute_streaks(exit_trades)

        # Daily PnL metrics
        daily_records = get_daily_pnl(strategy_id, strategy_type)
        daily_metrics = _compute_daily_metrics(daily_records)

        return {
            "total_trades": total_trades,
            "winning_trades": win_count,
            "losing_trades": loss_count,
            "breakeven_trades": len(breakeven_trades),
            "win_rate": round(win_rate, 2),
            "realized_pnl": round(realized_pnl, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "average_win": round(avg_win, 2),
            "average_loss": round(avg_loss, 2),
            "risk_reward_ratio": round(risk_reward, 2),
            "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else None,
            "expectancy": round(expectancy, 2),
            "best_trade": round(best_trade, 2),
            "worst_trade": round(worst_trade, 2),
            "max_consecutive_wins": max_wins,
            "max_consecutive_losses": max_losses,
            **daily_metrics,
        }

    except Exception as e:
        logger.exception(f"Error calculating strategy metrics: {e}")
        return _empty_metrics()


def _empty_metrics():
    """Return empty metrics dict when no trades exist."""
    return {
        "total_trades": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "breakeven_trades": 0,
        "win_rate": 0,
        "realized_pnl": 0,
        "gross_profit": 0,
        "gross_loss": 0,
        "average_win": 0,
        "average_loss": 0,
        "risk_reward_ratio": 0,
        "profit_factor": 0,
        "expectancy": 0,
        "best_trade": 0,
        "worst_trade": 0,
        "max_consecutive_wins": 0,
        "max_consecutive_losses": 0,
        "max_drawdown": 0,
        "max_drawdown_pct": 0,
        "current_drawdown": 0,
        "best_day": 0,
        "worst_day": 0,
        "average_daily_pnl": 0,
        "days_active": 0,
    }


def _compute_streaks(exit_trades):
    """Compute max consecutive wins and losses from ordered trades.

    Args:
        exit_trades: List of StrategyTrade objects ordered by time

    Returns:
        (max_consecutive_wins, max_consecutive_losses)
    """
    max_wins = 0
    max_losses = 0
    current_wins = 0
    current_losses = 0

    for trade in exit_trades:
        pnl = trade.pnl or 0
        if pnl > 0:
            current_wins += 1
            current_losses = 0
            max_wins = max(max_wins, current_wins)
        elif pnl < 0:
            current_losses += 1
            current_wins = 0
            max_losses = max(max_losses, current_losses)
        else:
            # Breakeven resets both streaks
            current_wins = 0
            current_losses = 0

    return max_wins, max_losses


def _compute_daily_metrics(daily_records):
    """Compute daily-level metrics from StrategyDailyPnL records.

    Args:
        daily_records: List of StrategyDailyPnL objects ordered by date

    Returns:
        dict with daily metrics
    """
    if not daily_records:
        return {
            "max_drawdown": 0,
            "max_drawdown_pct": 0,
            "current_drawdown": 0,
            "best_day": 0,
            "worst_day": 0,
            "average_daily_pnl": 0,
            "days_active": 0,
        }

    daily_pnls = [r.total_pnl or 0 for r in daily_records]
    days_active = len(daily_records)

    best_day = max(daily_pnls) if daily_pnls else 0
    worst_day = min(daily_pnls) if daily_pnls else 0
    average_daily = sum(daily_pnls) / days_active if days_active > 0 else 0

    # Max drawdown from cumulative PnL series
    max_drawdown = 0
    max_drawdown_pct = 0
    peak_cumulative = 0
    current_cumulative = 0

    for record in daily_records:
        current_cumulative = record.cumulative_pnl or 0
        if current_cumulative > peak_cumulative:
            peak_cumulative = current_cumulative

        dd = peak_cumulative - current_cumulative
        if dd > max_drawdown:
            max_drawdown = dd
            if peak_cumulative > 0:
                max_drawdown_pct = (dd / peak_cumulative) * 100

    current_drawdown = peak_cumulative - current_cumulative

    return {
        "max_drawdown": round(max_drawdown, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "current_drawdown": round(current_drawdown, 2),
        "best_day": round(best_day, 2),
        "worst_day": round(worst_day, 2),
        "average_daily_pnl": round(average_daily, 2),
        "days_active": days_active,
    }


# ──────────────────────────────────────────────────────────────
# Exit Breakdown
# ──────────────────────────────────────────────────────────────


def get_exit_breakdown(strategy_id, strategy_type):
    """Get exit breakdown aggregated by exit_reason.

    Returns list of dicts:
        [{"exit_reason": "stoploss", "count": 12, "total_pnl": -8400, "avg_pnl": -700}, ...]
    """
    try:
        from database.strategy_position_db import get_strategy_trades

        trades = get_strategy_trades(strategy_id, strategy_type)
        exit_trades = [t for t in trades if t.trade_type == "exit"]

        by_reason = defaultdict(lambda: {"count": 0, "total_pnl": 0})
        for trade in exit_trades:
            reason = trade.exit_reason or "unknown"
            by_reason[reason]["count"] += 1
            by_reason[reason]["total_pnl"] += trade.pnl or 0

        result = []
        for reason, data in sorted(by_reason.items()):
            count = data["count"]
            total = data["total_pnl"]
            result.append({
                "exit_reason": reason,
                "count": count,
                "total_pnl": round(total, 2),
                "avg_pnl": round(total / count, 2) if count > 0 else 0,
            })

        return result

    except Exception as e:
        logger.exception(f"Error getting exit breakdown: {e}")
        return []


# ──────────────────────────────────────────────────────────────
# Daily PnL Snapshot
# ──────────────────────────────────────────────────────────────


def snapshot_daily_pnl(strategy_id, strategy_type, user_id):
    """Take a daily PnL snapshot for a strategy.

    Called at 15:35 IST via APScheduler. Captures the end-of-day state:
    realized PnL, unrealized PnL, trade counts, drawdown tracking.
    """
    try:
        from database.strategy_position_db import (
            get_active_positions,
            get_daily_pnl,
            get_strategy_trades,
            upsert_daily_pnl,
        )

        today = datetime.now(IST).date()

        # Get all exit trades
        all_trades = get_strategy_trades(strategy_id, strategy_type)
        exit_trades = [t for t in all_trades if t.trade_type == "exit"]

        # Today's trades only
        todays_exits = [
            t for t in exit_trades
            if t.created_at and t.created_at.date() == today
        ]

        # Today's metrics
        total_trades_today = len(todays_exits)
        winning_today = [t for t in todays_exits if (t.pnl or 0) > 0]
        losing_today = [t for t in todays_exits if (t.pnl or 0) < 0]

        realized_pnl = sum(t.pnl or 0 for t in todays_exits)
        gross_profit = sum(t.pnl for t in winning_today)
        gross_loss = abs(sum(t.pnl for t in losing_today))
        max_trade_profit = max((t.pnl or 0 for t in todays_exits), default=0)
        max_trade_loss = min((t.pnl or 0 for t in todays_exits), default=0)

        # Unrealized PnL from open positions
        open_positions = get_active_positions(strategy_id=strategy_id)
        unrealized_pnl = sum(float(p.unrealized_pnl or 0) for p in open_positions)

        total_pnl = realized_pnl + unrealized_pnl

        # Cumulative PnL tracking (sum of all historical daily total_pnl + today)
        historical = get_daily_pnl(strategy_id, strategy_type)
        prev_cumulative = 0
        prev_peak = 0
        prev_max_dd = 0
        prev_max_dd_pct = 0

        if historical:
            # Get the most recent snapshot that's not today
            for rec in reversed(historical):
                if hasattr(rec, 'date') and rec.date:
                    rec_date = rec.date.date() if hasattr(rec.date, 'date') else rec.date
                    if rec_date != today:
                        prev_cumulative = rec.cumulative_pnl or 0
                        prev_peak = rec.peak_cumulative_pnl or 0
                        prev_max_dd = rec.max_drawdown or 0
                        prev_max_dd_pct = rec.max_drawdown_pct or 0
                        break

        cumulative_pnl = prev_cumulative + total_pnl
        peak_cumulative = max(prev_peak, cumulative_pnl)

        # Drawdown calculation
        drawdown = peak_cumulative - cumulative_pnl
        drawdown_pct = (drawdown / peak_cumulative * 100) if peak_cumulative > 0 else 0

        max_drawdown = max(prev_max_dd, drawdown)
        max_drawdown_pct = max(prev_max_dd_pct, drawdown_pct)

        upsert_daily_pnl(
            strategy_id=strategy_id,
            strategy_type=strategy_type,
            user_id=user_id,
            date=today,
            realized_pnl=round(realized_pnl, 2),
            unrealized_pnl=round(unrealized_pnl, 2),
            total_pnl=round(total_pnl, 2),
            total_trades=total_trades_today,
            winning_trades=len(winning_today),
            losing_trades=len(losing_today),
            gross_profit=round(gross_profit, 2),
            gross_loss=round(gross_loss, 2),
            max_trade_profit=round(max_trade_profit, 2),
            max_trade_loss=round(max_trade_loss, 2),
            cumulative_pnl=round(cumulative_pnl, 2),
            peak_cumulative_pnl=round(peak_cumulative, 2),
            drawdown=round(drawdown, 2),
            drawdown_pct=round(drawdown_pct, 2),
            max_drawdown=round(max_drawdown, 2),
            max_drawdown_pct=round(max_drawdown_pct, 2),
        )

        logger.info(
            f"Daily PnL snapshot: strategy={strategy_id}/{strategy_type} "
            f"realized={realized_pnl:.2f} unrealized={unrealized_pnl:.2f} "
            f"total={total_pnl:.2f} trades={total_trades_today}"
        )

    except Exception as e:
        logger.exception(f"Error taking daily PnL snapshot: {e}")
    finally:
        try:
            from database.strategy_position_db import db_session
            db_session.remove()
        except Exception:
            pass


def snapshot_all_strategies():
    """Take daily PnL snapshots for ALL active strategies.

    Called by APScheduler at STRATEGY_PNL_SNAPSHOT_TIME (default 15:35 IST).
    """
    try:
        from database.strategy_db import Strategy, db_session as strat_db_session
        from database.chartink_db import ChartinkStrategy, db_session as chartink_db_session

        # Webhook strategies
        try:
            strategies = strat_db_session.query(Strategy).filter_by(is_active=True).all()
            for s in strategies:
                snapshot_daily_pnl(s.id, "webhook", s.user_id)
        except Exception as e:
            logger.exception(f"Error snapshotting webhook strategies: {e}")

        # Chartink strategies
        try:
            chartink_strategies = chartink_db_session.query(ChartinkStrategy).filter_by(is_active=True).all()
            for s in chartink_strategies:
                snapshot_daily_pnl(s.id, "chartink", s.user_id)
        except Exception as e:
            logger.exception(f"Error snapshotting chartink strategies: {e}")

        logger.info("Daily PnL snapshot completed for all strategies")

    except Exception as e:
        logger.exception(f"Error in snapshot_all_strategies: {e}")


def get_equity_curve_data(strategy_id, strategy_type):
    """Get equity curve data for charting (daily cumulative PnL over time).

    Returns:
        list of dicts: [{"date": "2026-01-15", "cumulative_pnl": 5400.50}, ...]
    """
    try:
        from database.strategy_position_db import get_daily_pnl

        records = get_daily_pnl(strategy_id, strategy_type)
        return [
            {
                "date": r.date.strftime("%Y-%m-%d") if hasattr(r.date, "strftime") else str(r.date),
                "cumulative_pnl": round(r.cumulative_pnl or 0, 2),
                "total_pnl": round(r.total_pnl or 0, 2),
                "drawdown": round(r.drawdown or 0, 2),
                "drawdown_pct": round(r.drawdown_pct or 0, 2),
            }
            for r in records
        ]
    except Exception as e:
        logger.exception(f"Error getting equity curve data: {e}")
        return []
