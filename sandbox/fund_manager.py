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
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

import pytz

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import Float, inspect, select, type_coerce, update

from database.sandbox_db import (
    SandboxFunds,
    SandboxHoldings,
    SandboxPositions,
    db_session,
    get_config,
)
from database.token_db import get_symbol_info
from utils.logging import get_logger
from utils.symbol_utils import is_future, is_option

logger = get_logger(__name__)

#: Every money column of a funds row. A write is applied only if none of them
#: moved since it was read, so two writers can never both start from the same
#: balance and have the second erase the first.
_MONEY_COLUMNS = (
    "total_capital",
    "available_balance",
    "used_margin",
    "realized_pnl",
    "today_realized_pnl",
    "unrealized_pnl",
    "total_pnl",
)

#: Attempts before a funds write gives up. A failed attempt leaves this
#: session holding SQLite's write lock, so the next read is the final word and
#: the second attempt succeeds; the rest are headroom, not an expected path.
_FUNDS_WRITE_ATTEMPTS = 5

#: What a trader sees in the one case the attempts run out.
FUNDS_BUSY_MESSAGE = (
    "Your sandbox funds were being updated by another order at the same moment. Please try again."
)


@dataclass(frozen=True)
class FundsSnapshot:
    """One read of a funds row.

    Attributes:
        values: Each money column as the ORM reads it (Decimal rounded to the
            column's two places, or None). Every calculation starts from these,
            exactly as it did when the row was read through the ORM.
        stored: The same columns exactly as stored. The write compares against
            these, because the stored value can carry more places than the
            rounded one and would never compare equal to it.
    """

    values: dict
    stored: dict


def read_funds_snapshot(user_id) -> FundsSnapshot | None:
    """Read a user's funds row fresh from the database, never from the session.

    A plain query hands back the object already in the session's identity map
    with the values it had when first loaded, so a thread that had read the
    row earlier would compute from a balance another thread has since changed.
    A column select is not cached, so this is always the committed row (or,
    inside a write transaction, the row this transaction sees).

    Returns:
        The snapshot, or None when the user has no funds row.
    """
    columns = [getattr(SandboxFunds, name) for name in _MONEY_COLUMNS]
    stored = [
        type_coerce(getattr(SandboxFunds, name), Float).label(f"stored_{name}")
        for name in _MONEY_COLUMNS
    ]
    row = db_session.execute(
        select(*columns, *stored).where(SandboxFunds.user_id == user_id)
    ).first()
    if row is None:
        return None
    count = len(_MONEY_COLUMNS)
    return FundsSnapshot(
        values={name: row[index] for index, name in enumerate(_MONEY_COLUMNS)},
        stored={name: row[count + index] for index, name in enumerate(_MONEY_COLUMNS)},
    )


def _expire_cached_funds(user_id) -> None:
    """Drop the session's cached copy of a funds row after a direct UPDATE."""
    for obj in list(db_session.identity_map.values()):
        if isinstance(obj, SandboxFunds) and inspect(obj).dict.get("user_id") == user_id:
            db_session.expire(obj)


def write_funds_if_unchanged(user_id, snapshot: FundsSnapshot, new_values: dict) -> bool:
    """Write ``new_values`` only if the row still holds what ``snapshot`` read.

    Only the columns whose value actually changes are written, which is what
    the ORM's own flush does, so a funds row ends up byte for byte the same as
    it did when these methods assigned attributes and committed. Nothing is
    committed here.

    Args:
        user_id: The funds row's owner.
        snapshot: The read the new values were computed from.
        new_values: Column name to new Decimal value.

    Returns:
        True if written (or there was nothing to write), False if another
        writer changed the row in between and the caller must read again.
    """
    changes = {name: value for name, value in new_values.items() if value != snapshot.values[name]}
    if not changes:
        return True
    stmt = update(SandboxFunds).where(SandboxFunds.user_id == user_id)
    for name in _MONEY_COLUMNS:
        column = getattr(SandboxFunds, name)
        stored = snapshot.stored[name]
        if stored is None:
            stmt = stmt.where(column.is_(None))
        else:
            stmt = stmt.where(type_coerce(column, Float) == stored)
    result = db_session.execute(
        stmt.values(**changes), execution_options={"synchronize_session": False}
    )
    if result.rowcount != 1:
        return False
    _expire_cached_funds(user_id)
    return True


