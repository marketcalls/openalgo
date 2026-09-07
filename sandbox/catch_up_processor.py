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
        from sandbox.session_boundary import last_session_expiry_utc

        session_expiry_str = os.getenv("SESSION_EXPIRY_TIME", "03:00")
        last_session_expiry = last_session_expiry_utc(session_expiry_str, datetime.now(IST))

        # Crypto / 24x7 brokers have no daily session boundary, so there is no
        # scheduled square-off to catch up. Mirroring squareoff_manager, skip any
        # exchange that has no configured square-off time.
        from utils.session import is_session_expiry_disabled

        if is_session_expiry_disabled():
            logger.debug(
                "Catch-up: skipping MIS square-off because session expiry is disabled (crypto/24x7)"
            )
            return

        from sandbox.squareoff_manager import SquareOffManager

        squareoff_manager = SquareOffManager()
        configured_exchanges = set(squareoff_manager.square_off_times)

        # Square off MIS positions that were not touched since the last session
        # boundary. Use updated_at (database UTC clock), not created_at: reopened
        # symbols reuse the same row and keep an old created_at (#1794).
        stale_mis_positions = (
            SandboxPositions.query.filter_by(product="MIS")
            .filter(
                SandboxPositions.quantity != 0,
                SandboxPositions.updated_at < last_session_expiry,
            )
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
            if position.exchange not in configured_exchanges:
                logger.debug(
                    f"Catch-up: skipping {position.symbol} on {position.exchange} "
                    "(no square-off time configured)"
                )
                continue

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

                # Calculate realized P&L (apply contract_value for crypto, e.g. 0.01 for ETHUSD.P)
                from database.token_db import get_symbol_info as _get_sym_info
                _sym_cv = _get_sym_info(symbol, position.exchange)
                _cv = Decimal(str(_sym_cv.contract_value)) if _sym_cv and _sym_cv.contract_value else Decimal("1.0")
                if quantity > 0:
                    realized_pnl = (settlement_price - avg_price) * Decimal(str(quantity)) * _cv
                else:
                    realized_pnl = (avg_price - settlement_price) * Decimal(str(abs(quantity))) * _cv

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
        from sandbox.session_boundary import as_db_utc

        # Check if there are any CNC positions that need settlement.
        # created_at is the database clock (UTC). Build IST midnight, then
        # convert, or the comparison is read as UTC and lands 5.5h late.
        today = datetime.now(IST).date()
        settlement_cutoff = as_db_utc(
            IST.localize(datetime.combine(today, datetime.min.time()))
        )

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
        from sandbox.session_boundary import last_session_expiry_utc

        session_expiry_str = os.getenv("SESSION_EXPIRY_TIME", "03:00")
        last_session_expiry = last_session_expiry_utc(session_expiry_str, datetime.now(IST))

        # Check if there are positions with non-zero today_realized_pnl
        # that were last updated before the session boundary
        positions_needing_reset = SandboxPositions.query.filter(
            SandboxPositions.today_realized_pnl.is_not(None),
            SandboxPositions.today_realized_pnl != Decimal("0.00"),
            SandboxPositions.updated_at < last_session_expiry,
        ).count()

        funds_needing_reset = SandboxFunds.query.filter(
            SandboxFunds.today_realized_pnl.is_not(None),
            SandboxFunds.today_realized_pnl != Decimal("0.00"),
            SandboxFunds.updated_at < last_session_expiry,
        ).count()

        if positions_needing_reset > 0 or funds_needing_reset > 0:
            logger.info(
                f"Catch-up: Found {positions_needing_reset} positions, {funds_needing_reset} funds needing PnL reset"
            )

            # Reset all today_realized_pnl that are from before session boundary
            SandboxPositions.query.filter(
                SandboxPositions.updated_at < last_session_expiry
            ).update({"today_realized_pnl": Decimal("0.00")})

            SandboxFunds.query.filter(SandboxFunds.updated_at < last_session_expiry).update(
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

        # Skip non-trading days (issue #876): without this, an app started on
        # Monday backfills a Sunday snapshot, and one started on Sunday
        # backfills Saturday -- manufacturing the same weekend duplication the
        # 23:59 cron gate now prevents.
        from database.market_calendar_db import is_market_holiday

        if is_market_holiday(yesterday):
            logger.debug(
                f"Catch-up: Skipping P&L snapshot backfill for {yesterday}: not a trading day"
            )
            return

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

        # Fire any GTT whose trigger was crossed while the app was down
        catch_up_gtts()

        logger.info("Catch-up tasks completed")

    except Exception as e:
        logger.exception(f"Error running catch-up tasks: {e}")


def catch_up_gtts():
    """Fire GTTs whose trigger was crossed while the app was down.

    Deliberately not gated by market hours: an off-hours restart is exactly the
    case this exists for, and the polling engine has no market-hours gate
    either, so adding one here would make GTTs behave differently from every
    other resting order.

    Stranded claims are reverted first. A leg left in ``triggering`` by the
    crash that took the app down is invisible to the pending scan below, so
    without this step the very restart meant to recover it would skip it.
    """
    try:
        from sandbox import gtt_manager

        reclaimed = gtt_manager.reclaim_stranded_legs()
        if reclaimed:
            logger.info(f"Catch-up reverted {reclaimed} stranded GTT leg(s)")

        rows = gtt_manager.get_active_legs()
        if not rows:
            logger.debug("No active GTT legs to catch up")
            return

        from sandbox.execution_engine import ExecutionEngine

        engine = ExecutionEngine()
        symbols = list({(gtt.symbol, gtt.exchange) for _leg, gtt in rows})
        quotes = engine._fetch_quotes_batch(symbols)

        fired = 0
        for leg, gtt in rows:
            quote = quotes.get((gtt.symbol, gtt.exchange))
            if not quote:
                continue
            ltp = quote.get("ltp")
            if not gtt_manager.leg_is_triggered_by(leg.trigger_direction, leg.trigger_price, ltp):
                continue
            if gtt_manager.try_claim_trigger(leg.id):
                if gtt_manager.fire_leg(leg.id, execution_price=ltp):
                    fired += 1

        if fired:
            logger.info(f"Catch-up fired {fired} GTT(s) crossed while the app was down")

    except Exception as e:
        logger.exception(f"Error in GTT catch-up: {e}")
