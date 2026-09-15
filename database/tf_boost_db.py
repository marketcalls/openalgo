# database/tf_boost_db.py
"""
TF Boost Snapshot DuckDB Database Module

Fully isolated from historify.duckdb — its own file, its own schema. Stores
periodic snapshots of TradeFinder's market_pulse ranked lists (intraday_boost,
breakout_beacon, high_powered_stocks) for future backtest replay.
"""

from __future__ import annotations
import os
import time
from contextlib import contextmanager

from utils.logging import get_logger

logger = get_logger(__name__)

TF_BOOST_DB_PATH = os.getenv("TF_BOOST_DATABASE_PATH", "db/tf_boost_snapshots.duckdb")


def get_db_path() -> str:
    """Get absolute path to the DuckDB database file."""
    if os.path.isabs(TF_BOOST_DB_PATH):
        return TF_BOOST_DB_PATH
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, TF_BOOST_DB_PATH)


def ensure_db_directory():
    """Ensure the database directory exists."""
    db_path = get_db_path()
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
        logger.info(f"Created database directory: {db_dir}")


@contextmanager
def get_connection(max_retries: int = 3, retry_delay: float = 0.5):
    """Get a DuckDB connection with retry logic (mirrors database/historify_db.py)."""
    ensure_db_directory()
    db_path = get_db_path()
    conn = None
    last_error = None

    for attempt in range(max_retries):
        try:
            import duckdb

            conn = duckdb.connect(db_path)
            break
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                logger.debug(f"DuckDB connection attempt {attempt + 1} failed, retrying: {e}")
                time.sleep(retry_delay * (attempt + 1))
            else:
                logger.exception(f"Failed to connect to DuckDB after {max_retries} attempts: {e}")

    if conn is None:
        raise last_error or Exception("Failed to connect to DuckDB")

    try:
        yield conn
    finally:
        conn.close()


def init_tf_boost_database():
    """Create the tf_boost_snapshots table (idempotent). Never touches historify.duckdb."""
    with get_connection() as conn:
        conn.execute("CREATE SEQUENCE IF NOT EXISTS tf_boost_snapshots_id_seq START 1")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tf_boost_snapshots (
                id BIGINT PRIMARY KEY DEFAULT nextval('tf_boost_snapshots_id_seq'),
                snapshot_date  DATE NOT NULL,
                snapshot_time  TIMESTAMP NOT NULL,
                list_type      VARCHAR NOT NULL,
                rank           INTEGER NOT NULL,
                symbol         VARCHAR NOT NULL,
                ltp            DOUBLE,
                prev_close     DOUBLE,
                change_pct     DOUBLE,
                score          DOUBLE,
                created_at     TIMESTAMP DEFAULT current_timestamp,
                UNIQUE (snapshot_time, list_type, symbol)
            )
        """)
    logger.info("TF Boost snapshot database initialized (isolated, no historify schema touched)")


def get_boost_symbols(
    start_date: str,
    end_date: str | None = None,
    list_type: str = "intraday_boost",
    rank_as_of: str | None = None,
) -> list[str]:
    """Return the UNION of distinct symbols that appeared in `list_type` across
    the [start_date, end_date] window (inclusive, YYYY-MM-DD). This is the whole
    day's boost universe — including symbols that entered the list early and left
    before now — for point-in-time-honest backtesting. Returns [] if the table
    doesn't exist yet or has no rows for the window (never raises for the caller).

    Ordered by each symbol's BEST (lowest) rank, so callers can take the first N
    as "top N of the boost list" (the ISI backtest's Top-N cap).

    `rank_as_of` ("HH:MM" IST, e.g. "09:20") removes the whole-day hindsight in
    that ranking: only the last snapshot at or before that time on each day is
    considered, so the universe is what the list actually looked like at the
    cutoff. Symbols that had not entered the list by then are excluded entirely —
    a "top 20" chosen from a whole day's ranks is not knowable at 09:20 and made
    the backtest read better than live. On a day whose first snapshot is already
    after the cutoff (a late scraper start), that first snapshot is used instead
    of dropping the day.
    """
    end_date = end_date or start_date
    cutoff_min: int | None = None
    if rank_as_of:
        try:
            hh, mm = rank_as_of.split(":")
            cutoff_min = int(hh) * 60 + int(mm)
        except (ValueError, AttributeError):
            logger.warning(f"get_boost_symbols: bad rank_as_of {rank_as_of!r}, ignoring")
    try:
        with get_connection() as conn:
            if cutoff_min is None:
                rows = conn.execute(
                    """
                    SELECT symbol
                    FROM tf_boost_snapshots
                    WHERE snapshot_date BETWEEN ? AND ?
                      AND list_type = ?
                    GROUP BY symbol
                    ORDER BY MIN(rank), symbol
                    """,
                    [start_date, end_date, list_type],
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    WITH win AS (
                        SELECT * FROM tf_boost_snapshots
                        WHERE snapshot_date BETWEEN ? AND ?
                          AND list_type = ?
                    ),
                    cut AS (
                        SELECT snapshot_date,
                               COALESCE(
                                   MAX(snapshot_time) FILTER (
                                       WHERE snapshot_time
                                             <= snapshot_date::TIMESTAMP + (? * INTERVAL 1 MINUTE)
                                   ),
                                   MIN(snapshot_time)
                               ) AS t
                        FROM win
                        GROUP BY snapshot_date
                    )
                    SELECT w.symbol
                    FROM win w JOIN cut c ON w.snapshot_time = c.t
                    GROUP BY w.symbol
                    ORDER BY MIN(w.rank), w.symbol
                    """,
                    [start_date, end_date, list_type, cutoff_min],
                ).fetchall()
        return [r[0] for r in rows]
    except Exception as e:
        logger.warning(f"get_boost_symbols({start_date}..{end_date}, {list_type}): {e}")
        return []


