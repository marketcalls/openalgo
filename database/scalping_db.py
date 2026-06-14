# database/scalping_db.py
"""
Persistence for the /scalping terminal's stop-loss / trailing-SL configuration.

The trailing-SL engine itself runs in the browser (Phase 2). This module only
persists each active leg's SL config so it survives a page reload — keyed by
(symbol, exchange, product). Mirrors database/flow_db.py:
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

# Canonical engine factory enforces the project-wide pooling policy
# (SQLite -> NullPool with check_same_thread=False) for FD hygiene.
engine = create_db_engine()

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class ScalpingSLState(Base):
    """One row per active leg whose stop-loss is being tracked by the terminal."""

    __tablename__ = "scalping_sl_state"
    # Mode is part of the key so the SAME leg can hold an independent SL in analyze
    # (sandbox) and live mode without one overwriting/blocking the other.
    __table_args__ = (
        UniqueConstraint("symbol", "exchange", "product", "mode", name="uq_scalping_sl_leg"),
    )

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(60), nullable=False)
    exchange = Column(String(10), nullable=False)  # NFO | BFO
    product = Column(String(10), nullable=False)  # MIS | NRML
    side = Column(String(4), nullable=False, default="BUY")  # BUY | SELL

    # Trading mode this SL belongs to: "analyze" (sandbox) or "live". Segregates
    # sandbox SLs from live SLs so the monitor never acts across modes.
    mode = Column(String(10), nullable=False, default="analyze")

    entry_price = Column(Float, nullable=False, default=0.0)
    quantity = Column(Integer, nullable=False, default=0)

    initial_sl = Column(Float, nullable=True)
    trailing_enabled = Column(Boolean, nullable=False, default=False)
    trailing_step = Column(Float, nullable=True)
    highest_price = Column(Float, nullable=True)  # peak LTP seen since entry (long legs)
    lowest_price = Column(Float, nullable=True)  # trough LTP seen since entry (short legs)
    current_sl = Column(Float, nullable=True)
    target = Column(Float, nullable=True)  # take-profit price (0/None = no target)

    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ScalpingTrackedSymbol(Base):
    """Instruments the scalping terminal has traded (its 'scalping list').

    Broker positions carry no OpenAlgo strategy tag, so the terminal records every
    (symbol, exchange, product) it trades here. This is how Close-All / the position
    book are scoped to the scalping strategy instead of the whole account.
    """

    __tablename__ = "scalping_tracked_symbol"
    # Mode is part of the key so analyze (sandbox) and live lists are truly
    # segregated for the same instrument leg.
    __table_args__ = (
        UniqueConstraint("symbol", "exchange", "product", "mode", name="uq_scalping_tracked"),
    )

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(60), nullable=False)
    exchange = Column(String(10), nullable=False)
    product = Column(String(10), nullable=False)
    # Trading mode the instrument was traded in: "analyze" (sandbox) or "live".
    mode = Column(String(10), nullable=False, default="analyze")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


def init_db():
    """Create the scalping tables if they don't exist."""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Scalping DB", logger)
    _migrate_add_columns()
    _migrate_mode_unique(ScalpingSLState, "scalping_sl_state")
    _migrate_mode_unique(ScalpingTrackedSymbol, "scalping_tracked_symbol")


