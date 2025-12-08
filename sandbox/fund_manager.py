# sandbox/fund_manager.py
"""
Fund Manager - Handles simulated capital and margin calculations

Features:
- ₹10,000,000 (1 Crore) starting capital (configurable)
- Automatic reset via APScheduler on configured day/time (default: Sunday 00:00 IST)
- Leverage-based margin calculations
- Real-time available balance tracking

Auto-Reset:
- Runs as APScheduler background job (see squareoff_thread.py)
- Configurable day (Monday-Sunday) and time (HH:MM format)
- Resets all user funds to starting capital even if app was stopped during reset time
- Schedule automatically reloads when reset_day or reset_time config is changed
"""

import os
import sys
import threading
from decimal import Decimal
from datetime import datetime, timedelta
import pytz

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.sandbox_db import (
    SandboxFunds, SandboxPositions, SandboxHoldings,
    db_session, get_config
)
from database.token_db import get_symbol_info
from utils.logging import get_logger

logger = get_logger(__name__)


def is_option(symbol, exchange):
    """Check if symbol is an option based on exchange and symbol suffix"""
    if exchange in ['NFO', 'BFO', 'MCX', 'CDS', 'BCD', 'NCDEX']:
        return symbol.endswith('CE') or symbol.endswith('PE')
    return False


def is_future(symbol, exchange):
    """Check if symbol is a future based on exchange and symbol suffix"""
    if exchange in ['NFO', 'BFO', 'MCX', 'CDS', 'BCD', 'NCDEX']:
        return symbol.endswith('FUT')
    return False


