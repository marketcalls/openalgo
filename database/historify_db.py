# database/historify_db.py
"""
Historify DuckDB Database Module

High-performance columnar storage for historical market data.
Optimized for backtesting and analytical queries.
"""

import os
import duckdb
import pandas as pd
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, date
from contextlib import contextmanager
from utils.logging import get_logger
from dotenv import load_dotenv

# Initialize logger
logger = get_logger(__name__)

# Load environment variables
load_dotenv()

# Database path - in /db folder like other OpenAlgo databases
HISTORIFY_DB_PATH = os.getenv('HISTORIFY_DATABASE_PATH', 'db/historify.duckdb')


def get_db_path() -> str:
    """Get absolute path to the DuckDB database file."""
    if os.path.isabs(HISTORIFY_DB_PATH):
        return HISTORIFY_DB_PATH
    # Relative to the openalgo directory
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, HISTORIFY_DB_PATH)


def ensure_db_directory():
    """Ensure the database directory exists."""
    db_path = get_db_path()
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
        logger.info(f"Created database directory: {db_dir}")


@contextmanager
def get_connection():
    """
    Get a DuckDB connection with proper resource management.

    Usage:
        with get_connection() as conn:
            result = conn.execute("SELECT * FROM market_data").fetchdf()
    """
    ensure_db_directory()
    conn = duckdb.connect(get_db_path())
    try:
        yield conn
    finally:
        conn.close()


def init_database():
    """
    Initialize the Historify database schema.
    Creates all required tables if they don't exist.
    """
    ensure_db_directory()

    with get_connection() as conn:
        # Main OHLCV data table - unified table approach
        conn.execute("""
            CREATE TABLE IF NOT EXISTS market_data (
                symbol VARCHAR NOT NULL,
                exchange VARCHAR NOT NULL,
                interval VARCHAR NOT NULL,
                timestamp BIGINT NOT NULL,
                open DOUBLE NOT NULL,
                high DOUBLE NOT NULL,
                low DOUBLE NOT NULL,
                close DOUBLE NOT NULL,
                volume BIGINT NOT NULL,
                oi BIGINT DEFAULT 0,
                created_at TIMESTAMP DEFAULT current_timestamp,
                PRIMARY KEY (symbol, exchange, interval, timestamp)
            )
        """)

        # Watchlist table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY,
                symbol VARCHAR NOT NULL,
                exchange VARCHAR NOT NULL,
                display_name VARCHAR,
                added_at TIMESTAMP DEFAULT current_timestamp,
                UNIQUE (symbol, exchange)
            )
        """)

        # Data catalog for tracking downloaded data ranges
        conn.execute("""
            CREATE TABLE IF NOT EXISTS data_catalog (
                id INTEGER PRIMARY KEY,
                symbol VARCHAR NOT NULL,
                exchange VARCHAR NOT NULL,
                interval VARCHAR NOT NULL,
                first_timestamp BIGINT,
                last_timestamp BIGINT,
                record_count BIGINT DEFAULT 0,
                last_download_at TIMESTAMP,
                UNIQUE (symbol, exchange, interval)
            )
        """)

        # Create indexes for common query patterns
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_market_data_timestamp
            ON market_data (timestamp)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_market_data_exchange_time
            ON market_data (exchange, timestamp)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_market_data_interval_time
            ON market_data (interval, timestamp)
        """)

        logger.info("Historify database initialized successfully")


# =============================================================================
# Watchlist Operations
# =============================================================================

def get_watchlist() -> List[Dict[str, Any]]:
    """Get all symbols in the watchlist."""
    with get_connection() as conn:
        result = conn.execute("""
            SELECT id, symbol, exchange, display_name, added_at
            FROM watchlist
            ORDER BY added_at DESC
        """).fetchdf()

        if result.empty:
            return []

        return result.to_dict('records')


def add_to_watchlist(symbol: str, exchange: str, display_name: str = None) -> Tuple[bool, str]:
    """
    Add a symbol to the watchlist.

    Returns:
        Tuple of (success, message)
    """
    try:
        with get_connection() as conn:
            conn.execute("""
                INSERT INTO watchlist (symbol, exchange, display_name)
                VALUES (?, ?, ?)
                ON CONFLICT (symbol, exchange) DO NOTHING
            """, [symbol.upper(), exchange.upper(), display_name])

        logger.info(f"Added {symbol}:{exchange} to watchlist")
        return True, f"Added {symbol} to watchlist"
    except Exception as e:
        logger.error(f"Error adding to watchlist: {e}")
        return False, str(e)


