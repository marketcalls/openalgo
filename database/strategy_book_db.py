# database/strategy_book_db.py
"""
Per-strategy position book and P&L ledger.

The broker nets positions per `(symbol, exchange, product)` and knows nothing
about which strategy opened them, so two strategies trading the same contract
are indistinguishable downstream. This module keeps a parallel book keyed by
strategy so a workflow can ask "how is *this* strategy doing?" and exit on
its own P&L rather than the account's.

Design notes:

* **Fed entirely from the event bus.** `order.placed` supplies the
  orderid -> strategy mapping (the only place the tag is known) and
  `order.update` supplies fills. Nothing in the order execution path is
  modified, so live trading is untouched by this feature.
* **Idempotent.** Order updates can arrive more than once - a broker feed and
  a postback may both report the same fill - so applied quantity is tracked
  per order and only the unseen delta is booked. This also makes partial
  fills fall out naturally.
* **Weighted-average cost**, matching how OpenAlgo and Indian brokers report
  `average_price`. A position flipping through zero realizes the closed leg
  and reopens the remainder at the fill price.
* **Realized P&L accumulates**; `today_realized` resets on the first fill of
  a new trading date, which keeps it aligned with the ~3 AM IST session
  rollover without needing a scheduler.

Unrealized P&L is deliberately *not* stored. It is a function of the last
traded price and would be stale the moment it was written; it is computed at
read time in `services/strategy_pnl_service.py`.
"""

import os
import threading
from datetime import datetime, timedelta

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from database.engine_factory import create_db_engine
from utils.env_config import env_int
from utils.logging import get_logger

logger = get_logger(__name__)

# Serializes the read-modify-write of an order's applied-quantity watermark and
# its position row. The event bus dispatches on a thread pool, so concurrent
# updates for one order would otherwise double-book or lose a fill. Reentrant
# because draining a buffered fill re-enters apply_fill. Production is a single
# worker, so an in-process lock is sufficient.
_fill_lock = threading.RLock()

# Set once the tables exist. Reads must fail loudly rather than report an empty
# book: a strategy P&L of zero is indistinguishable from "flat and fine" to an
# exit trigger, so an uninitialized book must never be reported as one.
_initialized = False


class StrategyBookUnavailable(RuntimeError):
    """The per-strategy book could not be read, so its figures are unknown."""

