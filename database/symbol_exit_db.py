# database/symbol_exit_db.py
"""
Persistence for the symbol exit watcher.

The charting terminal / position calculator attaches optional risk legs
(``stoploss`` / ``target`` / ``trailing_stoploss``) to a ``placeorder``
request. Those are advisory on the wire, so this module records them as an
"exit watch" against the placed entry order, keyed one-per-entry-order. The
symbol exit monitor (``services/symbol_exit_monitor_service.py``) subscribes
to the symbol's live feed and squares the position off when the market reaches
either leg — for every trade type (intraday MIS, overnight, GTT) in both
sandbox (analyze) and live mode.

Mirrors database/scalping_db.py:
- SQLite via NullPool (one connection per op, closed immediately)
- scoped_session registered in app.py teardown_appcontext for FD hygiene
"""

import logging

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.sql import func

from database.engine_factory import create_db_engine

logger = logging.getLogger(__name__)

engine = create_db_engine()

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class SymbolExitWatch(Base):
    """One exit-watch per entry order the calculator placed with an SL/target."""

    __tablename__ = "symbol_exit_watch"
    # One watch per entry order so re-entries on the same leg sit side by side
    # instead of overwriting each other's stop/target.
    __table_args__ = (
        UniqueConstraint("order_id", "mode", name="uq_symbol_exit_watch_order"),
    )

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(60), nullable=False)
    exchange = Column(String(10), nullable=False)  # NSE | BSE | NFO | ...
    product = Column(String(10), nullable=False)  # MIS | NRML | CNC
    side = Column(String(4), nullable=False, default="BUY")  # BUY | SELL

    # Trading mode the entry was placed in: "analyze" (sandbox) or "live".
    # Segregates sandbox watches from live ones so the monitor never exits
    # across modes.
    mode = Column(String(10), nullable=False, default="analyze")

    # Entry order this watch guards; the square-off replaces this position.
    order_id = Column(String(64), nullable=False)
    strategy = Column(String(60), nullable=False, default="")

    entry_price = Column(Float, nullable=False, default=0.0)  # 0 = market fill (seeded from first tick)
    quantity = Column(Integer, nullable=False, default=0)

    stop_loss = Column(Float, nullable=True)  # configured stop price
    target = Column(Float, nullable=True)  # take-profit price
    trailing_step = Column(Float, nullable=True)  # price distance the stop trails behind the peak

    current_stop = Column(Float, nullable=True)  # live stop (may have trailed)
    highest_price = Column(Float, nullable=True)  # peak LTP seen since entry (long watch)
    lowest_price = Column(Float, nullable=True)  # trough LTP seen since entry (short watch)

    # active | executed | cancelled
    status = Column(String(10), nullable=False, default="active", index=True)
    exit_reason = Column(String(20), nullable=True)  # sl | target | flat
    exit_price = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    executed_at = Column(DateTime(timezone=True), nullable=True)


def init_db():
    """Create the symbol-exit tables if they don't exist."""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Symbol Exit DB", logger)


def _row_to_dict(row: SymbolExitWatch) -> dict:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "exchange": row.exchange,
        "product": row.product,
        "side": row.side,
        "mode": row.mode,
        "order_id": row.order_id,
        "strategy": row.strategy,
        "entry_price": row.entry_price,
        "quantity": row.quantity,
        "stop_loss": row.stop_loss,
        "target": row.target,
        "trailing_step": row.trailing_step,
        "current_stop": row.current_stop,
        "highest_price": row.highest_price,
        "lowest_price": row.lowest_price,
        "status": row.status,
        "exit_reason": row.exit_reason,
        "exit_price": row.exit_price,
    }


def create_exit_watch(data: dict) -> dict:
    """Persist an exit watch for a placed entry order.

    Returns the stored row; idempotent on ``(order_id, mode)`` so a retried
    placement or a duplicate event never stacks two watches for one order.
    """
    order_id = data.get("order_id", "")
    mode = data.get("mode", "analyze")
    existing = (
        db_session.query(SymbolExitWatch)
        .filter_by(order_id=order_id, mode=mode)
        .first()
    )
    if existing is not None:
        return _row_to_dict(existing)

    row = SymbolExitWatch(
        symbol=data["symbol"],
        exchange=data["exchange"],
        product=data["product"],
        side=data["side"],
        mode=mode,
        order_id=data["order_id"],
        strategy=data.get("strategy", ""),
        entry_price=float(data.get("entry_price") or 0),
        quantity=int(data.get("quantity") or 0),
        stop_loss=_as_float_or_none(data.get("stop_loss")),
        target=_as_float_or_none(data.get("target")),
        trailing_step=_as_float_or_none(data.get("trailing_step")),
        current_stop=_as_float_or_none(data.get("current_stop")),
        highest_price=_as_float_or_none(data.get("highest_price")),
        lowest_price=_as_float_or_none(data.get("lowest_price")),
    )
    db_session.add(row)
    db_session.flush()
    result = _row_to_dict(row)
    db_session.commit()
    return result


def get_active_watches(mode: str | None = None) -> list[dict]:
    """All active exit watches, optionally scoped to one mode."""
    q = db_session.query(SymbolExitWatch).filter(SymbolExitWatch.status == "active")
    if mode is not None:
        q = q.filter(SymbolExitWatch.mode == mode)
    rows = q.order_by(SymbolExitWatch.id.asc()).all()
    return [_row_to_dict(r) for r in rows]


def get_watch_by_id(watch_id: int) -> dict | None:
    row = db_session.query(SymbolExitWatch).filter_by(id=watch_id).first()
    return _row_to_dict(row) if row is not None else None


def update_watch_tick(watch_id: int, current_stop, highest_price, lowest_price) -> None:
    row = db_session.query(SymbolExitWatch).filter_by(id=watch_id).first()
    if row is None:
        return
    if current_stop is not None:
        row.current_stop = _as_float_or_none(current_stop)
    if highest_price is not None:
        row.highest_price = _as_float_or_none(highest_price)
    if lowest_price is not None:
        row.lowest_price = _as_float_or_none(lowest_price)
    db_session.commit()


def set_watch_entry_price(watch_id: int, entry_price: float) -> None:
    row = db_session.query(SymbolExitWatch).filter_by(id=watch_id).first()
    if row is None:
        return
    row.entry_price = float(entry_price)
    db_session.commit()


def mark_watch_executed(watch_id: int, reason: str, exit_price: float | None = None) -> bool:
    row = db_session.query(SymbolExitWatch).filter_by(id=watch_id).first()
    if row is None:
        return False
    row.status = "executed"
    row.exit_reason = reason
    row.exit_price = _as_float_or_none(exit_price)
    row.executed_at = func.now()
    db_session.commit()
    return True


def cancel_watch(order_id: str, mode: str) -> bool:
    row = (
        db_session.query(SymbolExitWatch)
        .filter_by(order_id=order_id, mode=mode)
        .first()
    )
    if row is None:
        return False
    row.status = "cancelled"
    db_session.commit()
    return True


def _as_float_or_none(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
