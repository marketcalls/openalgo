# database/watchlist_db.py
"""
Persistence for the charting terminal's watchlists.

The browser is the wrong place for this. A watchlist built up over months is
real work, and in localStorage it dies with a cache clear, does not follow the
user to a second device, and cannot be read by anything server-side. OpenAlgo
allows five concurrent sessions for its single user, so the list lives here and
every device sees the same one.

Mirrors database/scalping_db.py:
- SQLite via NullPool (one connection per op, closed immediately)
- scoped_session registered in utils/db_sessions.py for FD hygiene

Rows are scoped by ``user_id`` -- the session username, the same identity
blueprints/scalping.py uses. OpenAlgo is single-user per deployment, so this is
about keeping the schema honest rather than isolating tenants.
"""

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, scoped_session, sessionmaker

from database.engine_factory import create_db_engine
from utils.logging import get_logger

logger = get_logger(__name__)

# Canonical engine factory enforces the project-wide pooling policy
# (SQLite -> NullPool with check_same_thread=False) for FD hygiene.
engine = create_db_engine()

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

#: A list is a human-curated thing, not a data dump. The cap is what keeps a
#: runaway import from turning one poll into a thousand-symbol broker request.
MAX_ITEMS_PER_LIST = 250

#: Enough to organise by sector, strategy and expiry several times over.
MAX_LISTS_PER_USER = 50


class Watchlist(Base):
    """One named list of instruments."""

    __tablename__ = "watchlists"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(80), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    #: Display order in the list picker. Sparse and rewritten on reorder.
    position = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # delete-orphan so removing a list takes its rows with it in one flush
    # rather than leaving them for a FK cascade the SQLite file may not enforce.
    items = relationship(
        "WatchlistItem",
        back_populates="watchlist",
        cascade="all, delete-orphan",
        order_by="WatchlistItem.position",
    )

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_watchlist_user_name"),)


class WatchlistItem(Base):
    """One instrument inside a list."""

    __tablename__ = "watchlist_items"

    id = Column(Integer, primary_key=True)
    watchlist_id = Column(
        Integer, ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol = Column(String(64), nullable=False)
    exchange = Column(String(16), nullable=False)
    position = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())

    watchlist = relationship("Watchlist", back_populates="items")

    # The same instrument twice in one list is always a mistake, and the poll
    # would fetch it twice. Enforced here rather than in the blueprint so an
    # import cannot route around it.
    __table_args__ = (
        UniqueConstraint("watchlist_id", "symbol", "exchange", name="uq_watchlist_item"),
    )


def init_db():
    """Create the watchlist tables."""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Watchlist DB", logger)


def _serialize(watchlist: Watchlist) -> dict:
    """One list and its instruments, in the shape the terminal consumes."""
    return {
        "id": watchlist.id,
        "name": watchlist.name,
        "position": watchlist.position,
        "items": [
            {
                "id": item.id,
                "symbol": item.symbol,
                "exchange": item.exchange,
                "position": item.position,
            }
            for item in watchlist.items
        ],
    }


def get_watchlists(user_id: str) -> list[dict]:
    """Every list for a user, ordered, each with its instruments."""
    try:
        rows = (
            db_session.query(Watchlist)
            .filter_by(user_id=user_id)
            .order_by(Watchlist.position, Watchlist.id)
            .all()
        )
        return [_serialize(row) for row in rows]
    except Exception:
        logger.exception("Could not read watchlists for %s", user_id)
        db_session.rollback()
        return []


def create_watchlist(user_id: str, name: str, items: list[dict] | None = None) -> dict | None:
    """Add a list, optionally pre-filled.

    ``items`` carries the duplicate case for both of this function's callers:
    "make a copy" of an existing list, and importing one from a file. Returns
    None when the name is taken -- the caller reports that as a 409 rather than
    silently making a second list with the same name.
    """
    name = (name or "").strip()
    if not name:
        return None

    try:
        existing = db_session.query(Watchlist).filter_by(user_id=user_id, name=name).first()
        if existing:
            return None

        count = db_session.query(Watchlist).filter_by(user_id=user_id).count()
        if count >= MAX_LISTS_PER_USER:
            logger.warning("Watchlist cap reached for %s (%d lists)", user_id, count)
            return None

        watchlist = Watchlist(user_id=user_id, name=name, position=count)
        db_session.add(watchlist)
        db_session.flush()  # assign the id the items need

        for position, item in enumerate((items or [])[:MAX_ITEMS_PER_LIST]):
            symbol = (item.get("symbol") or "").strip().upper()
            exchange = (item.get("exchange") or "").strip().upper()
            if symbol and exchange:
                db_session.add(
                    WatchlistItem(
                        watchlist_id=watchlist.id,
                        symbol=symbol,
                        exchange=exchange,
                        position=position,
                    )
                )

        db_session.commit()
        return _serialize(watchlist)
    except Exception:
        logger.exception("Could not create watchlist %s for %s", name, user_id)
        db_session.rollback()
        return None