class FundManager:
    """Manages virtual funds for sandbox mode"""

    # Class-level lock for thread safety across all fund operations
    # This prevents race conditions when multiple threads modify funds simultaneously
    _lock = threading.Lock()

    def __init__(self, user_id):
        self.user_id = user_id
        self.starting_capital = Decimal(get_config('starting_capital', '10000000.00'))

    def initialize_funds(self):
        """Initialize funds for a new user"""
        with self._lock:
            try:
                # Check if user already has funds
                funds = SandboxFunds.query.filter_by(user_id=self.user_id).first()

                if not funds:
                    # Create new fund account
                    funds = SandboxFunds(
                        user_id=self.user_id,
                        total_capital=self.starting_capital,
                        available_balance=self.starting_capital,
                        used_margin=Decimal('0.00'),
                        realized_pnl=Decimal('0.00'),
                        unrealized_pnl=Decimal('0.00'),
                        total_pnl=Decimal('0.00'),
                        last_reset_date=datetime.now(pytz.timezone('Asia/Kolkata')),
                        reset_count=0
                    )
                    db_session.add(funds)
                    db_session.commit()
                    logger.info(f"Initialized funds for user {self.user_id} with ₹{self.starting_capital}")
                    return True, "Funds initialized successfully"
                else:
                    logger.debug(f"User {self.user_id} already has funds initialized")
                    return True, "Funds already initialized"

            except Exception as e:
                db_session.rollback()
                logger.error(f"Error initializing funds for user {self.user_id}: {e}")
                return False, f"Error initializing funds: {str(e)}"

    def get_funds(self):
        """Get current fund status for user"""
        try:
            funds = SandboxFunds.query.filter_by(user_id=self.user_id).first()

            if not funds:
                # Initialize funds if not exists
                success, message = self.initialize_funds()
                if not success:
                    return None

                funds = SandboxFunds.query.filter_by(user_id=self.user_id).first()

            # Check if reset is needed
            self._check_and_reset_funds(funds)

            # Return fund details
            return {
                'availablecash': float(funds.available_balance),
                'collateral': 0.00,  # No collateral in sandbox
                'm2munrealized': float(funds.unrealized_pnl),
                'm2mrealized': float(funds.realized_pnl),
                'utiliseddebits': float(funds.used_margin),
                'grossexposure': float(funds.used_margin),
                'totalpnl': float(funds.total_pnl),
                'last_reset': funds.last_reset_date.strftime('%Y-%m-%d %H:%M:%S'),
                'reset_count': funds.reset_count
            }

        except Exception as e:
            logger.error(f"Error getting funds for user {self.user_id}: {e}")
            return None

    def _check_and_reset_funds(self, funds):
        """Check if funds need to be reset (every Sunday at midnight IST)"""
        try:
            # Check if auto-reset is disabled
            reset_day = get_config('reset_day', 'Sunday')
            if reset_day.lower() == 'never':
                return  # Skip reset check entirely

            ist = pytz.timezone('Asia/Kolkata')
            now = datetime.now(ist)
            last_reset = funds.last_reset_date

            # Make last_reset timezone aware if it isn't
            if last_reset.tzinfo is None:
                last_reset = ist.localize(last_reset)

            # Check if it's the configured reset day and we haven't reset today
            reset_time_str = get_config('reset_time', '00:00')

            if now.strftime('%A') == reset_day:
                reset_hour, reset_minute = map(int, reset_time_str.split(':'))
                reset_time_today = now.replace(
                    hour=reset_hour,
                    minute=reset_minute,
                    second=0,
                    microsecond=0
                )

                # If current time is past reset time and last reset was before today's reset time
                if now >= reset_time_today and last_reset < reset_time_today:
                    self._reset_funds(funds)

        except Exception as e:
            logger.error(f"Error checking fund reset for user {self.user_id}: {e}")

    def _reset_funds(self, funds):
        """Reset funds to starting capital"""
        with self._lock:
            try:
                logger.info(f"Resetting funds for user {self.user_id}")

                # Reset all fund values
                funds.total_capital = self.starting_capital
                funds.available_balance = self.starting_capital
                funds.used_margin = Decimal('0.00')
                funds.realized_pnl = Decimal('0.00')
                funds.unrealized_pnl = Decimal('0.00')
                funds.total_pnl = Decimal('0.00')
                funds.last_reset_date = datetime.now(pytz.timezone('Asia/Kolkata'))
                funds.reset_count += 1

                db_session.commit()

                # Clear all positions and holdings
                SandboxPositions.query.filter_by(user_id=self.user_id).delete()
                SandboxHoldings.query.filter_by(user_id=self.user_id).delete()
                db_session.commit()

                logger.info(f"Funds reset successfully for user {self.user_id} (Reset #{funds.reset_count})")

            except Exception as e:
                db_session.rollback()
                logger.error(f"Error resetting funds for user {self.user_id}: {e}")

    def check_margin_available(self, required_margin):
        """Check if user has sufficient margin available"""
        try:
            funds = SandboxFunds.query.filter_by(user_id=self.user_id).first()

            if not funds:
                return False, "Funds not initialized"

            required_margin = Decimal(str(required_margin))

            if funds.available_balance >= required_margin:
                return True, "Sufficient margin available"
            else:
                shortage = required_margin - funds.available_balance
                return False, f"Insufficient funds. Required: ₹{required_margin}, Available: ₹{funds.available_balance}, Shortage: ₹{shortage}"

        except Exception as e:
            logger.error(f"Error checking margin for user {self.user_id}: {e}")
            return False, f"Error checking margin: {str(e)}"

    def block_margin(self, amount, description=""):
        """Block margin for a trade"""
        with self._lock:
            try:
                funds = SandboxFunds.query.filter_by(user_id=self.user_id).first()

                if not funds:
                    return False, "Funds not initialized"

                amount = Decimal(str(amount))

                if funds.available_balance < amount:
                    return False, f"Insufficient funds. Required: ₹{amount}, Available: ₹{funds.available_balance}"

                # Block the margin
                funds.available_balance -= amount
                funds.used_margin += amount

                db_session.commit()

                logger.info(f"Blocked ₹{amount} margin for user {self.user_id}. {description}")
                return True, f"Margin blocked: ₹{amount}"

            except Exception as e:
                db_session.rollback()
                logger.error(f"Error blocking margin for user {self.user_id}: {e}")
                return False, f"Error blocking margin: {str(e)}"

    def release_margin(self, amount, realized_pnl=0, description=""):
        """Release blocked margin and update P&L"""
        with self._lock:
            try:
                funds = SandboxFunds.query.filter_by(user_id=self.user_id).first()

                if not funds:
                    return False, "Funds not initialized"

                amount = Decimal(str(amount))
                realized_pnl = Decimal(str(realized_pnl))

                # Release the margin
                funds.used_margin -= amount
                funds.available_balance += amount

                # Add realized P&L
                funds.available_balance += realized_pnl
                funds.realized_pnl += realized_pnl
                funds.total_pnl = funds.realized_pnl + funds.unrealized_pnl

                db_session.commit()

                logger.info(f"Released ₹{amount} margin for user {self.user_id}. Realized P&L: ₹{realized_pnl}. {description}")
                return True, f"Margin released: ₹{amount}, P&L: ₹{realized_pnl}"

            except Exception as e:
                db_session.rollback()
                logger.error(f"Error releasing margin for user {self.user_id}: {e}")
                return False, f"Error releasing margin: {str(e)}"

    def transfer_margin_to_holdings(self, amount, description=""):
        """
        Transfer margin to holdings during T+1 settlement
        Reduces used_margin without crediting available_balance
        (the money is now represented in holdings value, not available cash)
        """
        with self._lock:
            try:
                funds = SandboxFunds.query.filter_by(user_id=self.user_id).first()

                if not funds:
                    return False, "Funds not initialized"

                amount = Decimal(str(amount))

                # Reduce used margin (release from used_margin)
                # But do NOT credit available_balance - money is now in holdings
                funds.used_margin -= amount

                db_session.commit()

                logger.info(f"Transferred ₹{amount} margin to holdings for user {self.user_id}. {description}")
                return True, f"Margin transferred to holdings: ₹{amount}"

            except Exception as e:
                db_session.rollback()
                logger.error(f"Error transferring margin to holdings for user {self.user_id}: {e}")
                return False, f"Error transferring margin to holdings: {str(e)}"

    def credit_sale_proceeds(self, amount, description=""):
        """
        Credit sale proceeds from selling CNC holdings
        Increases available_balance when holdings are sold
        """
        with self._lock:
            try:
                funds = SandboxFunds.query.filter_by(user_id=self.user_id).first()

                if not funds:
                    return False, "Funds not initialized"

                amount = Decimal(str(amount))

                # Credit sale proceeds to available balance
                funds.available_balance += amount

                db_session.commit()

                logger.info(f"Credited ₹{amount} sale proceeds for user {self.user_id}. {description}")
                return True, f"Sale proceeds credited: ₹{amount}"

            except Exception as e:
                db_session.rollback()
                logger.error(f"Error crediting sale proceeds for user {self.user_id}: {e}")
                return False, f"Error crediting sale proceeds: {str(e)}"

    def update_unrealized_pnl(self, unrealized_pnl):
        """Update unrealized P&L from open positions"""
        with self._lock:
            try:
                funds = SandboxFunds.query.filter_by(user_id=self.user_id).first()

                if not funds:
                    return False, "Funds not initialized"

                unrealized_pnl = Decimal(str(unrealized_pnl))

                funds.unrealized_pnl = unrealized_pnl
                funds.total_pnl = funds.realized_pnl + funds.unrealized_pnl

                db_session.commit()

                return True, "Unrealized P&L updated"

            except Exception as e:
                db_session.rollback()
                logger.error(f"Error updating unrealized P&L for user {self.user_id}: {e}")
                return False, f"Error updating unrealized P&L: {str(e)}"

    def calculate_margin_required(self, symbol, exchange, product, quantity, price, action=None):
        """Calculate margin required for a trade based on leverage rules"""
        try:
            quantity = abs(int(quantity))
            price = Decimal(str(price))

            # Get symbol info to determine instrument type (from cache)
            symbol_obj = get_symbol_info(symbol, exchange)

            if not symbol_obj:
                logger.error(f"Symbol {symbol} not found on {exchange}")
                return None, "Symbol not found"

            # Calculate trade value (quantity × price)
            trade_value = quantity * price

            # Determine leverage based on action, product and symbol type
            leverage = self._get_leverage(exchange, product, symbol, action)

            if leverage is None:
                return None, "Unable to determine leverage"

            # Calculate margin (always use leverage-based calculation)
            margin = trade_value / Decimal(str(leverage))

            logger.debug(f"Margin for {symbol} {exchange} {product} {action}: ₹{margin} (Trade value: ₹{trade_value}, Leverage: {leverage}x)")

            return margin, "Margin calculated successfully"

        except Exception as e:
            logger.error(f"Error calculating margin: {e}")
            return None, f"Error calculating margin: {str(e)}"

    def _get_leverage(self, exchange, product, symbol, action=None):
        """Get leverage multiplier based on exchange, product, symbol type, and action"""
        try:
            # Equity exchanges
            if exchange in ['NSE', 'BSE']:
                if product == 'MIS':
                    return Decimal(get_config('equity_mis_leverage', '5'))
                elif product == 'CNC':
                    return Decimal(get_config('equity_cnc_leverage', '1'))
                else:  # NRML
                    return Decimal(get_config('equity_cnc_leverage', '1'))

            # Futures (NFO, BFO, MCX, CDS, BCD, NCDEX exchanges with FUT suffix)
            elif is_future(symbol, exchange):
                return Decimal(get_config('futures_leverage', '10'))

            # Options (NFO, BFO, MCX, CDS, BCD, NCDEX exchanges with CE/PE suffix)
            elif is_option(symbol, exchange):
                # Options use different leverage based on BUY vs SELL
                if action == 'BUY':
                    return Decimal(get_config('option_buy_leverage', '1'))
                else:  # SELL
                    return Decimal(get_config('option_sell_leverage', '1'))

            # Default to 1x leverage
            return Decimal('1')

        except Exception as e:
            logger.error(f"Error getting leverage: {e}")
            return Decimal('1')