def get_boost_rank_timeline(
    start_date: str,
    end_date: str | None = None,
    list_type: str = "intraday_boost",
) -> dict[str, dict[str, list[list[int]]]]:
    """Return every symbol's rank over time: {symbol: {day: [[minute_of_day, rank], ...]}},
    each day's pairs sorted by time. Backs the ISI backtest's "top N at signal time"
    gate — a signal is tradable only if its symbol was inside the top N at the last
    snapshot before that bar, which is what the live list would have shown.

    Minute-of-day (not a timestamp) because the consumer compares against IST bar
    times it already derives that way. Returns {} on any failure, like
    get_boost_symbols — the caller then falls back to a fixed universe.
    """
    end_date = end_date or start_date
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT symbol,
                       strftime(snapshot_date, '%Y-%m-%d') AS day,
                       hour(snapshot_time) * 60 + minute(snapshot_time) AS min_of_day,
                       rank
                FROM tf_boost_snapshots
                WHERE snapshot_date BETWEEN ? AND ?
                  AND list_type = ?
                ORDER BY symbol, snapshot_time
                """,
                [start_date, end_date, list_type],
            ).fetchall()
    except Exception as e:
        logger.warning(f"get_boost_rank_timeline({start_date}..{end_date}, {list_type}): {e}")
        return {}

    timeline: dict[str, dict[str, list[list[int]]]] = {}
    for symbol, day, min_of_day, rank in rows:
        timeline.setdefault(symbol, {}).setdefault(day, []).append([int(min_of_day), int(rank)])
    return timeline


def get_boost_price_timeline(
    start_date: str,
    end_date: str | None = None,
    list_type: str = "intraday_boost",
) -> dict[str, dict[str, list[list[float]]]]:
    """Return every symbol's ltp over time: {symbol: {day: [[minute_of_day, ltp], ...]}},
    each day's pairs sorted by time. A sibling to get_boost_rank_timeline rather
    than an extension of it -- that function backs the ISI backtest's top-N gate
    on an exact 2-tuple [minute, rank] shape, so it is left untouched. This one
    exists purely to feed intraday consolidation/breakout detection (TradeFinder
    panel), which needs price, not rank. Returns {} on any failure, matching the
    other query functions here.
    """
    end_date = end_date or start_date
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT symbol,
                       strftime(snapshot_date, '%Y-%m-%d') AS day,
                       hour(snapshot_time) * 60 + minute(snapshot_time) AS min_of_day,
                       ltp
                FROM tf_boost_snapshots
                WHERE snapshot_date BETWEEN ? AND ?
                  AND list_type = ?
                ORDER BY symbol, snapshot_time
                """,
                [start_date, end_date, list_type],
            ).fetchall()
    except Exception as e:
        logger.warning(f"get_boost_price_timeline({start_date}..{end_date}, {list_type}): {e}")
        return {}

    timeline: dict[str, dict[str, list[list[float]]]] = {}
    for symbol, day, min_of_day, ltp in rows:
        timeline.setdefault(symbol, {}).setdefault(day, []).append([int(min_of_day), float(ltp)])
    return timeline