def rename_watchlist(user_id: str, watchlist_id: int, name: str) -> bool:
    """Rename a list. False when it is missing or the name is already used."""
    name = (name or "").strip()
    if not name:
        return False

    try:
        watchlist = db_session.query(Watchlist).filter_by(id=watchlist_id, user_id=user_id).first()
        if not watchlist:
            return False

        clash = (
            db_session.query(Watchlist)
            .filter(
                Watchlist.user_id == user_id,
                Watchlist.name == name,
                Watchlist.id != watchlist_id,
            )
            .first()
        )
        if clash:
            return False

        watchlist.name = name
        db_session.commit()
        return True
    except Exception:
        logger.exception("Could not rename watchlist %s", watchlist_id)
        db_session.rollback()
        return False


def delete_watchlist(user_id: str, watchlist_id: int) -> bool:
    """Remove a list and everything in it."""
    try:
        watchlist = db_session.query(Watchlist).filter_by(id=watchlist_id, user_id=user_id).first()
        if not watchlist:
            return False
        db_session.delete(watchlist)
        db_session.commit()
        return True
    except Exception:
        logger.exception("Could not delete watchlist %s", watchlist_id)
        db_session.rollback()
        return False


def clear_watchlist(user_id: str, watchlist_id: int) -> bool:
    """Empty a list without removing the list itself."""
    try:
        watchlist = db_session.query(Watchlist).filter_by(id=watchlist_id, user_id=user_id).first()
        if not watchlist:
            return False
        watchlist.items.clear()
        db_session.commit()
        return True
    except Exception:
        logger.exception("Could not clear watchlist %s", watchlist_id)
        db_session.rollback()
        return False


def add_item(user_id: str, watchlist_id: int, symbol: str, exchange: str) -> dict | None:
    """Append an instrument. Returns the existing row if it is already there.

    Adding a duplicate is a no-op rather than an error: the user's intent
    ("I want this in the list") is already satisfied, and reporting a failure
    for it would be noise.
    """
    symbol = (symbol or "").strip().upper()
    exchange = (exchange or "").strip().upper()
    if not symbol or not exchange:
        return None

    try:
        watchlist = db_session.query(Watchlist).filter_by(id=watchlist_id, user_id=user_id).first()
        if not watchlist:
            return None

        for item in watchlist.items:
            if item.symbol == symbol and item.exchange == exchange:
                return {
                    "id": item.id,
                    "symbol": item.symbol,
                    "exchange": item.exchange,
                    "position": item.position,
                }

        if len(watchlist.items) >= MAX_ITEMS_PER_LIST:
            logger.warning("Watchlist %s is full (%d items)", watchlist_id, MAX_ITEMS_PER_LIST)
            return None

        # max()+1 rather than len(): positions are rewritten on reorder and a
        # deletion leaves a gap, so the count is not the next free slot.
        next_position = max((item.position for item in watchlist.items), default=-1) + 1
        item = WatchlistItem(
            watchlist_id=watchlist.id, symbol=symbol, exchange=exchange, position=next_position
        )
        db_session.add(item)
        db_session.commit()
        return {
            "id": item.id,
            "symbol": item.symbol,
            "exchange": item.exchange,
            "position": item.position,
        }
    except Exception:
        logger.exception("Could not add %s:%s to watchlist %s", exchange, symbol, watchlist_id)
        db_session.rollback()
        return None


def remove_item(user_id: str, watchlist_id: int, item_id: int) -> bool:
    """Remove one instrument from a list."""
    try:
        item = (
            db_session.query(WatchlistItem)
            .join(Watchlist, WatchlistItem.watchlist_id == Watchlist.id)
            .filter(
                WatchlistItem.id == item_id,
                WatchlistItem.watchlist_id == watchlist_id,
                Watchlist.user_id == user_id,
            )
            .first()
        )
        if not item:
            return False
        db_session.delete(item)
        db_session.commit()
        return True
    except Exception:
        logger.exception("Could not remove item %s from watchlist %s", item_id, watchlist_id)
        db_session.rollback()
        return False


def reorder_items(user_id: str, watchlist_id: int, item_ids: list[int]) -> bool:
    """Rewrite the display order from a full list of item ids.

    Ids that do not belong to this list are ignored, and any item the caller
    omitted keeps a stable position after the ones it did send, so a reorder
    computed against a stale view cannot drop rows out of the list.
    """
    try:
        watchlist = db_session.query(Watchlist).filter_by(id=watchlist_id, user_id=user_id).first()
        if not watchlist:
            return False

        by_id = {item.id: item for item in watchlist.items}
        position = 0
        for item_id in item_ids:
            item = by_id.pop(item_id, None)
            if item is not None:
                item.position = position
                position += 1
        for item in by_id.values():
            item.position = position
            position += 1

        db_session.commit()
        return True
    except Exception:
        logger.exception("Could not reorder watchlist %s", watchlist_id)
        db_session.rollback()
        return False


def ensure_watchlist_tables_exists():
    """Alias matching the app.py startup pattern."""
    init_db()