def get_user_funds(user_id):
    """Helper function to get user funds"""
    fund_manager = FundManager(user_id)
    return fund_manager.get_funds()


def initialize_user_funds(user_id):
    """Helper function to initialize user funds"""
    fund_manager = FundManager(user_id)
    return fund_manager.initialize_funds()


def reset_all_user_funds():
    """
    Reset funds for all users (called by scheduler on configured reset day/time)
    This is the scheduled auto-reset function that runs independently of user actions.
    """
    try:
        logger.info("=== AUTO-RESET: Starting scheduled fund reset for all users ===")

        # Get all unique user IDs from funds table
        all_funds = SandboxFunds.query.all()

        if not all_funds:
            logger.info("No user funds to reset")
            return

        reset_count = 0
        for fund in all_funds:
            try:
                # Create FundManager for this user
                fm = FundManager(fund.user_id)

                # Call the internal reset function
                fm._reset_funds(fund)
                reset_count += 1

            except Exception as e:
                logger.error(f"Error resetting funds for user {fund.user_id}: {e}")
                continue

        logger.info(f"=== AUTO-RESET: Successfully reset {reset_count} user fund accounts ===")

    except Exception as e:
        logger.error(f"Error in scheduled auto-reset: {e}")


def reconcile_margin(user_id, auto_fix=True):
    """
    Reconcile used_margin in funds with actual margin blocked in positions.

    This function detects and optionally fixes margin discrepancies that can occur
    when position closures don't properly release margin.

    Args:
        user_id: User ID to reconcile
        auto_fix: If True, automatically fix discrepancies. If False, only report.

    Returns:
        tuple: (has_discrepancy: bool, discrepancy_amount: Decimal, message: str)
    """
    try:
        # Calculate total margin blocked across all open positions
        positions = SandboxPositions.query.filter_by(user_id=user_id).all()
        total_position_margin = sum(
            Decimal(str(pos.margin_blocked or 0))
            for pos in positions
            if pos.quantity != 0  # Only count open positions
        )

        # Get current used_margin from funds
        funds = SandboxFunds.query.filter_by(user_id=user_id).first()
        if not funds:
            return False, Decimal('0'), "No funds record found for user"

        current_used_margin = Decimal(str(funds.used_margin or 0))

        # Calculate discrepancy
        discrepancy = current_used_margin - total_position_margin

        if discrepancy == 0:
            return False, Decimal('0'), "No margin discrepancy detected"

        # Log the discrepancy
        logger.warning(
            f"Margin discrepancy detected for user {user_id}: "
            f"used_margin={current_used_margin}, position_margin={total_position_margin}, "
            f"discrepancy={discrepancy}"
        )

        if auto_fix:
            # Fix the discrepancy by adjusting used_margin and available_balance
            funds.used_margin = total_position_margin
            funds.available_balance += discrepancy  # Release the stuck margin
            db_session.commit()

            logger.info(
                f"Margin reconciled for user {user_id}: "
                f"Released {discrepancy} stuck margin, "
                f"new used_margin={total_position_margin}"
            )

            return True, discrepancy, f"Margin reconciled. Released {discrepancy} stuck margin."
        else:
            return True, discrepancy, f"Discrepancy of {discrepancy} detected but not fixed (auto_fix=False)"

    except Exception as e:
        logger.error(f"Error reconciling margin for user {user_id}: {e}")
        db_session.rollback()
        return False, Decimal('0'), f"Error during reconciliation: {str(e)}"