def remove_from_watchlist(symbol: str, exchange: str) -> Tuple[bool, str]:
    """
    Remove a symbol from the watchlist.

    Returns:
        Tuple of (success, message)
    """
    try:
        with get_connection() as conn:
            conn.execute("""
                DELETE FROM watchlist
                WHERE symbol = ? AND exchange = ?
            """, [symbol.upper(), exchange.upper()])

        logger.info(f"Removed {symbol}:{exchange} from watchlist")
        return True, f"Removed {symbol} from watchlist"
    except Exception as e:
        logger.error(f"Error removing from watchlist: {e}")
        return False, str(e)


def clear_watchlist() -> Tuple[bool, str]:
    """Clear all symbols from watchlist."""
    try:
        with get_connection() as conn:
            conn.execute("DELETE FROM watchlist")
        logger.info("Cleared watchlist")
        return True, "Watchlist cleared"
    except Exception as e:
        logger.error(f"Error clearing watchlist: {e}")
        return False, str(e)


# =============================================================================
# Market Data Operations
# =============================================================================

def upsert_market_data(df: pd.DataFrame, symbol: str, exchange: str, interval: str) -> int:
    """
    Insert or update OHLCV data from a pandas DataFrame.

    Args:
        df: DataFrame with columns: timestamp, open, high, low, close, volume, oi (optional)
        symbol: Trading symbol
        exchange: Exchange code
        interval: Time interval (1m, 5m, 15m, 30m, 1h, D)

    Returns:
        Number of records inserted/updated
    """
    if df.empty:
        return 0

    try:
        # Prepare DataFrame
        df = df.copy()
        df['symbol'] = symbol.upper()
        df['exchange'] = exchange.upper()
        df['interval'] = interval

        # Ensure required columns exist
        if 'oi' not in df.columns:
            df['oi'] = 0

        # Ensure timestamp is integer (epoch seconds)
        if df['timestamp'].dtype != 'int64':
            df['timestamp'] = pd.to_datetime(df['timestamp']).astype('int64') // 10**9

        # Select only required columns in correct order
        df = df[['symbol', 'exchange', 'interval', 'timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi']]

        with get_connection() as conn:
            # Use INSERT OR REPLACE for efficient upsert
            conn.execute("""
                INSERT OR REPLACE INTO market_data
                (symbol, exchange, interval, timestamp, open, high, low, close, volume, oi)
                SELECT symbol, exchange, interval, timestamp, open, high, low, close, volume, oi
                FROM df
            """)

            # Update catalog
            conn.execute("""
                INSERT OR REPLACE INTO data_catalog
                (symbol, exchange, interval, first_timestamp, last_timestamp,
                 record_count, last_download_at)
                SELECT
                    ?, ?, ?,
                    MIN(timestamp), MAX(timestamp), COUNT(*),
                    current_timestamp
                FROM market_data
                WHERE symbol = ? AND exchange = ? AND interval = ?
            """, [symbol.upper(), exchange.upper(), interval,
                  symbol.upper(), exchange.upper(), interval])

        logger.info(f"Upserted {len(df)} records for {symbol}:{exchange}:{interval}")
        return len(df)

    except Exception as e:
        logger.error(f"Error upserting market data: {e}")
        raise


def get_ohlcv(
    symbol: str,
    exchange: str,
    interval: str,
    start_timestamp: Optional[int] = None,
    end_timestamp: Optional[int] = None
) -> pd.DataFrame:
    """
    Retrieve OHLCV data for a symbol.

    Args:
        symbol: Trading symbol
        exchange: Exchange code
        interval: Time interval
        start_timestamp: Start epoch timestamp (optional)
        end_timestamp: End epoch timestamp (optional)

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume, oi
    """
    try:
        query = """
            SELECT timestamp, open, high, low, close, volume, oi
            FROM market_data
            WHERE symbol = ? AND exchange = ? AND interval = ?
        """
        params = [symbol.upper(), exchange.upper(), interval]

        if start_timestamp:
            query += " AND timestamp >= ?"
            params.append(start_timestamp)

        if end_timestamp:
            query += " AND timestamp <= ?"
            params.append(end_timestamp)

        query += " ORDER BY timestamp ASC"

        with get_connection() as conn:
            result = conn.execute(query, params).fetchdf()

        return result

    except Exception as e:
        logger.error(f"Error fetching OHLCV data: {e}")
        return pd.DataFrame()