def _migrate_mode_unique(model, table_name: str):
    """Recreate a table so its UNIQUE constraint includes `mode` (analyze/live).

    SQLite can't ALTER a constraint, so for DBs created before mode-scoping we
    recreate the table. Idempotent: skips when the unique constraint already covers
    `mode`. DATA-SAFE: the DROP, CREATE and re-INSERT all run inside a SINGLE
    transaction (SQLite DDL is transactional), so any mid-migration failure rolls
    back and leaves the original table + rows intact. Rows are also held in memory
    as a recovery fallback. Doing the DROP before CREATE inside the txn also avoids
    index/constraint name collisions.
    """
    from sqlalchemy import inspect, text
    from sqlalchemy.schema import CreateIndex, CreateTable

    try:
        inspector = inspect(engine)
        if table_name not in inspector.get_table_names():
            return
        uniques = inspector.get_unique_constraints(table_name)
        if any("mode" in (uc.get("column_names") or []) for uc in uniques):
            return  # already mode-scoped

        cols = [c["name"] for c in inspector.get_columns(table_name)]
        model_cols = {c.name for c in model.__table__.columns}
        common = [c for c in cols if c in model_cols]
        collist = ", ".join(common)
    except Exception as e:
        logger.exception(f"Error inspecting {table_name} for mode migration: {e}")
        return

    # Read all rows into memory FIRST — survives even a catastrophic failure below.
    try:
        with engine.connect() as conn:
            rows = [dict(r._mapping) for r in conn.execute(text(f"SELECT {collist} FROM {table_name}"))]
    except Exception as e:
        logger.exception(f"Error reading {table_name} before mode migration: {e}")
        return

    # Atomic recreate: DROP + CREATE (+ indexes) + INSERT in ONE transaction. On any
    # error the whole transaction rolls back and the original table is untouched.
    try:
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE {table_name}"))
            conn.execute(CreateTable(model.__table__))
            for index in model.__table__.indexes:
                conn.execute(CreateIndex(index))
            if rows:
                conn.execute(model.__table__.insert(), rows)
        logger.info(
            "Scalping DB: %s recreated with mode-scoped unique constraint (%d rows preserved)",
            table_name,
            len(rows),
        )
    except Exception as e:
        logger.exception(f"Error migrating {table_name} to mode-scoped uniqueness: {e}")
        # Recovery: ensure the table exists and the in-memory rows are restored.
        try:
            model.__table__.create(engine, checkfirst=True)
            if rows:
                with engine.begin() as conn:
                    existing = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
                    if not existing:
                        conn.execute(model.__table__.insert(), rows)
                        logger.warning("Scalping DB: %s restored %d rows after failed migration",
                                       table_name, len(rows))
        except Exception as re:
            logger.exception(f"Recovery for {table_name} failed: {re}")


def _migrate_add_columns():
    """Add columns introduced after the table's first release (idempotent)."""
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        if "scalping_sl_state" not in inspector.get_table_names():
            return
        existing = {c["name"] for c in inspector.get_columns("scalping_sl_state")}
        with engine.begin() as conn:
            if "lowest_price" not in existing:
                conn.execute(text("ALTER TABLE scalping_sl_state ADD COLUMN lowest_price FLOAT"))
                logger.info("Scalping DB: added lowest_price column")
            if "target" not in existing:
                conn.execute(text("ALTER TABLE scalping_sl_state ADD COLUMN target FLOAT"))
                logger.info("Scalping DB: added target column")
            if "mode" not in existing:
                # Existing rows default to 'analyze' (conservative: the live
                # monitor will not auto-act on pre-existing/ambiguous SLs).
                conn.execute(
                    text("ALTER TABLE scalping_sl_state ADD COLUMN mode VARCHAR(10) "
                         "NOT NULL DEFAULT 'analyze'")
                )
                logger.info("Scalping DB: added mode column to scalping_sl_state")

        if "scalping_tracked_symbol" in inspector.get_table_names():
            tracked_cols = {c["name"] for c in inspector.get_columns("scalping_tracked_symbol")}
            if "mode" not in tracked_cols:
                with engine.begin() as conn:
                    conn.execute(
                        text("ALTER TABLE scalping_tracked_symbol ADD COLUMN mode VARCHAR(10) "
                             "NOT NULL DEFAULT 'analyze'")
                    )
                logger.info("Scalping DB: added mode column to scalping_tracked_symbol")
    except Exception as e:
        logger.exception(f"Error migrating scalping columns: {e}")


def _to_dict(row: "ScalpingSLState") -> dict:
    return {
        "symbol": row.symbol,
        "exchange": row.exchange,
        "product": row.product,
        "mode": row.mode,
        "side": row.side,
        "entry_price": row.entry_price,
        "quantity": row.quantity,
        "initial_sl": row.initial_sl,
        "trailing_enabled": row.trailing_enabled,
        "trailing_step": row.trailing_step,
        "highest_price": row.highest_price,
        "lowest_price": row.lowest_price,
        "current_sl": row.current_sl,
        "target": row.target,
        "is_active": row.is_active,
    }