def apply_funds_change(
    user_id,
    compute: Callable[[dict], tuple[bool, str, dict]],
    ensure: Callable[[], object] | None = None,
) -> tuple[bool, str]:
    """Read a funds row, compute its new values and write them as one step.

    ``compute`` receives the row's current values and returns
    ``(ok, message, new_values)``. A refusal (``ok`` False) writes nothing. If
    another writer changed the row between the read and the write, the whole
    thing is repeated from a fresh read, so the result is what it would have
    been had the two run one after the other. Nothing is committed here.

    Args:
        user_id: The funds row's owner.
        compute: The calculation, run against each fresh read.
        ensure: Called once when the row is missing, to create it.

    Returns:
        ``(ok, message)``: compute's own, or a funds-missing or busy outcome.
    """
    for _attempt in range(_FUNDS_WRITE_ATTEMPTS):
        snapshot = read_funds_snapshot(user_id)
        if snapshot is None and ensure is not None:
            ensure()
            ensure = None
            snapshot = read_funds_snapshot(user_id)
        if snapshot is None:
            return False, "Funds not initialized"
        ok, message, new_values = compute(snapshot.values)
        if not ok:
            return False, message
        if write_funds_if_unchanged(user_id, snapshot, new_values):
            return True, message
    logger.error(
        f"Funds for user {user_id} changed under every one of "
        f"{_FUNDS_WRITE_ATTEMPTS} attempts; nothing was written"
    )
    return False, FUNDS_BUSY_MESSAGE


def _released(values: dict, amount: Decimal, realized_pnl: Decimal, count_today: bool) -> dict:
    """New funds values after releasing ``amount`` of margin with ``realized_pnl``.

    The additions run in the same order the attribute assignments always did,
    so the Decimal results match to the last digit.
    """
    available = values["available_balance"] + amount
    available += realized_pnl
    realized = values["realized_pnl"] + realized_pnl
    new_values = {
        "used_margin": values["used_margin"] - amount,
        "available_balance": available,
        "realized_pnl": realized,
        "total_pnl": realized + values["unrealized_pnl"],
    }
    if count_today:
        new_values["today_realized_pnl"] = (
            values["today_realized_pnl"] or Decimal("0.00")
        ) + realized_pnl
    return new_values


