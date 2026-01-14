# services/historify_service.py
"""
Historify Service Layer

Business logic for historical market data management:
- Download data from brokers and store in DuckDB
- Manage watchlist
- Export data to CSV
- Provide OHLCV data for charts and backtesting
"""

import os
import pandas as pd
from typing import Tuple, Dict, Any, Optional, List
from datetime import datetime, date, timedelta
from utils.logging import get_logger
from database.historify_db import (
    get_watchlist as db_get_watchlist,
    add_to_watchlist as db_add_to_watchlist,
    remove_from_watchlist as db_remove_from_watchlist,
    upsert_market_data,
    get_ohlcv,
    get_data_catalog as db_get_data_catalog,
    get_data_range,
    export_to_csv as db_export_to_csv,
    export_to_dataframe,
    get_database_stats,
    delete_market_data,
    import_from_csv as db_import_from_csv,
    SUPPORTED_EXCHANGES,
    init_database
)
from services.history_service import get_history
from services.intervals_service import get_intervals
from database.auth_db import get_auth_token_broker

logger = get_logger(__name__)


# =============================================================================
# Watchlist Operations
# =============================================================================

def get_watchlist() -> Tuple[bool, Dict[str, Any], int]:
    """
    Get all symbols in the watchlist.

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        watchlist = db_get_watchlist()
        return True, {
            'status': 'success',
            'data': watchlist,
            'count': len(watchlist)
        }, 200
    except Exception as e:
        logger.error(f"Error getting watchlist: {e}")
        return False, {
            'status': 'error',
            'message': str(e)
        }, 500


def add_to_watchlist(symbol: str, exchange: str, display_name: str = None) -> Tuple[bool, Dict[str, Any], int]:
    """
    Add a symbol to the watchlist.

    Args:
        symbol: Trading symbol
        exchange: Exchange code
        display_name: Optional display name

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        if not symbol or not exchange:
            return False, {
                'status': 'error',
                'message': 'Symbol and exchange are required'
            }, 400

        if exchange.upper() not in SUPPORTED_EXCHANGES:
            return False, {
                'status': 'error',
                'message': f'Invalid exchange. Supported: {", ".join(SUPPORTED_EXCHANGES)}'
            }, 400

        success, msg = db_add_to_watchlist(symbol, exchange, display_name)

        if success:
            return True, {
                'status': 'success',
                'message': msg
            }, 200
        else:
            return False, {
                'status': 'error',
                'message': msg
            }, 400

    except Exception as e:
        logger.error(f"Error adding to watchlist: {e}")
        return False, {
            'status': 'error',
            'message': str(e)
        }, 500


def remove_from_watchlist(symbol: str, exchange: str) -> Tuple[bool, Dict[str, Any], int]:
    """
    Remove a symbol from the watchlist.

    Args:
        symbol: Trading symbol
        exchange: Exchange code

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        if not symbol or not exchange:
            return False, {
                'status': 'error',
                'message': 'Symbol and exchange are required'
            }, 400

        success, msg = db_remove_from_watchlist(symbol, exchange)

        if success:
            return True, {
                'status': 'success',
                'message': msg
            }, 200
        else:
            return False, {
                'status': 'error',
                'message': msg
            }, 400

    except Exception as e:
        logger.error(f"Error removing from watchlist: {e}")
        return False, {
            'status': 'error',
            'message': str(e)
        }, 500


def bulk_add_to_watchlist(symbols: List[Dict[str, str]]) -> Tuple[bool, Dict[str, Any], int]:
    """
    Add multiple symbols to the watchlist.

    Args:
        symbols: List of dicts with 'symbol' and 'exchange' keys

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        added = 0
        failed = []

        for item in symbols:
            symbol = item.get('symbol', '').upper()
            exchange = item.get('exchange', '').upper()
            display_name = item.get('display_name')

            if not symbol or not exchange:
                failed.append({'symbol': symbol, 'exchange': exchange, 'error': 'Missing symbol or exchange'})
                continue

            success, msg = db_add_to_watchlist(symbol, exchange, display_name)
            if success:
                added += 1
            else:
                failed.append({'symbol': symbol, 'exchange': exchange, 'error': msg})

        return True, {
            'status': 'success',
            'added': added,
            'failed': failed,
            'total': len(symbols)
        }, 200

    except Exception as e:
        logger.error(f"Error bulk adding to watchlist: {e}")
        return False, {
            'status': 'error',
            'message': str(e)
        }, 500


