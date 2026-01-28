# sandbox/catch_up_processor.py
"""
Catch-Up Processor - Handles missed scheduled jobs after app restart

Features:
- T+1 settlement catch-up for CNC positions
- Daily PnL reset catch-up if app was down during SESSION_EXPIRY_TIME
- Called after master contract download completes (fresh login)
"""

import os
from datetime import datetime, timedelta
from decimal import Decimal

import pytz

from utils.logging import get_logger

logger = get_logger(__name__)

# IST timezone
IST = pytz.timezone("Asia/Kolkata")


def get_last_session_boundary():
    """
    Get the most recent session boundary time (SESSION_EXPIRY_TIME)
    Returns datetime in IST
    """
    session_expiry_str = os.getenv("SESSION_EXPIRY_TIME", "03:00")
    reset_hour, reset_minute = map(int, session_expiry_str.split(":"))

    now = datetime.now(IST)
    today_boundary = now.replace(hour=reset_hour, minute=reset_minute, second=0, microsecond=0)

    if now >= today_boundary:
        return today_boundary
    else:
        return today_boundary - timedelta(days=1)


def catch_up_mis_squareoff():
    """
    Check and square-off any MIS positions from previous days
    MIS positions are intraday and should NEVER carry overnight
    Called after master contract download completes

    IMPORTANT: Since these positions are from previous days, their P&L should NOT
    be added to today_realized_pnl - only to accumulated/all-time realized_pnl
    """
    try:
        from database.sandbox_db import SandboxFunds, SandboxPositions, db_session
        from sandbox.fund_manager import FundManager

        # Get today's date at midnight IST
        today = datetime.now(IST).date()
        today_start = datetime.combine(today, datetime.min.time())
        today_start = IST.localize(today_start)

        # Find MIS positions from previous days (created before today)
        stale_mis_positions = (
            SandboxPositions.query.filter_by(product="MIS")
            .filter(SandboxPositions.quantity != 0, SandboxPositions.created_at < today_start)
            .all()
        )

        if not stale_mis_positions:
            logger.debug("Catch-up: No stale MIS positions found")
            return

        logger.info(
            f"Catch-up: Found {len(stale_mis_positions)} stale MIS positions from previous days"
        )

        # Process each stale MIS position manually (not through normal close flow)
        # This ensures we don't add to today_realized_pnl
        for position in stale_mis_positions:
            try:
                user_id = position.user_id
                symbol = position.symbol
                quantity = position.quantity
                avg_price = Decimal(str(position.average_price))
                margin_blocked = Decimal(str(position.margin_blocked or 0))

                # Get current LTP for settlement (use last known LTP or avg price)
                if position.ltp and Decimal(str(position.ltp)) > 0:
                    settlement_price = Decimal(str(position.ltp))
                else:
                    settlement_price = avg_price

                # Calculate realized P&L
                if quantity > 0:
                    realized_pnl = (settlement_price - avg_price) * Decimal(str(quantity))
                else:
                    realized_pnl = (avg_price - settlement_price) * Decimal(str(abs(quantity)))

                logger.info(
                    f"Catch-up settling stale MIS: {symbol} for {user_id}, "
                    f"qty={quantity}, pnl={realized_pnl}, margin={margin_blocked}"
                )

                # Update funds - add to realized_pnl but NOT today_realized_pnl
                funds = SandboxFunds.query.filter_by(user_id=user_id).first()
                if funds:
                    # Release margin back to available balance
                    funds.available_balance += margin_blocked + realized_pnl
                    funds.used_margin -= margin_blocked

                    # Add to all-time realized P&L only (NOT today_realized_pnl)
                    funds.realized_pnl = (funds.realized_pnl or Decimal("0.00")) + realized_pnl
                    funds.total_pnl = funds.realized_pnl + (funds.unrealized_pnl or Decimal("0.00"))

                    # Ensure used_margin doesn't go negative
                    if funds.used_margin < 0:
                        funds.used_margin = Decimal("0.00")

                # Update position to closed state
                position.quantity = 0
                position.margin_blocked = Decimal("0.00")
                position.pnl = realized_pnl
                position.accumulated_realized_pnl = (
                    position.accumulated_realized_pnl or Decimal("0.00")
                ) + realized_pnl
                # DO NOT update today_realized_pnl since this is from a previous day
                position.today_realized_pnl = Decimal("0.00")

                db_session.commit()
                logger.info(f"Catch-up: Settled stale MIS position {symbol} for {user_id}")

            except Exception as e:
                db_session.rollback()
                logger.exception(f"Error settling stale MIS position {position.symbol}: {e}")

        logger.info("Catch-up: Stale MIS positions settled")

    except Exception as e:
        logger.exception(f"Error in catch-up MIS square-off: {e}")


def catch_up_t1_settlement():
    """
    Check and process T+1 settlement if needed
    Called after master contract download completes
    """
    try:
        from database.sandbox_db import SandboxPositions
        from sandbox.holdings_manager import process_all_t1_settlements

        # Check if there are any CNC positions that need settlement
        ist = IST
        today = datetime.now(ist).date()
        settlement_cutoff = datetime.combine(today, datetime.min.time())

        pending_positions = (
            SandboxPositions.query.filter_by(product="CNC")
            .filter(SandboxPositions.created_at < settlement_cutoff)
            .count()
        )

        if pending_positions > 0:
            logger.info(f"Catch-up: Found {pending_positions} CNC positions pending T+1 settlement")
            process_all_t1_settlements()
            logger.info("Catch-up: T+1 settlement completed")
        else:
            logger.debug("Catch-up: No CNC positions pending T+1 settlement")

    except Exception as e:
        logger.exception(f"Error in catch-up T+1 settlement: {e}")