class FundManager:
    """Manages sandbox funds for sandbox mode.

    Every change to a balance is a compare-and-set against a fresh read (see
    :func:`apply_funds_change`), not an update of an object loaded earlier.
    That is what keeps two threads, or a thread and a GTT's staged change, from
    starting at the same balance and losing one of their writes; a process lock
    could not, because the stale value comes from the session, not the thread.
    """

    # Guards creating a funds row and the scheduled reset only. Balance changes
    # need no lock: each is a single conditional write in the database.
    _lock = threading.RLock()

    def __init__(self, user_id):
        self.user_id = user_id
        self.starting_capital = Decimal(get_config("starting_capital", "10000000.00"))

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
                        used_margin=Decimal("0.00"),
                        realized_pnl=Decimal("0.00"),
                        today_realized_pnl=Decimal("0.00"),
                        unrealized_pnl=Decimal("0.00"),
                        total_pnl=Decimal("0.00"),
                        last_reset_date=datetime.now(pytz.timezone("Asia/Kolkata")),
                        reset_count=0,
                    )
                    db_session.add(funds)
                    db_session.commit()
                    logger.info(
                        f"Initialized funds for user {self.user_id} with ₹{self.starting_capital}"
                    )
                    return True, "Funds initialized successfully"
                else:
                    logger.debug(f"User {self.user_id} already has funds initialized")
                    return True, "Funds already initialized"

            except Exception as e:
                db_session.rollback()
                logger.exception(f"Error initializing funds for user {self.user_id}: {e}")
                return False, f"Error initializing funds: {str(e)}"

    def get_funds(self):
        """Get current fund status for user"""
        try:
            # populate_existing: a thread that read this row before (a pooled
            # request thread, a job thread) would otherwise be handed its own
            # earlier copy instead of the balance as it stands now.
            funds = SandboxFunds.query.filter_by(user_id=self.user_id).populate_existing().first()

            if not funds:
                # Initialize funds if not exists
                success, message = self.initialize_funds()
                if not success:
                    return None

                funds = (
                    SandboxFunds.query.filter_by(user_id=self.user_id).populate_existing().first()
                )

            # Check if reset is needed
            self._check_and_reset_funds(funds)

            # Return fund details
            return {
                "availablecash": float(funds.available_balance),
                "collateral": 0.00,  # No collateral in sandbox
                "m2munrealized": float(funds.unrealized_pnl),
                "m2mrealized": float(
                    funds.today_realized_pnl or 0
                ),  # Today's realized P&L (resets daily)
                "total_realized_pnl": float(funds.realized_pnl),  # All-time realized P&L
                "today_realized_pnl": float(funds.today_realized_pnl or 0),
                "utiliseddebits": float(funds.used_margin),
                "grossexposure": float(funds.used_margin),
                "totalpnl": float(funds.total_pnl),
                "last_reset": funds.last_reset_date.strftime("%Y-%m-%d %H:%M:%S"),
                "reset_count": funds.reset_count,
            }

        except Exception as e:
            logger.exception(f"Error getting funds for user {self.user_id}: {e}")
            return None

    def _check_and_reset_funds(self, funds):
        """Check if funds need to be reset (every Sunday at midnight IST)"""
        try:
            # Check if auto-reset is disabled
            reset_day = get_config("reset_day", "Never")
            if reset_day.lower() == "never":
                return  # Skip reset check entirely

            ist = pytz.timezone("Asia/Kolkata")
            now = datetime.now(ist)
            last_reset = funds.last_reset_date

            # Make last_reset timezone aware if it isn't
            if last_reset.tzinfo is None:
                last_reset = ist.localize(last_reset)

            # Check if it's the configured reset day and we haven't reset today
            reset_time_str = get_config("reset_time", "00:00")

            if now.strftime("%A") == reset_day:
                reset_hour, reset_minute = map(int, reset_time_str.split(":"))
                reset_time_today = now.replace(
                    hour=reset_hour, minute=reset_minute, second=0, microsecond=0
                )

                # If current time is past reset time and last reset was before today's reset time
                if now >= reset_time_today and last_reset < reset_time_today:
                    self._reset_funds(funds)

        except Exception as e:
            logger.exception(f"Error checking fund reset for user {self.user_id}: {e}")

    def _reset_funds(self, funds):
        """Reset funds to starting capital"""
        with self._lock:
            try:
                logger.info(f"Resetting funds for user {self.user_id}")

                # Reset all fund values
                funds.total_capital = self.starting_capital
                funds.available_balance = self.starting_capital
                funds.used_margin = Decimal("0.00")
                funds.realized_pnl = Decimal("0.00")
                funds.today_realized_pnl = Decimal("0.00")
                funds.unrealized_pnl = Decimal("0.00")
                funds.total_pnl = Decimal("0.00")
                funds.last_reset_date = datetime.now(pytz.timezone("Asia/Kolkata"))
                funds.reset_count += 1

                db_session.commit()

                # Clear all positions and holdings
                SandboxPositions.query.filter_by(user_id=self.user_id).delete()
                SandboxHoldings.query.filter_by(user_id=self.user_id).delete()
                db_session.commit()

                logger.info(
                    f"Funds reset successfully for user {self.user_id} (Reset #{funds.reset_count})"
                )

            except Exception as e:
                db_session.rollback()
                logger.exception(f"Error resetting funds for user {self.user_id}: {e}")

    def _ensure_funds_initialized(self):
        """Ensure funds are initialized for the user, creating them if needed.

        Returns:
            SandboxFunds or None: The funds record, or None if initialization failed.
        """
        # populate_existing: return the row as it stands now, not a copy this
        # thread's session loaded earlier and never refreshed.
        funds = SandboxFunds.query.filter_by(user_id=self.user_id).populate_existing().first()
        if not funds:
            logger.info(f"Auto-initializing funds for user {self.user_id}")
            success, message = self.initialize_funds()
            if not success:
                logger.error(f"Failed to auto-initialize funds for user {self.user_id}: {message}")
                return None
            funds = SandboxFunds.query.filter_by(user_id=self.user_id).first()
        return funds

    def _apply(self, compute):
        """Apply ``compute`` to this user's funds as one compare-and-set write.

        Creates the funds row first if it is missing, as every mutator always
        did. Nothing is committed here.
        """
        return apply_funds_change(self.user_id, compute, ensure=self._ensure_funds_initialized)

    def check_margin_available(self, required_margin):
        """Check if user has sufficient margin available"""
        try:
            funds = self._ensure_funds_initialized()

            if not funds:
                return False, "Funds not initialized"

            required_margin = Decimal(str(required_margin))

            if funds.available_balance >= required_margin:
                return True, "Sufficient margin available"
            else:
                shortage = required_margin - funds.available_balance
                return (
                    False,
                    f"Insufficient funds. Required: ₹{required_margin}, Available: ₹{funds.available_balance}, Shortage: ₹{shortage}",
                )

        except Exception as e:
            logger.exception(f"Error checking margin for user {self.user_id}: {e}")
            return False, f"Error checking margin: {str(e)}"

    def stage_margin_delta(self, delta, description=""):
        """Apply a margin change WITHOUT committing, so a caller can make the
        funds move and its own state change one transaction.

        block_margin and release_margin each commit on their own. That is right
        for a plain order, but it makes a GTT transition two separate commits:
        the funds move, then the GTT row is written, and a failure in between
        leaves the ledger and the row disagreeing about the same money with
        nothing to reconcile them. Callers that must be atomic stage the change
        here and commit once, so either both land or neither does.

        Args:
            delta: Positive to block (reserve), negative to release.
            description: For the log line.

        Returns:
            ``(ok, message)``. The caller must commit on success and roll back
            on failure - nothing is committed here.
        """
        try:
            if not self._ensure_funds_initialized():
                return False, "Funds not initialized"

            delta = Decimal(str(delta))
            if delta == 0:
                return True, "No change"

            # A single UPDATE that computes the new balance in SQL, not in
            # Python. Reading the row, adjusting it in memory and letting the
            # caller commit is a lost update: two threads each read the same
            # starting balance, each write their own total, and the second
            # commit erases the first - two GTTs reserving 950 each while the
            # ledger moved only once. The class lock cannot help, because it is
            # released long before the caller commits, and it protects nothing
            # against a second process.
            #
            # The sufficiency check is part of the WHERE clause for the same
            # reason: checking in Python and updating afterwards is
            # check-then-act, and rowcount tells us which of the two happened.
            stmt = update(SandboxFunds).where(SandboxFunds.user_id == self.user_id)
            if delta > 0:
                stmt = stmt.where(SandboxFunds.available_balance >= delta)
            else:
                # Releasing more than is actually reserved would drive
                # used_margin negative and credit the difference as available
                # cash - money the account never had. Guarded in the same
                # statement so the check cannot be raced past.
                stmt = stmt.where(SandboxFunds.used_margin >= -delta)
            stmt = stmt.values(
                available_balance=SandboxFunds.available_balance - delta,
                used_margin=SandboxFunds.used_margin + delta,
            )
            result = db_session.execute(stmt, execution_options={"synchronize_session": False})

            if result.rowcount != 1:
                if delta > 0:
                    return False, f"Insufficient funds. Required: ₹{delta}"
                return (
                    False,
                    f"Cannot release ₹{-delta}: more than the reserved margin",
                )

            # The in-memory copy is now stale; drop it so later reads see the
            # value the database actually holds.
            _expire_cached_funds(self.user_id)

            # Deliberately no commit: the caller owns the transaction.
            logger.info(f"Staged ₹{delta} margin change for user {self.user_id}. {description}")
            return True, f"Margin change staged: ₹{delta}"
        except Exception as e:
            logger.exception(f"Error staging margin for user {self.user_id}: {e}")
            return False, f"Error staging margin: {str(e)}"

    def block_margin(self, amount, description=""):
        """Block margin for a trade"""
        try:
            amount = Decimal(str(amount))

            def compute(funds):
                # A negative "block" is a release wearing the wrong name: it
                # subtracts from used_margin and credits available_balance,
                # inventing cash. Amounts are always positive; direction is
                # the method you call.
                if amount <= 0:
                    return False, f"Block amount must be positive, got {amount}", None

                if funds["available_balance"] < amount:
                    return (
                        False,
                        f"Insufficient funds. Required: ₹{amount}, Available: ₹{funds['available_balance']}",
                        None,
                    )

                return (
                    True,
                    f"Margin blocked: ₹{amount}",
                    {
                        "available_balance": funds["available_balance"] - amount,
                        "used_margin": funds["used_margin"] + amount,
                    },
                )

            ok, message = self._apply(compute)
            if not ok:
                return False, message

            db_session.commit()

            logger.info(f"Blocked ₹{amount} margin for user {self.user_id}. {description}")
            return True, message

        except Exception as e:
            db_session.rollback()
            logger.exception(f"Error blocking margin for user {self.user_id}: {e}")
            return False, f"Error blocking margin: {str(e)}"

    def stage_release_margin(
        self, amount, realized_pnl=0, description="", count_today=True, log=True
    ):
        """Release blocked margin and book P&L WITHOUT committing.

        The same arithmetic and the same refusals as :meth:`release_margin`,
        for a caller that must land the release and its own state change in
        one commit (expiry settlement, which otherwise released the margin in
        one commit and closed the position in the next, so a second settler
        arriving in between released it again).

        Args:
            amount: Margin to release; never negative.
            realized_pnl: P&L to book; a loss is negative.
            description: For the log line.
            count_today: Also add the P&L to today's realized P&L.
            log: Log the release here; the committing wrapper logs after its
                commit instead.

        Returns:
            ``(ok, message)``. Nothing is committed.
        """
        amount = Decimal(str(amount))
        realized_pnl = Decimal(str(realized_pnl))

        def compute(funds):
            # A negative release blocks margin and destroys available cash;
            # same reasoning as block_margin. realized_pnl is deliberately
            # unrestricted - a loss is a legitimate negative.
            if amount < 0:
                return False, f"Release amount cannot be negative, got {amount}", None

            # Refuse to release more than is reserved. Letting it through
            # drives used_margin negative and credits the difference as
            # available cash, so a single over-release anywhere - a double
            # release, a stale amount, a recovery bug - invents money and
            # every figure derived from the balance is wrong afterwards.
            # Failing here instead leaves the margin blocked, which
            # reconcile_margin(auto_fix=True) already exists to correct.
            if amount > funds["used_margin"]:
                logger.error(
                    f"Refusing to release ₹{amount} for user {self.user_id}: only "
                    f"₹{funds['used_margin']} is reserved. {description}"
                )
                return (
                    False,
                    f"Cannot release ₹{amount}: only ₹{funds['used_margin']} is reserved",
                    None,
                )

            return (
                True,
                f"Margin released: ₹{amount}, P&L: ₹{realized_pnl}",
                _released(funds, amount, realized_pnl, count_today),
            )

        ok, message = self._apply(compute)
        if ok and log:
            self._log_release(amount, realized_pnl, description)
        return ok, message

    def _log_release(self, amount, realized_pnl, description):
        logger.info(
            f"Released ₹{Decimal(str(amount))} margin for user {self.user_id}. "
            f"Realized P&L: ₹{Decimal(str(realized_pnl))}. {description}"
        )

    def release_margin(self, amount, realized_pnl=0, description=""):
        """Release blocked margin and update P&L"""
        try:
            ok, message = self.stage_release_margin(amount, realized_pnl, description, log=False)
            if not ok:
                return False, message

            db_session.commit()

            self._log_release(amount, realized_pnl, description)
            return True, message

        except Exception as e:
            db_session.rollback()
            logger.exception(f"Error releasing margin for user {self.user_id}: {e}")
            return False, f"Error releasing margin: {str(e)}"

    def stage_transfer_margin_to_holdings(self, amount, description="", log=True):
        """:meth:`transfer_margin_to_holdings` without the commit.

        T+1 settlement stages every transfer and commits once with the holding
        and position changes they belong to.

        Returns:
            ``(ok, message)``. Nothing is committed.
        """
        amount = Decimal(str(amount))

        def compute(funds):
            if amount <= 0:
                return False, f"Transfer amount must be positive, got {amount}", None

            # Same ceiling as release_margin. This is the T+1 settlement
            # path, so an over-transfer drives used_margin negative and the
            # difference silently becomes headroom for further trades -
            # without even the visible cash bump a bad release leaves.
            if amount > funds["used_margin"]:
                logger.error(
                    f"Refusing to transfer ₹{amount} to holdings for user "
                    f"{self.user_id}: only ₹{funds['used_margin']} is reserved. "
                    f"{description}"
                )
                return (
                    False,
                    f"Cannot transfer ₹{amount}: only ₹{funds['used_margin']} is reserved",
                    None,
                )

            # Reduce used margin (release from used_margin)
            # But do NOT credit available_balance - money is now in holdings
            return (
                True,
                f"Margin transferred to holdings: ₹{amount}",
                {"used_margin": funds["used_margin"] - amount},
            )

        ok, message = self._apply(compute)
        if ok and log:
            self._log_transfer(amount, description)
        return ok, message

    def _log_transfer(self, amount, description):
        logger.debug(
            f"Transferred ₹{Decimal(str(amount))} margin to holdings for user "
            f"{self.user_id}. {description}"
        )

    def transfer_margin_to_holdings(self, amount, description=""):
        """
        Transfer margin to holdings during T+1 settlement
        Reduces used_margin without crediting available_balance
        (the money is now represented in holdings value, not available cash)
        """
        try:
            ok, message = self.stage_transfer_margin_to_holdings(amount, description, log=False)
            if not ok:
                return False, message

            db_session.commit()

            self._log_transfer(amount, description)
            return True, message

        except Exception as e:
            db_session.rollback()
            logger.exception(f"Error transferring margin to holdings for user {self.user_id}: {e}")
            return False, f"Error transferring margin to holdings: {str(e)}"

    def stage_credit_sale_proceeds(self, amount, description="", log=True):
        """:meth:`credit_sale_proceeds` without the commit.

        Returns:
            ``(ok, message)``. Nothing is committed.
        """
        amount = Decimal(str(amount))

        def compute(funds):
            # A negative credit debits available_balance with none of the
            # sufficiency checks a real debit goes through.
            if amount <= 0:
                return False, f"Credit amount must be positive, got {amount}", None

            # Credit sale proceeds to available balance
            return (
                True,
                f"Sale proceeds credited: ₹{amount}",
                {"available_balance": funds["available_balance"] + amount},
            )

        ok, message = self._apply(compute)
        if ok and log:
            self._log_credit(amount, description)
        return ok, message

    def _log_credit(self, amount, description):
        logger.info(
            f"Credited ₹{Decimal(str(amount))} sale proceeds for user {self.user_id}. {description}"
        )

    def credit_sale_proceeds(self, amount, description=""):
        """
        Credit sale proceeds from selling CNC holdings
        Increases available_balance when holdings are sold
        """
        try:
            ok, message = self.stage_credit_sale_proceeds(amount, description, log=False)
            if not ok:
                return False, message

            db_session.commit()

            self._log_credit(amount, description)
            return True, message

        except Exception as e:
            db_session.rollback()
            logger.exception(f"Error crediting sale proceeds for user {self.user_id}: {e}")
            return False, f"Error crediting sale proceeds: {str(e)}"

    def stage_prior_session_release(self, amount, realized_pnl, description=""):
        """Settle a position left over from a previous session, WITHOUT committing.

        The catch-up for an MIS position that outlived its session. It differs
        from :meth:`stage_release_margin` on purpose: the P&L belongs to a day
        that has already closed, so it goes to all-time realized P&L and not
        to today's, and used margin is floored at zero rather than refused.

        Returns:
            ``(ok, message)``. Nothing is committed.
        """
        amount = Decimal(str(amount))
        realized_pnl = Decimal(str(realized_pnl))

        def compute(funds):
            # Release margin back to available balance
            available = funds["available_balance"] + (amount + realized_pnl)
            used = funds["used_margin"] - amount

            # Add to all-time realized P&L only (NOT today_realized_pnl)
            realized = (funds["realized_pnl"] or Decimal("0.00")) + realized_pnl
            total = realized + (funds["unrealized_pnl"] or Decimal("0.00"))

            # Ensure used_margin doesn't go negative
            if used < 0:
                used = Decimal("0.00")

            return (
                True,
                f"Prior-session position settled: ₹{amount}, P&L: ₹{realized_pnl}",
                {
                    "available_balance": available,
                    "used_margin": used,
                    "realized_pnl": realized,
                    "total_pnl": total,
                },
            )

        # No ensure: this catch-up only ever adjusted a funds row that already
        # existed, and settling a stale position must not create one.
        ok, message = apply_funds_change(self.user_id, compute)
        if ok:
            logger.debug(
                f"Staged prior-session release of ₹{amount} for user {self.user_id}. {description}"
            )
        return ok, message

    def update_unrealized_pnl(self, unrealized_pnl):
        """Update unrealized P&L from open positions"""
        try:
            unrealized_pnl = Decimal(str(unrealized_pnl))

            def compute(funds):
                return (
                    True,
                    "Unrealized P&L updated",
                    {
                        "unrealized_pnl": unrealized_pnl,
                        "total_pnl": funds["realized_pnl"] + unrealized_pnl,
                    },
                )

            ok, message = self._apply(compute)
            if not ok:
                return False, message

            db_session.commit()

            return True, message

        except Exception as e:
            db_session.rollback()
            logger.exception(f"Error updating unrealized P&L for user {self.user_id}: {e}")
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

            logger.debug(
                f"Margin for {symbol} {exchange} {product} {action}: ₹{margin} (Trade value: ₹{trade_value}, Leverage: {leverage}x)"
            )

            return margin, "Margin calculated successfully"

        except Exception as e:
            logger.exception(f"Error calculating margin: {e}")
            return None, f"Error calculating margin: {str(e)}"

    def _get_leverage(self, exchange, product, symbol, action=None):
        """Get leverage multiplier based on exchange, product, symbol type, and action"""
        try:
            # Equity exchanges
            if exchange in ["NSE", "BSE"]:
                if product == "MIS":
                    return Decimal(get_config("equity_mis_leverage", "5"))
                elif product == "CNC":
                    return Decimal(get_config("equity_cnc_leverage", "1"))
                else:  # NRML
                    return Decimal(get_config("equity_cnc_leverage", "1"))

            # Futures (NFO, BFO, MCX, CDS, BCD, NCDEX exchanges with FUT suffix)
            elif is_future(symbol, exchange):
                return Decimal(get_config("futures_leverage", "10"))

            # Options (NFO, BFO, MCX, CDS, BCD, NCDEX exchanges with CE/PE suffix)
            elif is_option(symbol, exchange):
                # Options use different leverage based on BUY vs SELL
                if action == "BUY":
                    return Decimal(get_config("option_buy_leverage", "1"))
                else:  # SELL
                    return Decimal(get_config("option_sell_leverage", "1"))

            # Default to 1x leverage
            return Decimal("1")

        except Exception as e:
            logger.exception(f"Error getting leverage: {e}")
            return Decimal("1")


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
                logger.exception(f"Error resetting funds for user {fund.user_id}: {e}")
                continue

        logger.info(f"=== AUTO-RESET: Successfully reset {reset_count} user fund accounts ===")

    except Exception as e:
        logger.exception(f"Error in scheduled auto-reset: {e}")