def upsert_sl_state(data: dict) -> dict | None:
    """Create or update the SL state for a (symbol, exchange, product, mode) leg."""
    try:
        symbol = data["symbol"]
        exchange = data["exchange"]
        product = data["product"]
    except KeyError as e:
        logger.error(f"upsert_sl_state missing key: {e}")
        return None
    mode = data.get("mode") or "analyze"

    try:
        row = (
            db_session.query(ScalpingSLState)
            .filter_by(symbol=symbol, exchange=exchange, product=product, mode=mode)
            .first()
        )
        if row is None:
            row = ScalpingSLState(symbol=symbol, exchange=exchange, product=product, mode=mode)
            db_session.add(row)

        for field in (
            "mode",
            "side",
            "entry_price",
            "quantity",
            "initial_sl",
            "trailing_enabled",
            "trailing_step",
            "highest_price",
            "lowest_price",
            "current_sl",
            "target",
            "is_active",
        ):
            if field in data and data[field] is not None:
                setattr(row, field, data[field])

        db_session.commit()
        return _to_dict(row)
    except Exception as e:
        logger.exception(f"Error upserting scalping SL state: {e}")
        db_session.rollback()
        return None


def get_active_sl_states(mode: str | None = None) -> list[dict]:
    """Return active SL states, optionally scoped to a trading mode.

    Pass mode="analyze" or "live" to segregate sandbox SLs from live SLs.
    """
    try:
        q = db_session.query(ScalpingSLState).filter_by(is_active=True)
        if mode is not None:
            q = q.filter_by(mode=mode)
        return [_to_dict(r) for r in q.all()]
    except Exception as e:
        logger.exception(f"Error fetching scalping SL states: {e}")
        db_session.rollback()
        return []


def delete_sl_state(symbol: str, exchange: str, product: str, mode: str | None = None) -> bool:
    """Remove the SL state for a leg. Scoped to `mode` when given (so clearing a
    sandbox SL never removes the live SL for the same leg, and vice-versa)."""
    try:
        q = db_session.query(ScalpingSLState).filter_by(
            symbol=symbol, exchange=exchange, product=product
        )
        if mode is not None:
            q = q.filter_by(mode=mode)
        deleted = q.delete()
        db_session.commit()
        return deleted > 0
    except Exception as e:
        logger.exception(f"Error deleting scalping SL state: {e}")
        db_session.rollback()
        return False


def track_symbol(symbol: str, exchange: str, product: str, mode: str = "analyze") -> bool:
    """Record a (symbol, exchange, product, mode) as part of the scalping list.

    The trading mode is part of the key so analyze (sandbox) and live lists are
    truly segregated — the same leg can appear independently in both. Idempotent.
    """
    try:
        exists = (
            db_session.query(ScalpingTrackedSymbol)
            .filter_by(symbol=symbol, exchange=exchange, product=product, mode=mode)
            .first()
        )
        if exists is None:
            db_session.add(
                ScalpingTrackedSymbol(
                    symbol=symbol, exchange=exchange, product=product, mode=mode
                )
            )
            db_session.commit()
        return True
    except Exception as e:
        logger.exception(f"Error tracking scalping symbol: {e}")
        db_session.rollback()
        return False


def get_tracked_symbols(mode: str | None = None) -> list[dict]:
    """Return the scalping list, optionally scoped to a trading mode."""
    try:
        q = db_session.query(ScalpingTrackedSymbol)
        if mode is not None:
            q = q.filter_by(mode=mode)
        return [
            {"symbol": r.symbol, "exchange": r.exchange, "product": r.product, "mode": r.mode}
            for r in q.all()
        ]
    except Exception as e:
        logger.exception(f"Error fetching scalping tracked symbols: {e}")
        db_session.rollback()
        return []


def clear_tracked_symbols(mode: str | None = None) -> bool:
    """Clear the scalping list, optionally only for one trading mode."""
    try:
        q = db_session.query(ScalpingTrackedSymbol)
        if mode is not None:
            q = q.filter_by(mode=mode)
        q.delete()
        db_session.commit()
        return True
    except Exception as e:
        logger.exception(f"Error clearing scalping tracked symbols: {e}")
        db_session.rollback()
        return False