# =============================================================================
# Data Download Operations
# =============================================================================

def download_data(
    symbol: str,
    exchange: str,
    interval: str,
    start_date: str,
    end_date: str,
    api_key: str
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Download historical data for a symbol and store in DuckDB.

    Args:
        symbol: Trading symbol
        exchange: Exchange code
        interval: Time interval (from broker's supported intervals)
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        api_key: OpenAlgo API key

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        logger.info(f"Downloading {symbol}:{exchange}:{interval} from {start_date} to {end_date}")

        # Fetch data from broker via history_service
        success, response, status_code = get_history(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            api_key=api_key
        )

        if not success:
            return False, response, status_code

        data = response.get('data', [])
        if not data:
            return True, {
                'status': 'success',
                'message': 'No data available for the specified period',
                'records': 0
            }, 200

        # Convert to DataFrame
        df = pd.DataFrame(data)

        # Normalize timestamp column
        if 'time' in df.columns:
            df['timestamp'] = df['time']
        elif 'timestamp' not in df.columns:
            return False, {
                'status': 'error',
                'message': 'No timestamp column in data'
            }, 500

        # Store in DuckDB
        records = upsert_market_data(df, symbol, exchange, interval)

        logger.info(f"Downloaded and stored {records} records for {symbol}:{exchange}:{interval}")

        return True, {
            'status': 'success',
            'symbol': symbol.upper(),
            'exchange': exchange.upper(),
            'interval': interval,
            'start_date': start_date,
            'end_date': end_date,
            'records': records
        }, 200

    except Exception as e:
        logger.error(f"Error downloading data: {e}")
        return False, {
            'status': 'error',
            'message': str(e)
        }, 500


def download_watchlist_data(
    interval: str,
    start_date: str,
    end_date: str,
    api_key: str
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Download data for all symbols in the watchlist.

    Args:
        interval: Time interval
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        api_key: OpenAlgo API key

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        watchlist = db_get_watchlist()

        if not watchlist:
            return False, {
                'status': 'error',
                'message': 'Watchlist is empty'
            }, 400

        results = []
        for item in watchlist:
            symbol = item['symbol']
            exchange = item['exchange']

            success, response, _ = download_data(
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                start_date=start_date,
                end_date=end_date,
                api_key=api_key
            )

            results.append({
                'symbol': symbol,
                'exchange': exchange,
                'success': success,
                'records': response.get('records', 0) if success else 0,
                'error': response.get('message') if not success else None
            })

        total_records = sum(r['records'] for r in results if r['success'])
        successful = sum(1 for r in results if r['success'])

        return True, {
            'status': 'success',
            'interval': interval,
            'start_date': start_date,
            'end_date': end_date,
            'total_symbols': len(watchlist),
            'successful': successful,
            'total_records': total_records,
            'results': results
        }, 200

    except Exception as e:
        logger.error(f"Error downloading watchlist data: {e}")
        return False, {
            'status': 'error',
            'message': str(e)
        }, 500


# =============================================================================
# Data Retrieval Operations
# =============================================================================

def get_chart_data(
    symbol: str,
    exchange: str,
    interval: str,
    start_date: str = None,
    end_date: str = None
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get OHLCV data for charting.

    Args:
        symbol: Trading symbol
        exchange: Exchange code
        interval: Time interval
        start_date: Start date in YYYY-MM-DD format (optional)
        end_date: End date in YYYY-MM-DD format (optional)

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        # Convert dates to timestamps if provided
        start_ts = None
        end_ts = None

        if start_date:
            start_ts = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp())
        if end_date:
            # Add 1 day to include end date
            end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            end_ts = int(end_dt.timestamp())

        df = get_ohlcv(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_timestamp=start_ts,
            end_timestamp=end_ts
        )

        if df.empty:
            return True, {
                'status': 'success',
                'data': [],
                'count': 0,
                'message': 'No data available'
            }, 200

        # Convert to list of dicts for JSON response
        data = df.to_dict('records')

        return True, {
            'status': 'success',
            'symbol': symbol.upper(),
            'exchange': exchange.upper(),
            'interval': interval,
            'data': data,
            'count': len(data)
        }, 200

    except Exception as e:
        logger.error(f"Error getting chart data: {e}")
        return False, {
            'status': 'error',
            'message': str(e)
        }, 500


def get_data_catalog() -> Tuple[bool, Dict[str, Any], int]:
    """
    Get catalog of all available data.

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        catalog = db_get_data_catalog()

        # Convert timestamps to readable dates
        for item in catalog:
            if item.get('first_timestamp'):
                item['first_date'] = datetime.fromtimestamp(item['first_timestamp']).strftime('%Y-%m-%d')
            if item.get('last_timestamp'):
                item['last_date'] = datetime.fromtimestamp(item['last_timestamp']).strftime('%Y-%m-%d')

        return True, {
            'status': 'success',
            'data': catalog,
            'count': len(catalog)
        }, 200

    except Exception as e:
        logger.error(f"Error getting data catalog: {e}")
        return False, {
            'status': 'error',
            'message': str(e)
        }, 500


def get_symbol_data_info(symbol: str, exchange: str, interval: str = None) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get data availability info for a symbol.

    Args:
        symbol: Trading symbol
        exchange: Exchange code
        interval: Time interval (optional - returns all if not specified)

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        if interval:
            data_range = get_data_range(symbol, exchange, interval)
            if data_range:
                data_range['first_date'] = datetime.fromtimestamp(data_range['first_timestamp']).strftime('%Y-%m-%d')
                data_range['last_date'] = datetime.fromtimestamp(data_range['last_timestamp']).strftime('%Y-%m-%d')
                return True, {
                    'status': 'success',
                    'symbol': symbol.upper(),
                    'exchange': exchange.upper(),
                    'interval': interval,
                    'data': data_range
                }, 200
            else:
                return True, {
                    'status': 'success',
                    'symbol': symbol.upper(),
                    'exchange': exchange.upper(),
                    'interval': interval,
                    'data': None,
                    'message': 'No data available'
                }, 200
        else:
            # Return all intervals for this symbol
            catalog = db_get_data_catalog()
            symbol_data = [
                c for c in catalog
                if c['symbol'] == symbol.upper() and c['exchange'] == exchange.upper()
            ]
            return True, {
                'status': 'success',
                'symbol': symbol.upper(),
                'exchange': exchange.upper(),
                'intervals': symbol_data
            }, 200

    except Exception as e:
        logger.error(f"Error getting symbol data info: {e}")
        return False, {
            'status': 'error',
            'message': str(e)
        }, 500


# =============================================================================
# Export Operations
# =============================================================================

def export_data_to_csv(
    output_dir: str,
    symbol: str = None,
    exchange: str = None,
    interval: str = None,
    start_date: str = None,
    end_date: str = None
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Export data to CSV file.

    Args:
        output_dir: Directory to save the CSV file
        symbol: Filter by symbol (optional)
        exchange: Filter by exchange (optional)
        interval: Filter by interval (optional)
        start_date: Start date in YYYY-MM-DD format (optional)
        end_date: End date in YYYY-MM-DD format (optional)

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        # Generate filename
        parts = ['historify_data']
        if symbol:
            parts.append(symbol.upper())
        if exchange:
            parts.append(exchange.upper())
        if interval:
            parts.append(interval)
        parts.append(datetime.now().strftime('%Y%m%d_%H%M%S'))

        filename = '_'.join(parts) + '.csv'
        output_path = os.path.join(output_dir, filename)

        # Convert dates to timestamps
        start_ts = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp()) if start_date else None
        end_ts = int(datetime.strptime(end_date, '%Y-%m-%d').timestamp()) if end_date else None

        success, msg = db_export_to_csv(
            output_path=output_path,
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_timestamp=start_ts,
            end_timestamp=end_ts
        )

        if success:
            file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
            return True, {
                'status': 'success',
                'message': msg,
                'file_path': output_path,
                'file_size_kb': round(file_size / 1024, 2)
            }, 200
        else:
            return False, {
                'status': 'error',
                'message': msg
            }, 500

    except Exception as e:
        logger.error(f"Error exporting to CSV: {e}")
        return False, {
            'status': 'error',
            'message': str(e)
        }, 500


def get_export_dataframe(
    symbol: str,
    exchange: str,
    interval: str,
    start_date: str = None,
    end_date: str = None
) -> pd.DataFrame:
    """
    Get data as pandas DataFrame for backtesting.

    Args:
        symbol: Trading symbol
        exchange: Exchange code
        interval: Time interval
        start_date: Start date in YYYY-MM-DD format (optional)
        end_date: End date in YYYY-MM-DD format (optional)

    Returns:
        DataFrame with datetime index and OHLCV columns
    """
    start_ts = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp()) if start_date else None
    end_ts = int(datetime.strptime(end_date, '%Y-%m-%d').timestamp()) if end_date else None

    return export_to_dataframe(symbol, exchange, interval, start_ts, end_ts)


# =============================================================================
# Utility Operations
# =============================================================================

def get_supported_timeframes(api_key: str) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get supported timeframes from the connected broker.

    Args:
        api_key: OpenAlgo API key

    Returns:
        Tuple of (success, response_data, status_code)
    """
    return get_intervals(api_key=api_key)


def get_exchanges() -> Tuple[bool, Dict[str, Any], int]:
    """
    Get list of supported exchanges.

    Returns:
        Tuple of (success, response_data, status_code)
    """
    return True, {
        'status': 'success',
        'data': SUPPORTED_EXCHANGES
    }, 200


def get_stats() -> Tuple[bool, Dict[str, Any], int]:
    """
    Get Historify database statistics.

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        stats = get_database_stats()
        return True, {
            'status': 'success',
            'data': stats
        }, 200
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return False, {
            'status': 'error',
            'message': str(e)
        }, 500


def delete_symbol_data(
    symbol: str,
    exchange: str,
    interval: str = None
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Delete market data for a symbol.

    Args:
        symbol: Trading symbol
        exchange: Exchange code
        interval: Time interval (optional - deletes all if not specified)

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        success, msg = delete_market_data(symbol, exchange, interval)
        if success:
            return True, {
                'status': 'success',
                'message': msg
            }, 200
        else:
            return False, {
                'status': 'error',
                'message': msg
            }, 500
    except Exception as e:
        logger.error(f"Error deleting data: {e}")
        return False, {
            'status': 'error',
            'message': str(e)
        }, 500


def initialize_historify() -> Tuple[bool, Dict[str, Any], int]:
    """
    Initialize the Historify database.
    Called on app startup to ensure database is ready.

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        init_database()
        return True, {
            'status': 'success',
            'message': 'Historify database initialized'
        }, 200
    except Exception as e:
        logger.error(f"Error initializing Historify: {e}")
        return False, {
            'status': 'error',
            'message': str(e)
        }, 500


# =============================================================================
# CSV Upload Operations
# =============================================================================

# Valid intervals for data import (common across brokers)
VALID_INTERVALS = {
    '1s', '5s', '10s', '15s', '30s',  # Seconds
    '1m', '2m', '3m', '5m', '10m', '15m', '20m', '30m', '45m',  # Minutes
    '1h', '2h', '3h', '4h',  # Hours
    'D', '1D', 'W', '1W', 'M', '1M',  # Days, Weeks, Months
}


def upload_csv_data(
    file_path: str,
    symbol: str,
    exchange: str,
    interval: str
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Upload CSV data to the Historify database.

    Args:
        file_path: Path to the uploaded CSV file
        symbol: Trading symbol
        exchange: Exchange code
        interval: Time interval

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        if not symbol or not exchange or not interval:
            return False, {
                'status': 'error',
                'message': 'Symbol, exchange, and interval are required'
            }, 400

        if exchange.upper() not in SUPPORTED_EXCHANGES:
            return False, {
                'status': 'error',
                'message': f'Invalid exchange. Supported: {", ".join(SUPPORTED_EXCHANGES)}'
            }, 400

        # Validate interval
        if interval not in VALID_INTERVALS:
            return False, {
                'status': 'error',
                'message': f'Invalid interval. Supported: {", ".join(sorted(VALID_INTERVALS))}'
            }, 400

        success, msg, records = db_import_from_csv(file_path, symbol, exchange, interval)

        if success:
            return True, {
                'status': 'success',
                'message': msg,
                'symbol': symbol.upper(),
                'exchange': exchange.upper(),
                'interval': interval,
                'records': records
            }, 200
        else:
            return False, {
                'status': 'error',
                'message': msg
            }, 400

    except Exception as e:
        logger.error(f"Error uploading CSV: {e}")
        return False, {
            'status': 'error',
            'message': str(e)
        }, 500