def rebase_starting_capital(new_capital) -> int:
    """Move every funds row onto a new starting capital, keeping its margin and P&L.

    For each row, total capital becomes ``new_capital`` and the available
    balance becomes ``new_capital - used_margin + total_pnl``. Each row is
    written as a compare-and-set against a fresh read, so a margin block that
    commits while this runs is kept rather than overwritten by a balance
    computed from before it. All rows are committed together.

    Args:
        new_capital: The new starting capital.

    Returns:
        The number of funds rows updated.

    Raises:
        RuntimeError: A row kept changing under every attempt; nothing is
            committed and the caller rolls back.
    """
    new_capital = Decimal(str(new_capital))
    user_ids = [
        user_id
        for (user_id,) in db_session.execute(
            select(SandboxFunds.user_id).order_by(SandboxFunds.id)
        ).all()
    ]

    def compute(funds):
        # Calculate what the new available balance should be
        # New available = new_capital - used_margin + total_pnl
        return (
            True,
            "",
            {
                "total_capital": new_capital,
                "available_balance": new_capital - funds["used_margin"] + funds["total_pnl"],
            },
        )

    for user_id in user_ids:
        ok, message = apply_funds_change(user_id, compute)
        if not ok:
            raise RuntimeError(
                f"Could not move funds of user {user_id} to the new capital: {message}"
            )

    db_session.commit()
    return len(user_ids)


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
        holds_write_lock = False
        for _attempt in range(_FUNDS_WRITE_ATTEMPTS):
            outcome = _reconcile_once(user_id, auto_fix, holds_write_lock)
            if outcome is not None:
                return outcome
            # Funds moved between the read and the write. The failed write left
            # this session holding SQLite's write lock, so reading funds,
            # positions and GTTs again gives the final word.
            holds_write_lock = True

        db_session.rollback()
        logger.warning(
            f"Margin reconciliation for user {user_id} skipped: funds kept changing while it ran"
        )
        return False, Decimal("0"), "Funds changed during reconciliation; skipped"

    except Exception as e:
        logger.exception(f"Error reconciling margin for user {user_id}: {e}")
        db_session.rollback()
        return False, Decimal("0"), f"Error during reconciliation: {str(e)}"