def get_data_catalog() -> List[Dict[str, Any]]:
    """
    Get summary of all available data in the database.

    Returns:
        List of dictionaries with symbol, exchange, interval, and data range info
    """
    try:
        with get_connection() as conn:
            result = conn.execute("""
                SELECT
                    symbol, exchange, interval,
                    first_timestamp, last_timestamp,
                    record_count, last_download_at
                FROM data_catalog
                ORDER BY exchange, symbol, interval
            """).fetchdf()

        if result.empty:
            return []

        return result.to_dict('records')

    except Exception as e:
        logger.error(f"Error fetching data catalog: {e}")
        return []


def get_available_symbols() -> List[Dict[str, str]]:
    """
    Get list of unique symbol-exchange combinations with data.

    Returns:
        List of dictionaries with symbol and exchange
    """
    try:
        with get_connection() as conn:
            result = conn.execute("""
                SELECT DISTINCT symbol, exchange
                FROM data_catalog
                ORDER BY exchange, symbol
            """).fetchdf()

        if result.empty:
            return []

        return result.to_dict('records')

    except Exception as e:
        logger.error(f"Error fetching available symbols: {e}")
        return []


def get_data_range(symbol: str, exchange: str, interval: str) -> Optional[Dict[str, Any]]:
    """
    Get the date range of available data for a symbol.

    Returns:
        Dictionary with first_timestamp, last_timestamp, record_count
        or None if no data exists
    """
    try:
        with get_connection() as conn:
            result = conn.execute("""
                SELECT first_timestamp, last_timestamp, record_count
                FROM data_catalog
                WHERE symbol = ? AND exchange = ? AND interval = ?
            """, [symbol.upper(), exchange.upper(), interval]).fetchone()

        if result:
            return {
                'first_timestamp': result[0],
                'last_timestamp': result[1],
                'record_count': result[2]
            }
        return None

    except Exception as e:
        logger.error(f"Error fetching data range: {e}")
        return None