engine = create_db_engine()

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class StrategyOrderTag(Base):
    """orderid -> strategy, captured when the order is placed.

    Fills arrive later carrying only an orderid, so without this the strategy
    that produced a trade cannot be recovered.
    """

    __tablename__ = "strategy_order_tags"

    id = Column(Integer, primary_key=True)
    orderid = Column(String(64), nullable=False, unique=True, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    strategy = Column(String(120), nullable=False, index=True)
    symbol = Column(String(64), nullable=False)
    exchange = Column(String(20), nullable=False)
    product = Column(String(20), nullable=False)
    # Cumulative quantity already booked for this order, so a repeated or
    # partial-fill update only contributes its unseen delta.
    applied_quantity = Column(Float, nullable=False, default=0.0)
    # Cumulative notional (quantity x price) already booked. Brokers report
    # `average_price` cumulatively, so the incremental price of a partial fill
    # must be derived from the change in notional - booking the delta at the
    # latest cumulative average corrupts the cost basis whenever partials
    # execute at different prices.
    applied_notional = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class StrategyPendingFill(Base):
    """A fill whose order tag had not been recorded yet.

    EventBus callbacks run on a shared pool, and in analyze mode an
    immediately marketable order publishes its fill from the sandbox engine
    *before* place_order_service publishes order.placed. Without buffering,
    such a fill finds no tag and is lost permanently.
    """

    __tablename__ = "strategy_pending_fills"

    id = Column(Integer, primary_key=True)
    orderid = Column(String(64), nullable=False, index=True)
    filled_quantity = Column(Float, nullable=False)
    average_price = Column(Float, nullable=False)
    action = Column(String(10), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class StrategyPosition(Base):
    """Open position and accumulated realized P&L for one strategy leg."""

    __tablename__ = "strategy_positions"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "strategy", "symbol", "exchange", "product", name="uq_strategy_leg"
        ),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(String(64), nullable=False, index=True)
    strategy = Column(String(120), nullable=False, index=True)
    symbol = Column(String(64), nullable=False, index=True)
    exchange = Column(String(20), nullable=False)
    product = Column(String(20), nullable=False)
    # Signed: positive long, negative short.
    quantity = Column(Float, nullable=False, default=0.0)
    average_price = Column(Float, nullable=False, default=0.0)
    realized_pnl = Column(Float, nullable=False, default=0.0)
    today_realized_pnl = Column(Float, nullable=False, default=0.0)
    trade_date = Column(String(10), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


def init_strategy_book_db() -> None:
    """Create tables if absent, then apply column migrations. Idempotent."""
    global _initialized
    Base.metadata.create_all(bind=engine)
    _migrate_add_columns()
    _prune_old_tags()
    _initialized = True
    logger.debug("Strategy book DB initialized")


def is_initialized() -> bool:
    """Whether the book is usable. False means its figures are unknown."""
    return _initialized


# One tag row exists per order, forever, and the key space is every order ever
# placed - so it needs a retention bound. An order cannot report new fills days
# after the fact, making anything past this window safe to drop.
_TAG_RETENTION = timedelta(days=env_int("STRATEGY_TAG_RETENTION_DAYS", 30, minimum=1))


def _prune_old_tags() -> None:
    """Drop order tags well past the point where new fills could arrive."""
    try:
        cutoff = datetime.now() - _TAG_RETENTION
        removed = (
            db_session.query(StrategyOrderTag)
            .filter(StrategyOrderTag.created_at < cutoff)
            .delete(synchronize_session=False)
        )
        if removed:
            db_session.commit()
            logger.info(f"Strategy book: pruned {removed} order tag(s) past retention")
    except Exception:
        db_session.rollback()
        logger.exception("Could not prune old order tags")


def _migrate_add_columns():
    """Add columns introduced after the table's first release (idempotent).

    create_all() only creates missing *tables*, so an install that already has
    strategy_order_tags would otherwise never gain applied_notional and every
    query against the model would fail.
    """
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        if "strategy_order_tags" not in inspector.get_table_names():
            return
        existing = {c["name"] for c in inspector.get_columns("strategy_order_tags")}
        with engine.begin() as conn:
            if "applied_notional" not in existing:
                conn.execute(
                    text(
                        "ALTER TABLE strategy_order_tags "
                        "ADD COLUMN applied_notional FLOAT NOT NULL DEFAULT 0.0"
                    )
                )
                logger.info("Strategy book DB: added applied_notional column")
    except Exception:
        logger.exception("Strategy book DB: column migration failed")


def _session_date() -> str:
    """The current trading session's date (03:00 IST rollover), as ISO text.

    Not ``date.today()``: that is the server's local calendar date, which
    mislabels everything traded between midnight and the rollover and is not
    even IST on a host outside India.
    """
    try:
        from utils.session import get_trading_session_date

        return get_trading_session_date()
    except Exception:
        logger.exception("Could not resolve trading session date; falling back to local date")
        return datetime.now().date().isoformat()


def record_order_tag(
    orderid: str, user_id: str, strategy: str, symbol: str, exchange: str, product: str
) -> bool:
    """Remember which strategy placed an order. Ignores duplicates.

    Takes the same lock as apply_fill. Serializing only fill application is not
    enough: a fill could find no tag, then the tag could be written and its
    (still empty) buffer drained, and only then would the fill be buffered -
    leaving it orphaned until it expired. Holding one lock across both makes
    the two orderings the only possible ones, and both are handled.
    """
    if not orderid or not strategy:
        return False
    with _fill_lock:
        return _record_order_tag_locked(orderid, user_id, strategy, symbol, exchange, product)


def _record_order_tag_locked(
    orderid: str, user_id: str, strategy: str, symbol: str, exchange: str, product: str
) -> bool:
    try:
        existing = db_session.query(StrategyOrderTag).filter_by(orderid=str(orderid)).one_or_none()
        if existing:
            return True
        db_session.add(
            StrategyOrderTag(
                orderid=str(orderid),
                user_id=user_id or "",
                strategy=strategy,
                symbol=symbol or "",
                exchange=exchange or "",
                product=product or "",
            )
        )
        db_session.commit()
    except Exception:
        db_session.rollback()
        logger.exception(f"Could not tag order {orderid} with strategy {strategy}")
        return False

    _drain_pending_fills(str(orderid))
    return True


def _drain_pending_fills(orderid: str) -> None:
    """Apply any fills that arrived before this order's tag was recorded.

    Each row is deleted only *after* its fill is booked. Deleting first would
    lose the fill permanently if booking then failed. Booking first is safe in
    the other direction too: apply_fill is idempotent on the applied-quantity
    watermark, so a row that is booked but not yet deleted is a no-op on retry.
    """
    try:
        pending = (
            db_session.query(StrategyPendingFill)
            .filter_by(orderid=orderid)
            .order_by(StrategyPendingFill.id)
            .all()
        )
        rows = [(p.id, p.filled_quantity, p.average_price, p.action) for p in pending]
    except Exception:
        db_session.rollback()
        logger.exception(f"Could not read buffered fills for order {orderid}")
        return

    for row_id, qty, price, action in rows:
        try:
            logger.info(f"Applying buffered fill for order {orderid} (arrived before its tag)")
            apply_fill(orderid, qty, price, action)
            db_session.query(StrategyPendingFill).filter_by(id=row_id).delete(
                synchronize_session=False
            )
            db_session.commit()
        except Exception:
            db_session.rollback()
            # Left in place deliberately: the row is retried on the next tag or
            # fill for this order, and pruned by age if it never applies.
            logger.exception(f"Could not apply buffered fill {row_id} for order {orderid}")


def _buffer_fill(orderid: str, filled_quantity: float, average_price: float, action: str) -> None:
    """Hold a fill until its order tag is recorded.

    Most untagged fills are not racing anything - they are ordinary orders
    placed outside any strategy, and their tag will never arrive. Those rows
    are pruned by age so the table cannot grow without bound.
    """
    if not orderid:
        return
    try:
        _prune_pending_fills()
        db_session.add(
            StrategyPendingFill(
                orderid=str(orderid),
                filled_quantity=abs(float(filled_quantity or 0)),
                average_price=float(average_price or 0),
                action=str(action or ""),
            )
        )
        db_session.commit()
        logger.debug(f"Buffered fill for untagged order {orderid}")
    except Exception:
        db_session.rollback()
        logger.exception(f"Could not buffer fill for order {orderid}")


# A tag that is going to arrive arrives within milliseconds - the buffer only
# has to survive the publish race, never a session.
_PENDING_FILL_TTL = timedelta(minutes=env_int("STRATEGY_PENDING_FILL_TTL_MIN", 10, minimum=1))


def _prune_pending_fills() -> None:
    """Drop buffered fills whose tag never arrived (ordinary untagged orders)."""
    try:
        cutoff = datetime.now() - _PENDING_FILL_TTL
        removed = (
            db_session.query(StrategyPendingFill)
            .filter(StrategyPendingFill.created_at < cutoff)
            .delete(synchronize_session=False)
        )
        if removed:
            db_session.commit()
            # The bulk delete bypasses the identity map; drop the stale entries
            # so a reused primary key does not warn on the next flush.
            db_session.expire_all()
            logger.debug(f"Strategy book: pruned {removed} unclaimed buffered fill(s)")
    except Exception:
        db_session.rollback()
        logger.exception("Could not prune pending fills")


def get_order_tag(orderid: str) -> StrategyOrderTag | None:
    try:
        return db_session.query(StrategyOrderTag).filter_by(orderid=str(orderid)).one_or_none()
    except Exception:
        db_session.rollback()
        logger.exception(f"Could not read order tag for {orderid}")
        return None


def apply_fill(
    orderid: str,
    filled_quantity: float,
    average_price: float,
    action: str,
) -> dict | None:
    """Book the unseen portion of a fill against its strategy's position.

    Returns a summary of the affected leg, or None when the order is unknown
    (not placed with a strategy tag) or the fill adds nothing new.

    Serialized: the event bus dispatches callbacks on a thread pool, so two
    updates for the same order can run concurrently. Reading the watermark,
    booking the delta and writing the watermark back must be one critical
    section or a duplicate event double-books the fill.
    """
    with _fill_lock:
        return _apply_fill_locked(orderid, filled_quantity, average_price, action)


def _apply_fill_locked(
    orderid: str,
    filled_quantity: float,
    average_price: float,
    action: str,
) -> dict | None:
    tag = get_order_tag(orderid)
    if tag is None:
        # The fill beat its own order.placed event. Buffer it; record_order_tag
        # drains the buffer as soon as the tag lands.
        _buffer_fill(orderid, filled_quantity, average_price, action)
        return None

    filled_quantity = abs(float(filled_quantity or 0))
    delta = filled_quantity - float(tag.applied_quantity or 0)
    if delta <= 0:
        return None  # already booked; duplicate or out-of-order event

    # `average_price` is cumulative over the whole order, so the incremental
    # price is the change in notional over the change in quantity. Booking the
    # delta at the cumulative average would misprice partials filled at
    # different levels.
    cumulative_notional = filled_quantity * float(average_price or 0)
    incremental_notional = cumulative_notional - float(tag.applied_notional or 0)
    price = incremental_notional / delta if delta else float(average_price or 0)
    signed = delta if str(action).upper() == "BUY" else -delta
    today = _session_date()

    try:
        leg = (
            db_session.query(StrategyPosition)
            .filter_by(
                user_id=tag.user_id,
                strategy=tag.strategy,
                symbol=tag.symbol,
                exchange=tag.exchange,
                product=tag.product,
            )
            .one_or_none()
        )
        if leg is None:
            leg = StrategyPosition(
                user_id=tag.user_id,
                strategy=tag.strategy,
                symbol=tag.symbol,
                exchange=tag.exchange,
                product=tag.product,
                trade_date=today,
            )
            db_session.add(leg)

        if leg.trade_date != today:
            leg.today_realized_pnl = 0.0
            leg.trade_date = today

        qty = float(leg.quantity or 0)
        avg = float(leg.average_price or 0)

        if qty == 0 or (qty > 0) == (signed > 0):
            total = abs(qty) + abs(signed)
            leg.average_price = ((avg * abs(qty)) + (price * abs(signed))) / total
            leg.quantity = qty + signed
        else:
            closing = min(abs(signed), abs(qty))
            direction = 1.0 if qty > 0 else -1.0
            realized = closing * (price - avg) * direction
            leg.realized_pnl = float(leg.realized_pnl or 0) + realized
            leg.today_realized_pnl = float(leg.today_realized_pnl or 0) + realized
            remaining = abs(signed) - closing
            leg.quantity = qty + signed
            if abs(leg.quantity) < 1e-9:
                leg.quantity = 0.0
                leg.average_price = 0.0
            elif remaining > 0:
                leg.average_price = price

        tag.applied_quantity = filled_quantity
        tag.applied_notional = cumulative_notional
        db_session.commit()
        return {
            "strategy": leg.strategy,
            "symbol": leg.symbol,
            "exchange": leg.exchange,
            "product": leg.product,
            "quantity": round(float(leg.quantity), 4),
            "average_price": round(float(leg.average_price), 4),
            "realized_pnl": round(float(leg.realized_pnl), 4),
            "today_realized_pnl": round(float(leg.today_realized_pnl), 4),
            "booked_quantity": round(delta, 4),
        }
    except Exception:
        db_session.rollback()
        logger.exception(f"Could not apply fill for order {orderid}")
        return None


def get_strategy_legs(user_id: str | None = None, strategy: str | None = None) -> list[dict]:
    """Every tracked leg, optionally narrowed to one user and/or strategy.

    Raises:
        StrategyBookUnavailable: the book is not initialized or cannot be read.
            Returning an empty list here would be reported as a P&L of zero,
            which an exit trigger cannot distinguish from a flat, healthy
            strategy - so an unknown book is raised, never rendered as zero.
    """
    if not _initialized:
        raise StrategyBookUnavailable(
            "Strategy book is not initialized; per-strategy P&L is unavailable"
        )
    # Same boundary the write path stamps, so a leg booked at 02:00 IST is not
    # read back as belonging to a different day.
    today = _session_date()
    try:
        query = db_session.query(StrategyPosition)
        if user_id:
            query = query.filter_by(user_id=user_id)
        if strategy:
            query = query.filter_by(strategy=strategy)
        return [
            {
                "strategy": r.strategy,
                "symbol": r.symbol,
                "exchange": r.exchange,
                "product": r.product,
                "quantity": float(r.quantity or 0),
                "average_price": float(r.average_price or 0),
                "realized_pnl": float(r.realized_pnl or 0),
                # Stale once the trading date rolls over. The stored value is
                # only reset by the next fill, so a strategy read early in a
                # new session would otherwise report yesterday's figure.
                "today_realized_pnl": (
                    float(r.today_realized_pnl or 0) if r.trade_date == today else 0.0
                ),
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in query.all()
        ]
    except Exception as exc:
        db_session.rollback()
        logger.exception("Could not read strategy legs")
        raise StrategyBookUnavailable("Could not read the strategy book") from exc


def list_strategies(user_id: str | None = None) -> list[str]:
    try:
        query = db_session.query(StrategyPosition.strategy).distinct()
        if user_id:
            query = query.filter(StrategyPosition.user_id == user_id)
        return sorted(r[0] for r in query.all())
    except Exception:
        db_session.rollback()
        logger.exception("Could not list strategies")
        return []


def reset_strategy(user_id: str, strategy: str) -> int:
    """Delete a strategy's legs and its order tags. Administrative helper.

    The tags carry the applied-quantity watermark, so leaving them behind
    would make the reset strategy permanently unable to re-book those orders.
    Fills from orders still in flight at reset time become untagged and are
    ignored, which is the intended clean-slate semantic.
    """
    try:
        n = (
            db_session.query(StrategyPosition)
            .filter_by(user_id=user_id, strategy=strategy)
            .delete()
        )
        db_session.query(StrategyOrderTag).filter_by(user_id=user_id, strategy=strategy).delete(
            synchronize_session=False
        )
        db_session.commit()
        return n
    except Exception:
        db_session.rollback()
        logger.exception(f"Could not reset strategy {strategy}")
        return 0
