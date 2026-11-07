# database/pnl_db.py
"""Persistence for the multi-day P&L feature.

Own SQLite file (``db/tradebook.db``), isolated from the main DB the way
``sandbox_db.py`` is: an indefinitely growing store of real trade history with
its own backup and retention needs. Engine and session setup mirror
``sandbox_db.py`` (NullPool, check_same_thread=False).

Two tables:
- ``tradebook_fills``: the captured or imported per-fill ledger. It is the only
  persisted state; realized P&L is derived from these rows on every read by
  ``utils/pnl_fifo.py``, the way the intraday PnL Tracker derives its numbers.
- ``pnl_capture_runs``: an audit log of the daily capture job, so a failed run
  shows up as a recorded failure rather than a silent gap in the ledger.

Dedup key: the broker's own per-fill ``tradeid`` plus the trade date when
present, otherwise a composite of the fill's fields, so re-running the capture
job or importing an overlapping CSV never double-counts a fill.
"""

import hashlib
import os
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import func

from database.strategy_book_db import get_order_tag
from utils.broker_timestamp import parse_broker_timestamp
from utils.logging import get_logger

logger = get_logger(__name__)

load_dotenv()

# Own store, own env var, like sandbox_db.py.
TRADEBOOK_DATABASE_URL = os.getenv("TRADEBOOK_DATABASE_URL", "sqlite:///db/tradebook.db")