def reconcile_all_users_margin():
    """
    Reconcile margin for all users.

    Returns:
        dict: Summary of reconciliation results
    """
    try:
        logger.info("=== Starting margin reconciliation for all users ===")

        all_funds = SandboxFunds.query.all()

        if not all_funds:
            logger.info("No user funds to reconcile")
            return {"users_checked": 0, "discrepancies_found": 0, "total_released": 0}

        users_checked = 0
        discrepancies_found = 0
        total_released = Decimal('0')

        for fund in all_funds:
            has_discrepancy, amount, message = reconcile_margin(fund.user_id, auto_fix=True)
            users_checked += 1

            if has_discrepancy:
                discrepancies_found += 1
                total_released += amount
                logger.info(f"User {fund.user_id}: {message}")

        logger.info(
            f"=== Margin reconciliation complete: "
            f"{users_checked} users checked, {discrepancies_found} discrepancies fixed, "
            f"total margin released: {total_released} ==="
        )

        return {
            "users_checked": users_checked,
            "discrepancies_found": discrepancies_found,
            "total_released": float(total_released)
        }

    except Exception as e:
        logger.error(f"Error in margin reconciliation: {e}")
        return {"error": str(e)}


def validate_margin_consistency(user_id):
    """
    Validate that used_margin equals sum of position margins.
    Call this after position updates to detect issues early.

    Returns:
        tuple: (is_consistent: bool, discrepancy: Decimal)
    """
    try:
        # Calculate total margin blocked across all open positions
        positions = SandboxPositions.query.filter_by(user_id=user_id).all()
        total_position_margin = sum(
            Decimal(str(pos.margin_blocked or 0))
            for pos in positions
            if pos.quantity != 0  # Only count open positions
        )

        # Get current used_margin from funds
        funds = SandboxFunds.query.filter_by(user_id=user_id).first()
        if not funds:
            return True, Decimal('0')  # No funds = no discrepancy to report

        current_used_margin = Decimal(str(funds.used_margin or 0))
        discrepancy = current_used_margin - total_position_margin

        if discrepancy != 0:
            logger.warning(
                f"Margin inconsistency for user {user_id}: "
                f"used_margin={current_used_margin}, position_margin={total_position_margin}, "
                f"discrepancy={discrepancy}"
            )
            return False, discrepancy

        return True, Decimal('0')

    except Exception as e:
        logger.error(f"Error validating margin for user {user_id}: {e}")
        return True, Decimal('0')  # Don't block operations on validation error