def delete_market_data(
    symbol: str,
    exchange: str,
    interval: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Delete market data for a symbol.

    Args:
        symbol: Trading symbol
        exchange: Exchange code
        interval: Time interval (if None, deletes all intervals)

    Returns:
        Tuple of (success, message)
    """
    try:
        with get_connection() as conn:
            if interval:
                conn.execute("""
                    DELETE FROM market_data
                    WHERE symbol = ? AND exchange = ? AND interval = ?
                """, [symbol.upper(), exchange.upper(), interval])
                conn.execute("""
                    DELETE FROM data_catalog
                    WHERE symbol = ? AND exchange = ? AND interval = ?
                """, [symbol.upper(), exchange.upper(), interval])
                msg = f"Deleted {symbol}:{exchange}:{interval} data"
            else:
                conn.execute("""
                    DELETE FROM market_data
                    WHERE symbol = ? AND exchange = ?
                """, [symbol.upper(), exchange.upper()])
                conn.execute("""
                    DELETE FROM data_catalog
                    WHERE symbol = ? AND exchange = ?
                """, [symbol.upper(), exchange.upper()])
                msg = f"Deleted all {symbol}:{exchange} data"

        logger.info(msg)
        return True, msg

    except Exception as e:
        logger.error(f"Error deleting market data: {e}")
        return False, str(e)


# =============================================================================
# Export Operations
# =============================================================================

def export_to_csv(
    output_path: str,
    symbol: Optional[str] = None,
    exchange: Optional[str] = None,
    interval: Optional[str] = None,
    start_timestamp: Optional[int] = None,
    end_timestamp: Optional[int] = None
) -> Tuple[bool, str]:
    """
    Export market data to CSV file.

    Args:
        output_path: Path to save the CSV file
        symbol: Filter by symbol (optional)
        exchange: Filter by exchange (optional)
        interval: Filter by interval (optional)
        start_timestamp: Start epoch timestamp (optional)
        end_timestamp: End epoch timestamp (optional)

    Returns:
        Tuple of (success, message)
    """
    try:
        # Build WHERE clause
        conditions = []
        params = []

        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol.upper())
        if exchange:
            conditions.append("exchange = ?")
            params.append(exchange.upper())
        if interval:
            conditions.append("interval = ?")
            params.append(interval)
        if start_timestamp:
            conditions.append("timestamp >= ?")
            params.append(start_timestamp)
        if end_timestamp:
            conditions.append("timestamp <= ?")
            params.append(end_timestamp)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
            SELECT
                symbol, exchange, interval,
                strftime(to_timestamp(timestamp), '%Y-%m-%d') as date,
                strftime(to_timestamp(timestamp), '%H:%M:%S') as time,
                open, high, low, close, volume, oi
            FROM market_data
            WHERE {where_clause}
            ORDER BY symbol, exchange, interval, timestamp
        """

        # Validate output path - must be within temp directory
        import tempfile
        temp_dir = tempfile.gettempdir()
        abs_output = os.path.abspath(output_path)
        if not abs_output.startswith(os.path.abspath(temp_dir)):
            return False, "Invalid output path: must be within temp directory"

        with get_connection() as conn:
            # Always use parameterized query and pandas to_csv for safety
            df = conn.execute(query, params).fetchdf()
            df.to_csv(output_path, index=False)

        logger.info(f"Exported data to {output_path}")
        return True, f"Data exported to {output_path}"

    except Exception as e:
        logger.error(f"Error exporting to CSV: {e}")
        return False, str(e)


def export_to_dataframe(
    symbol: str,
    exchange: str,
    interval: str,
    start_timestamp: Optional[int] = None,
    end_timestamp: Optional[int] = None
) -> pd.DataFrame:
    """
    Export market data to pandas DataFrame (for backtesting).

    Returns:
        DataFrame with datetime index and OHLCV columns
    """
    df = get_ohlcv(symbol, exchange, interval, start_timestamp, end_timestamp)

    if df.empty:
        return df

    # Convert timestamp to datetime and set as index
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='s')
    df.set_index('datetime', inplace=True)
    df.drop('timestamp', axis=1, inplace=True)

    return df


# =============================================================================
# Utility Functions
# =============================================================================

def get_database_stats() -> Dict[str, Any]:
    """
    Get database statistics.

    Returns:
        Dictionary with database size, record counts, etc.
    """
    try:
        db_path = get_db_path()
        db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0

        with get_connection() as conn:
            total_records = conn.execute("SELECT COUNT(*) FROM market_data").fetchone()[0]
            total_symbols = conn.execute("SELECT COUNT(DISTINCT symbol || exchange) FROM market_data").fetchone()[0]
            watchlist_count = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]

        return {
            'database_path': db_path,
            'database_size_mb': round(db_size / (1024 * 1024), 2),
            'total_records': total_records,
            'total_symbols': total_symbols,
            'watchlist_count': watchlist_count
        }

    except Exception as e:
        logger.error(f"Error fetching database stats: {e}")
        return {
            'database_path': get_db_path(),
            'database_size_mb': 0,
            'total_records': 0,
            'total_symbols': 0,
            'watchlist_count': 0
        }


def vacuum_database():
    """
    Vacuum the database to reclaim space and optimize performance.
    """
    try:
        with get_connection() as conn:
            conn.execute("VACUUM")
        logger.info("Database vacuumed successfully")
    except Exception as e:
        logger.error(f"Error vacuuming database: {e}")


# Supported exchanges (these are static across brokers)
SUPPORTED_EXCHANGES = [
    'NSE', 'BSE', 'NFO', 'BFO', 'MCX', 'CDS', 'BCD',
    'NSE_INDEX', 'BSE_INDEX'
]


def get_supported_intervals(api_key: str) -> List[str]:
    """
    Get supported intervals dynamically from the broker.
    Uses the intervals_service to fetch broker-specific supported timeframes.

    Args:
        api_key: OpenAlgo API key

    Returns:
        List of supported interval strings (e.g., ['1m', '5m', '15m', '1h', 'D'])
    """
    try:
        from services.intervals_service import get_intervals

        success, response, _ = get_intervals(api_key=api_key)

        if success and response.get('status') == 'success':
            intervals_data = response.get('data', {})
            # Flatten all interval categories into a single list
            all_intervals = []
            for category in ['seconds', 'minutes', 'hours', 'days', 'weeks', 'months']:
                all_intervals.extend(intervals_data.get(category, []))
            return all_intervals
        return []
    except Exception as e:
        logger.error(f"Error fetching supported intervals: {e}")
        return []