if TRADEBOOK_DATABASE_URL and "sqlite" in TRADEBOOK_DATABASE_URL:
    engine = create_engine(
        TRADEBOOK_DATABASE_URL, poolclass=NullPool, connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(TRADEBOOK_DATABASE_URL, pool_size=20, max_overflow=40, pool_timeout=10)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


def _trade_date(timestamp):
    """YYYY-MM-DD of a parsed trade timestamp, or None when it has no date."""
    try:
        return timestamp.strftime("%Y-%m-%d")
    except AttributeError:
        return None


def exchange_family(exchange):
    """Collapse an exchange code to the numbering domain its trade ids come
    from: cash and derivatives of one exchange share it (NSE/NFO/CDS/NCO ->
    "NSE", BSE/BFO/BCD -> "BSE"). A Console F&O CSV labels a NIFTY option NSE
    while the capture job stores NFO, and both must produce one key.
    """
    code = (exchange or "").strip().upper()
    return _EXCHANGE_FAMILY_MAP.get(code, code or "?")


def make_dedup_key(tradeid, orderid, symbol, exchange, action, quantity, average_price, timestamp):
    """Stable idempotency key for one fill.

    A ``tradeid`` is only unique within one exchange on one trading day -
    Zerodha re-uses the same numbers on later days (2026-10-01: ids 1287080/1
    and 401066-8 each belonged to two different fills months apart). So the
    key is date + exchange family + tradeid, never the bare id: the bare id
    made a CSV import abort on the clash and let the capture job silently
    skip a real fill whose id matched an older one.

    Without a tradeid (pre-fix capture, or a CSV export that never included
    it), fall back to a composite of every field that would differ between
    two distinct fills of the same order - two legitimate fills can share
    orderid, symbol, action, and even price, but not all of those plus
    quantity and timestamp at once in practice. Hashed only to keep the
    indexed column short and fixed-width.
    """
    tradeid = (tradeid or "").strip()
    if tradeid:
        trade_date = _trade_date(timestamp)
        if trade_date:
            return f"tid:{trade_date}:{exchange_family(exchange)}:{tradeid}"
        # No date to scope by: the legacy bare key is the best we can do.
        return f"tid:{tradeid}"

    # Numeric/timestamp fields are normalized before hashing so the same
    # fill produces the same key regardless of caller: the daily capture job
    # hands quantity/price through however the broker mapping typed them
    # (int, float, or occasionally string), while a CSV import parses its
    # own column types independently. int(100), float(100.0), and "100"
    # must all fold to one canonical string, or a CSV backfill of a
    # tradeid-less trade the capture job already stored would double-count
    # instead of deduping against it.
    try:
        quantity_norm = f"{float(quantity):.4f}"
    except (TypeError, ValueError):
        quantity_norm = str(quantity)
    try:
        price_norm = f"{float(average_price):.4f}"
    except (TypeError, ValueError):
        price_norm = str(average_price)

    raw = "|".join(
        str(part)
        for part in (orderid, symbol, exchange, action, quantity_norm, price_norm, timestamp)
    )
    return "composite:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()


def parse_trade_timestamp(value, fallback=None):
    """Best-effort parse of a tradebook/CSV timestamp into a naive datetime for
    storage; shared by the capture job and the CSV import path."""
    return parse_broker_timestamp(value, fallback)


# Segment of a row, matching the segment picker of broker consoles. "mutual_fund"
# is accepted but no exchange maps to it yet.
VALID_SEGMENTS = ("equity", "fno", "currency", "commodity", "mutual_fund")

# Built from utils.constants's own exchange constants rather than hand-typed
# strings, so this can never silently drift from the canonical exchange
# list if that module ever changes a code.
try:
    from utils.constants import (
        EXCHANGE_BCD,
        EXCHANGE_BFO,
        EXCHANGE_BSE,
        EXCHANGE_CDS,
        EXCHANGE_MCX,
        EXCHANGE_NCDEX,
        EXCHANGE_NCO,
        EXCHANGE_NFO,
        EXCHANGE_NSE,
    )

    _EXCHANGE_SEGMENT_MAP = {
        EXCHANGE_NSE: "equity",
        EXCHANGE_BSE: "equity",
        EXCHANGE_NFO: "fno",
        EXCHANGE_BFO: "fno",
        EXCHANGE_CDS: "currency",
        EXCHANGE_BCD: "currency",
        EXCHANGE_MCX: "commodity",
        EXCHANGE_NCDEX: "commodity",
        EXCHANGE_NCO: "commodity",  # "NSE Commodities (futures + options)" - commodity segment despite the name
    }
    # Zerodha Console's tradebook export labels F&O rows with the underlying's
    # exchange (NSE for NIFTY, BSE for SENSEX) rather than the derivatives
    # exchange the broker feed reports - see normalize_fno_exchange().
    _CONSOLE_FNO_EXCHANGE_MAP = {EXCHANGE_NSE: EXCHANGE_NFO, EXCHANGE_BSE: EXCHANGE_BFO}
    # See exchange_family(): which exchange's trade numbering a code belongs to.
    _EXCHANGE_FAMILY_MAP = {
        EXCHANGE_NSE: "NSE",
        EXCHANGE_NFO: "NSE",
        EXCHANGE_CDS: "NSE",
        EXCHANGE_NCO: "NSE",
        EXCHANGE_BSE: "BSE",
        EXCHANGE_BFO: "BSE",
        EXCHANGE_BCD: "BSE",
    }
except ImportError:
    # utils.constants is part of this same codebase and always importable in
    # practice; guarded only so a database-layer module never hard-fails
    # over an import from an unrelated package.
    logger.exception("utils.constants unavailable - segment derivation disabled")
    _EXCHANGE_SEGMENT_MAP = {}
    _CONSOLE_FNO_EXCHANGE_MAP = {}
    _EXCHANGE_FAMILY_MAP = {}


def normalize_fno_exchange(segment, exchange):
    """Exchange to store for a row: NFO/BFO for an F&O row that a Zerodha
    Console CSV labelled NSE/BSE, otherwise the exchange unchanged.

    The daily capture job stores the broker feed's own NFO/BFO, so without
    this an imported and a captured F&O row disagree on exchange and the
    Scrip-wise report shows NSE/BSE beside NFO/BFO for the same segment.
    Segment (not exchange) is what filters a report, so this changes only
    the displayed/stored exchange, never which rows a segment view includes.

    Store-time only: make_dedup_key must still be fed the raw CSV exchange,
    or a re-upload of an already-imported CSV would stop deduping against
    the existing rows that were hashed with NSE/BSE.
    """
    if segment != "fno":
        return exchange
    return _CONSOLE_FNO_EXCHANGE_MAP.get((exchange or "").strip(), exchange)


def derive_segment(exchange):
    """Map a raw exchange code to one of VALID_SEGMENTS, or None when it
    doesn't fit any of them (index/quote-only symbols like NSE_INDEX, or
    CRYPTO - not a real segment in this scheme and not traded by either
    broker this feature currently ships for).
    """
    return _EXCHANGE_SEGMENT_MAP.get((exchange or "").strip())


class TradebookFill(Base):
    """One captured or imported fill; realized P&L is derived from these rows."""

    __tablename__ = "tradebook_fills"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Idempotency key, see make_dedup_key().
    dedup_key = Column(String(80), unique=True, nullable=False, index=True)

    tradeid = Column(String(50), nullable=True, index=True)
    orderid = Column(String(50), nullable=True, index=True)

    symbol = Column(String(50), nullable=False, index=True)
    exchange = Column(String(20), nullable=False, index=True)
    product = Column(String(20), nullable=True)
    action = Column(String(10), nullable=False)  # BUY or SELL

    # One of VALID_SEGMENTS, derived from exchange at write time via
    # derive_segment(). Nullable: exchange codes that map to none of the
    # segments (index/quote symbols, crypto) are left unset.
    segment = Column(String(20), nullable=True, index=True)

    # Strategy that placed the trade, joined at write time from the order tag in
    # database/strategy_book_db.py (nullable: CSV history has no order id to
    # join, and tags expire). Also settable via
    # PATCH /api/v1/pnl/trades/<id>/strategy.
    strategy = Column(String(120), nullable=True, index=True)

    quantity = Column(Float, nullable=False)
    average_price = Column(Float, nullable=False)
    trade_value = Column(Float, nullable=True)

    # The fill's own execution time, not this row's insert time.
    trade_timestamp = Column(DateTime, nullable=False, index=True)

    # "capture" (daily automated pull from services/tradebook_service.py) or
    # "import" (CSV upload, backfilling history predating the capture job).
    source = Column(String(20), nullable=False, default="capture")

    created_at = Column(DateTime, nullable=False, default=func.now())

    __table_args__ = (
        Index("idx_tradebook_fills_symbol_exchange_ts", "symbol", "exchange", "trade_timestamp"),
        Index("idx_tradebook_fills_ts", "trade_timestamp"),
    )


class PnlCaptureRun(Base):
    """Audit log for the daily capture job - one row per attempted run, so a
    silent failure (broker API down, auth expired) shows up as a gap instead
    of just missing trades nobody notices until a P&L report looks wrong.
    Mirrors the spirit of Historify's download_jobs/job_items bookkeeping.
    """

    __tablename__ = "pnl_capture_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_date = Column(String(10), nullable=False, index=True)  # YYYY-MM-DD, IST trading date
    status = Column(String(20), nullable=False)  # success, failed, partial, skipped
    trades_fetched = Column(Integer, nullable=False, default=0)
    trades_new = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False, default=func.now())
    finished_at = Column(DateTime, nullable=True)


def lookup_order_strategy(orderid):
    """Strategy name tagged on this order in the strategy book, or None (no
    order id, no tag, or the tag expired)."""
    if not orderid:
        return None
    tag = get_order_tag(orderid)
    return tag.strategy if tag else None


def fill_exists(session, dedup_key):
    """True when this fill is already stored."""
    return session.query(TradebookFill.id).filter_by(dedup_key=dedup_key).first() is not None


def init_db():
    """Create the tradebook tables. Idempotent."""
    from database.db_init_helper import _ensure_sqlite_dir, init_db_with_logging

    _ensure_sqlite_dir(engine)
    init_db_with_logging(Base, engine, "Tradebook DB", logger)