def catch_up_daily_pnl_reset():
    """
    Check and reset daily PnL if needed
    Called after master contract download completes
    """
    try:
        from database.sandbox_db import SandboxFunds, SandboxPositions, db_session

        last_session_boundary = get_last_session_boundary()

        # Check if there are positions with non-zero today_realized_pnl
        # that were last updated before the session boundary
        positions_needing_reset = SandboxPositions.query.filter(
            SandboxPositions.today_realized_pnl != None,
            SandboxPositions.today_realized_pnl != Decimal("0.00"),
            SandboxPositions.updated_at < last_session_boundary,
        ).count()

        funds_needing_reset = SandboxFunds.query.filter(
            SandboxFunds.today_realized_pnl != None,
            SandboxFunds.today_realized_pnl != Decimal("0.00"),
            SandboxFunds.updated_at < last_session_boundary,
        ).count()

        if positions_needing_reset > 0 or funds_needing_reset > 0:
            logger.info(
                f"Catch-up: Found {positions_needing_reset} positions, {funds_needing_reset} funds needing PnL reset"
            )

            # Reset all today_realized_pnl that are from before session boundary
            SandboxPositions.query.filter(
                SandboxPositions.updated_at < last_session_boundary
            ).update({"today_realized_pnl": Decimal("0.00")})

            SandboxFunds.query.filter(SandboxFunds.updated_at < last_session_boundary).update(
                {"today_realized_pnl": Decimal("0.00")}
            )

            db_session.commit()
            logger.info("Catch-up: Daily PnL reset completed")
        else:
            logger.debug("Catch-up: No stale today_realized_pnl found")

    except Exception as e:
        logger.exception(f"Error in catch-up daily PnL reset: {e}")


def catch_up_daily_pnl_snapshot():
    """
    Check and create daily P&L snapshots for missed days
    If the app was down at 23:59 IST, the snapshot wouldn't have been captured
    """
    try:
        from datetime import date, timedelta

        from database.sandbox_db import (
            SandboxDailyPnL,
            SandboxFunds,
            SandboxHoldings,
            SandboxPositions,
            db_session,
        )

        today = date.today()
        yesterday = today - timedelta(days=1)

        # Get all users with funds
        all_funds = SandboxFunds.query.all()

        for funds in all_funds:
            user_id = funds.user_id

            # Check if yesterday's snapshot exists
            existing_snapshot = SandboxDailyPnL.query.filter_by(
                user_id=user_id, date=yesterday
            ).first()

            if existing_snapshot:
                logger.debug(f"Catch-up: Yesterday's snapshot already exists for user {user_id}")
                continue

            # Calculate yesterday's P&L from available data
            # Since we don't have exact yesterday's values, use what we can reconstruct:
            # - All-time realized - today's realized = yesterday's (approximate)
            all_time_realized = Decimal(str(funds.realized_pnl or 0))
            today_realized = Decimal(str(funds.today_realized_pnl or 0))

            # Yesterday's realized = All-time - Today's
            # This is approximate but better than nothing
            yesterday_realized = all_time_realized - today_realized

            # For unrealized, we can't know yesterday's values accurately
            # So we'll set them to 0 (positions may have changed)
            positions_unrealized = Decimal("0.00")
            holdings_unrealized = Decimal("0.00")

            # Only create snapshot if there was some activity
            if yesterday_realized != 0 or all_time_realized != 0:
                snapshot = SandboxDailyPnL(
                    user_id=user_id,
                    date=yesterday,
                    realized_pnl=yesterday_realized,
                    positions_unrealized_pnl=positions_unrealized,
                    holdings_unrealized_pnl=holdings_unrealized,
                    total_mtm=yesterday_realized,  # Only realized since we don't know unrealized
                    available_balance=funds.available_balance,
                    used_margin=funds.used_margin,
                    portfolio_value=funds.available_balance + funds.used_margin,
                )
                db_session.add(snapshot)
                logger.info(
                    f"Catch-up: Created yesterday's P&L snapshot for user {user_id}, realized={yesterday_realized}"
                )

        db_session.commit()
        logger.info("Catch-up: Daily P&L snapshot backfill completed")

    except Exception as e:
        logger.exception(f"Error in catch-up daily P&L snapshot: {e}")


def run_catch_up_tasks():
    """
    Run all catch-up tasks after master contract download completes
    This ensures scheduled jobs that were missed (due to app being down) are processed

    Note: Runs regardless of sandbox mode - the sandbox database exists independently
    and positions need to be settled even if user is not in analyzer mode
    """
    try:
        logger.info("Running catch-up tasks after master contract download...")

        # Run MIS square-off catch-up (stale overnight positions)
        catch_up_mis_squareoff()

        # Run T+1 settlement catch-up
        catch_up_t1_settlement()

        # Run daily PnL reset catch-up
        catch_up_daily_pnl_reset()

        # Run daily PnL snapshot catch-up (for missed days)
        catch_up_daily_pnl_snapshot()

        logger.info("Catch-up tasks completed")

    except Exception as e:
        logger.exception(f"Error running catch-up tasks: {e}")