# =============================================================================
# CSV Import Operations
# =============================================================================

def import_from_csv(
    file_path: str,
    symbol: str,
    exchange: str,
    interval: str
) -> Tuple[bool, str, int]:
    """
    Import OHLCV data from a CSV file into the database.

    Expected CSV format (one of these column sets):
        Option 1: timestamp, open, high, low, close, volume, oi
        Option 2: date, time, open, high, low, close, volume, oi
        Option 3: datetime, open, high, low, close, volume

    The CSV must have headers. Column names are case-insensitive.

    Args:
        file_path: Path to the CSV file
        symbol: Trading symbol
        exchange: Exchange code
        interval: Time interval (e.g., '1m', '5m', 'D')

    Returns:
        Tuple of (success, message, records_imported)
    """
    try:
        # Read CSV with flexible parsing
        df = pd.read_csv(file_path)

        if df.empty:
            return False, "CSV file is empty", 0

        # Normalize column names to lowercase
        df.columns = df.columns.str.lower().str.strip()

        # Handle different timestamp formats
        if 'timestamp' in df.columns:
            # Check if timestamp is already epoch seconds or milliseconds
            if pd.api.types.is_numeric_dtype(df['timestamp']):
                first_val = df['timestamp'].iloc[0]
                # Epoch milliseconds are > 1e12 (after year 2001 in ms)
                # Epoch seconds are typically between 1e9 and 2e9 (1970-2033)
                if first_val > 1e12:
                    # Milliseconds - convert to seconds
                    df['timestamp'] = df['timestamp'] // 1000
                # else: Already epoch seconds, no conversion needed
            else:
                # Parse as datetime string
                df['timestamp'] = pd.to_datetime(df['timestamp']).astype('int64') // 10**9
        elif 'datetime' in df.columns:
            df['timestamp'] = pd.to_datetime(df['datetime']).astype('int64') // 10**9
        elif 'date' in df.columns:
            if 'time' in df.columns:
                df['datetime'] = df['date'].astype(str) + ' ' + df['time'].astype(str)
            else:
                df['datetime'] = df['date'].astype(str)
            df['timestamp'] = pd.to_datetime(df['datetime']).astype('int64') // 10**9
        else:
            return False, "CSV must have 'timestamp', 'datetime', or 'date' column", 0

        # Validate required OHLCV columns
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            return False, f"Missing required columns: {', '.join(missing_cols)}", 0

        # Add optional columns if missing
        if 'oi' not in df.columns:
            df['oi'] = 0

        # Select and order columns
        df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi']]

        # Convert data types
        df['timestamp'] = df['timestamp'].astype('int64')
        df['open'] = pd.to_numeric(df['open'], errors='coerce')
        df['high'] = pd.to_numeric(df['high'], errors='coerce')
        df['low'] = pd.to_numeric(df['low'], errors='coerce')
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce').fillna(0).astype('int64')
        df['oi'] = pd.to_numeric(df['oi'], errors='coerce').fillna(0).astype('int64')

        # Drop rows with NaN values in OHLC
        initial_count = len(df)
        df = df.dropna(subset=['open', 'high', 'low', 'close'])
        dropped_count = initial_count - len(df)

        if df.empty:
            return False, "No valid data rows after parsing", 0

        # Insert into database
        records = upsert_market_data(df, symbol, exchange, interval)

        msg = f"Imported {records} records"
        if dropped_count > 0:
            msg += f" ({dropped_count} rows skipped due to invalid data)"

        logger.info(f"CSV import: {msg} for {symbol}:{exchange}:{interval}")
        return True, msg, records

    except pd.errors.ParserError as e:
        logger.error(f"CSV parsing error: {e}")
        return False, f"CSV parsing error: {str(e)}", 0
    except Exception as e:
        logger.error(f"Error importing CSV: {e}")
        return False, str(e), 0