def _reconcile_once(user_id, auto_fix, holds_write_lock=False):
    """One read-compare-write pass of :func:`reconcile_margin`.

    Args:
        user_id: The account to reconcile.
        auto_fix: Write the correction, or only report it.
        holds_write_lock: True for a pass after a lost compare-and-set, which
            runs inside the transaction that failed write opened.

    Returns:
        reconcile_margin's result tuple, or None when the funds row changed
        between the read and the write and the pass must be repeated.
    """

    def settle(result):
        # A pass after a lost compare-and-set holds SQLite's write lock. One
        # that ends without writing must close that transaction: the engine
        # threads that call this never release their sessions, so the lock
        # would stay with them until something else on that thread commits,
        # which can be hours, and every other sandbox writer (order placement,
        # the position book, square-off) fails with "database is locked".
        if holds_write_lock:
            db_session.rollback()
        return result

    # Funds first. Every writer that moves position or GTT margin moves the
    # funds row in the same commit (settlement, T+1, a GTT reserving or
    # releasing), so any such commit landing between these reads changes the
    # funds row after it was read, and the compare-and-set below refuses the
    # write. Read the other way round, a settlement between the reads moved
    # both while the funds row still matched its snapshot, and the correction
    # re-blocked the margin the settlement had just released. A fill that opens
    # or adds to a position moves margin from its order to the position without
    # touching funds, and read in this order it cannot make a discrepancy
    # appear either.
    snapshot = read_funds_snapshot(user_id)
    if snapshot is None:
        return settle((False, Decimal("0"), "No funds record found for user"))

    # Calculate total margin blocked across all open positions. populate_existing
    # so the margins are the committed ones, not copies this session loaded
    # earlier (a second pass, a pooled thread).
    positions = SandboxPositions.query.filter_by(user_id=user_id).populate_existing().all()
    total_position_margin = sum(
        Decimal(str(pos.margin_blocked or 0))
        for pos in positions
        if pos.quantity != 0  # Only count open positions
    )

    # Active GTTs hold margin too. Without counting them a resting GTT looks
    # exactly like a leaked reservation, and with auto_fix on that would
    # release the very margin the GTT needs to place its order when it
    # fires.
    try:
        from database.sandbox_db import SandboxGTT

        total_gtt_margin = sum(
            Decimal(str(gtt.margin_blocked or 0))
            for gtt in SandboxGTT.query.filter_by(user_id=user_id, gtt_status="active")
            .populate_existing()
            .all()
        )
    except Exception:
        logger.exception(
            "Could not total active GTT margin during reconciliation; "
            "skipping reconciliation rather than risk releasing it"
        )
        return settle((False, Decimal("0"), "GTT margin unavailable; reconciliation skipped"))

    total_position_margin += total_gtt_margin

    # used_margin as read above, fresh from the database: a copy read earlier
    # would decide the discrepancy on a balance that has since moved.
    current_used_margin = Decimal(str(snapshot.values["used_margin"] or 0))

    # Calculate discrepancy
    discrepancy = current_used_margin - total_position_margin

    if discrepancy == 0:
        return settle((False, Decimal("0"), "No margin discrepancy detected"))

    # Log the discrepancy
    logger.warning(
        f"Margin discrepancy detected for user {user_id}: "
        f"used_margin={current_used_margin}, position_margin={total_position_margin}, "
        f"discrepancy={discrepancy}"
    )

    if not auto_fix:
        return settle(
            (
                True,
                discrepancy,
                f"Discrepancy of {discrepancy} detected but not fixed (auto_fix=False)",
            )
        )

    # Fix the discrepancy by adjusting used_margin and available_balance, but
    # only if the funds row is still what was read: an order that blocked
    # margin in between would otherwise have its block erased.
    new_values = {
        "used_margin": total_position_margin,
        "available_balance": snapshot.values["available_balance"] + discrepancy,
    }
    if not write_funds_if_unchanged(user_id, snapshot, new_values):
        return None
    db_session.commit()

    logger.info(
        f"Margin reconciled for user {user_id}: "
        f"Released {discrepancy} stuck margin, "
        f"new used_margin={total_position_margin}"
    )

    return True, discrepancy, f"Margin reconciled. Released {discrepancy} stuck margin."


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
        total_released = Decimal("0")

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
            "total_released": float(total_released),
        }

    except Exception as e:
        logger.exception(f"Error in margin reconciliation: {e}")
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
            return True, Decimal("0")  # No funds = no discrepancy to report

        current_used_margin = Decimal(str(funds.used_margin or 0))
        discrepancy = current_used_margin - total_position_margin

        if discrepancy != 0:
            logger.warning(
                f"Margin inconsistency for user {user_id}: "
                f"used_margin={current_used_margin}, position_margin={total_position_margin}, "
                f"discrepancy={discrepancy}"
            )
            return False, discrepancy

        return True, Decimal("0")

    except Exception as e:
        logger.exception(f"Error validating margin for user {user_id}: {e}")
        return True, Decimal("0")  # Don't block operations on validation error
