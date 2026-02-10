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
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from database.auth_db import get_auth_token_broker
from database.historify_db import (
    COMPUTED_INTERVALS,
    STORAGE_INTERVALS,
    SUPPORTED_EXCHANGES,
    delete_market_data,
    export_to_dataframe,
    get_data_range,
    get_database_stats,
    get_ohlcv,
    init_database,
    upsert_market_data,
)
from database.historify_db import add_to_watchlist as db_add_to_watchlist
from database.historify_db import bulk_add_to_watchlist as db_bulk_add_to_watchlist
from database.historify_db import export_to_csv as db_export_to_csv
from database.historify_db import get_data_catalog as db_get_data_catalog
from database.historify_db import get_watchlist as db_get_watchlist
from database.historify_db import import_from_csv as db_import_from_csv
from database.historify_db import import_from_parquet as db_import_from_parquet
from database.historify_db import remove_from_watchlist as db_remove_from_watchlist
from database.historify_db import bulk_remove_from_watchlist as db_bulk_remove_from_watchlist
from database.historify_db import bulk_delete_market_data as db_bulk_delete_market_data
from database.token_db_enhanced import get_symbol_info
from services.history_service import get_history
from services.intervals_service import get_intervals
from utils.logging import get_logger

logger = get_logger(__name__)


def validate_symbol(symbol: str, exchange: str) -> tuple[bool, str]:
    """
    Validate that a symbol exists in the master contract database.

    Args:
        symbol: Trading symbol
        exchange: Exchange code

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Index exchanges don't need validation against master contract
    if exchange.upper() in ("NSE_INDEX", "BSE_INDEX"):
        return True, ""

    try:
        symbol_info = get_symbol_info(symbol.upper(), exchange.upper())
        if symbol_info is None:
            return (
                False,
                f"Symbol '{symbol}' not found in {exchange} master contract. Please check the symbol name.",
            )
        return True, ""
    except Exception as e:
        logger.warning(f"Could not validate symbol {symbol}:{exchange}: {e}")
        # If validation fails due to cache/db issues, allow the symbol
        # (it will fail during download if truly invalid)
        return True, ""


# =============================================================================
# Watchlist Operations
# =============================================================================


def get_watchlist() -> tuple[bool, dict[str, Any], int]:
    """
    Get all symbols in the watchlist.

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        watchlist = db_get_watchlist()
        return True, {"status": "success", "data": watchlist, "count": len(watchlist)}, 200
    except Exception as e:
        logger.exception(f"Error getting watchlist: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def add_to_watchlist(
    symbol: str, exchange: str, display_name: str = None
) -> tuple[bool, dict[str, Any], int]:
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
            return False, {"status": "error", "message": "Symbol and exchange are required"}, 400

        if exchange.upper() not in SUPPORTED_EXCHANGES:
            return (
                False,
                {
                    "status": "error",
                    "message": f"Invalid exchange. Supported: {', '.join(SUPPORTED_EXCHANGES)}",
                },
                400,
            )

        # Validate symbol exists in master contract database
        is_valid, error_msg = validate_symbol(symbol, exchange)
        if not is_valid:
            return False, {"status": "error", "message": error_msg}, 400

        success, msg = db_add_to_watchlist(symbol, exchange, display_name)

        if success:
            return True, {"status": "success", "message": msg}, 200
        else:
            return False, {"status": "error", "message": msg}, 400

    except Exception as e:
        logger.exception(f"Error adding to watchlist: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def remove_from_watchlist(symbol: str, exchange: str) -> tuple[bool, dict[str, Any], int]:
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
            return False, {"status": "error", "message": "Symbol and exchange are required"}, 400

        success, msg = db_remove_from_watchlist(symbol, exchange)

        if success:
            return True, {"status": "success", "message": msg}, 200
        else:
            return False, {"status": "error", "message": msg}, 400

    except Exception as e:
        logger.exception(f"Error removing from watchlist: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def bulk_remove_from_watchlist(
    symbols: list[dict[str, str]],
) -> tuple[bool, dict[str, Any], int]:
    """
    Remove multiple symbols from the watchlist in a single bulk operation.

    Args:
        symbols: List of dicts with 'symbol' and 'exchange' keys

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        if not symbols:
            return False, {"status": "error", "message": "No symbols provided"}, 400

        removed, skipped, failed = db_bulk_remove_from_watchlist(symbols)

        total = len(symbols)
        message = f"Removed {removed} symbol(s) from watchlist"
        if skipped > 0:
            message += f", {skipped} not found"
        if failed:
            message += f", {len(failed)} failed"

        return (
            True,
            {
                "status": "success",
                "message": message,
                "removed": removed,
                "skipped": skipped,
                "failed": failed,
                "total": total,
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error bulk removing from watchlist: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def bulk_add_to_watchlist(symbols: list[dict[str, str]]) -> tuple[bool, dict[str, Any], int]:
    """
    Add multiple symbols to the watchlist in a single bulk operation.

    Args:
        symbols: List of dicts with 'symbol' and 'exchange' keys

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        # Validate symbols before bulk insert
        validated_symbols = []
        invalid_symbols = []

        for item in symbols:
            symbol = item.get("symbol", "").upper()
            exchange = item.get("exchange", "").upper()

            if not symbol or not exchange:
                invalid_symbols.append(
                    {
                        "symbol": symbol or "MISSING",
                        "exchange": exchange or "MISSING",
                        "error": "Missing symbol or exchange",
                    }
                )
                continue

            if exchange not in SUPPORTED_EXCHANGES:
                invalid_symbols.append(
                    {"symbol": symbol, "exchange": exchange, "error": "Invalid exchange"}
                )
                continue

            # Validate symbol exists in master contract
            is_valid, error_msg = validate_symbol(symbol, exchange)
            if not is_valid:
                invalid_symbols.append({"symbol": symbol, "exchange": exchange, "error": error_msg})
                continue

            validated_symbols.append(item)

        # Use bulk insert for validated symbols
        added, skipped, failed = db_bulk_add_to_watchlist(validated_symbols)

        # Add invalid symbols to failed list
        failed.extend(invalid_symbols)

        return (
            True,
            {
                "status": "success",
                "added": added,
                "skipped": skipped,
                "failed": failed,
                "total": len(symbols),
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error bulk adding to watchlist: {e}")
        return False, {"status": "error", "message": str(e)}, 500


# =============================================================================
# Data Download Operations
# =============================================================================


def download_data(
    symbol: str, exchange: str, interval: str, start_date: str, end_date: str, api_key: str
) -> tuple[bool, dict[str, Any], int]:
    """
    Download historical data for a symbol and store in DuckDB.

    Only storage intervals (1m and D) are allowed for download.
    Other timeframes (5m, 15m, 30m, 1h) are computed from 1m data on-the-fly.

    Args:
        symbol: Trading symbol
        exchange: Exchange code
        interval: Time interval - only '1m' or 'D' allowed
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        api_key: OpenAlgo API key

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        # Validate interval - only storage intervals allowed for download
        if interval not in STORAGE_INTERVALS:
            return (
                False,
                {
                    "status": "error",
                    "message": f"Only {', '.join(sorted(STORAGE_INTERVALS))} intervals can be downloaded. "
                    f"Other timeframes ({', '.join(sorted(COMPUTED_INTERVALS))}) are computed from 1m data.",
                },
                400,
            )

        logger.info(f"Downloading {symbol}:{exchange}:{interval} from {start_date} to {end_date}")

        # Fetch data from broker via history_service
        success, response, status_code = get_history(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            api_key=api_key,
        )

        if not success:
            return False, response, status_code

        data = response.get("data", [])
        if not data:
            return (
                True,
                {
                    "status": "success",
                    "message": "No data available for the specified period",
                    "records": 0,
                },
                200,
            )

        # Convert to DataFrame
        df = pd.DataFrame(data)

        # Normalize timestamp column
        if "time" in df.columns:
            df["timestamp"] = df["time"]
        elif "timestamp" not in df.columns:
            return False, {"status": "error", "message": "No timestamp column in data"}, 500

        # Store in DuckDB
        records = upsert_market_data(df, symbol, exchange, interval)

        logger.info(f"Downloaded and stored {records} records for {symbol}:{exchange}:{interval}")

        return (
            True,
            {
                "status": "success",
                "symbol": symbol.upper(),
                "exchange": exchange.upper(),
                "interval": interval,
                "start_date": start_date,
                "end_date": end_date,
                "records": records,
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error downloading data: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def download_watchlist_data(
    interval: str, start_date: str, end_date: str, api_key: str
) -> tuple[bool, dict[str, Any], int]:
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
            return False, {"status": "error", "message": "Watchlist is empty"}, 400

        results = []
        for item in watchlist:
            symbol = item["symbol"]
            exchange = item["exchange"]

            success, response, _ = download_data(
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                start_date=start_date,
                end_date=end_date,
                api_key=api_key,
            )

            results.append(
                {
                    "symbol": symbol,
                    "exchange": exchange,
                    "success": success,
                    "records": response.get("records", 0) if success else 0,
                    "error": response.get("message") if not success else None,
                }
            )

        total_records = sum(r["records"] for r in results if r["success"])
        successful = sum(1 for r in results if r["success"])

        return (
            True,
            {
                "status": "success",
                "interval": interval,
                "start_date": start_date,
                "end_date": end_date,
                "total_symbols": len(watchlist),
                "successful": successful,
                "total_records": total_records,
                "results": results,
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error downloading watchlist data: {e}")
        return False, {"status": "error", "message": str(e)}, 500


# =============================================================================
# Data Retrieval Operations
# =============================================================================


def get_chart_data(
    symbol: str, exchange: str, interval: str, start_date: str = None, end_date: str = None
) -> tuple[bool, dict[str, Any], int]:
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
            start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp())
        if end_date:
            # Add 1 day to include end date
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            end_ts = int(end_dt.timestamp())

        df = get_ohlcv(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_timestamp=start_ts,
            end_timestamp=end_ts,
        )

        if df.empty:
            return (
                True,
                {"status": "success", "data": [], "count": 0, "message": "No data available"},
                200,
            )

        # Convert to list of dicts for JSON response
        data = df.to_dict("records")

        return (
            True,
            {
                "status": "success",
                "symbol": symbol.upper(),
                "exchange": exchange.upper(),
                "interval": interval,
                "data": data,
                "count": len(data),
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error getting chart data: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def get_data_catalog() -> tuple[bool, dict[str, Any], int]:
    """
    Get catalog of all available data.

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        catalog = db_get_data_catalog()

        # Convert timestamps to readable dates
        for item in catalog:
            if item.get("first_timestamp"):
                item["first_date"] = datetime.fromtimestamp(item["first_timestamp"]).strftime(
                    "%Y-%m-%d"
                )
            if item.get("last_timestamp"):
                item["last_date"] = datetime.fromtimestamp(item["last_timestamp"]).strftime(
                    "%Y-%m-%d"
                )

        return True, {"status": "success", "data": catalog, "count": len(catalog)}, 200

    except Exception as e:
        logger.exception(f"Error getting data catalog: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def get_symbol_data_info(
    symbol: str, exchange: str, interval: str = None
) -> tuple[bool, dict[str, Any], int]:
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
                data_range["first_date"] = datetime.fromtimestamp(
                    data_range["first_timestamp"]
                ).strftime("%Y-%m-%d")
                data_range["last_date"] = datetime.fromtimestamp(
                    data_range["last_timestamp"]
                ).strftime("%Y-%m-%d")
                return (
                    True,
                    {
                        "status": "success",
                        "symbol": symbol.upper(),
                        "exchange": exchange.upper(),
                        "interval": interval,
                        "data": data_range,
                    },
                    200,
                )
            else:
                return (
                    True,
                    {
                        "status": "success",
                        "symbol": symbol.upper(),
                        "exchange": exchange.upper(),
                        "interval": interval,
                        "data": None,
                        "message": "No data available",
                    },
                    200,
                )
        else:
            # Return all intervals for this symbol
            catalog = db_get_data_catalog()
            symbol_data = [
                c
                for c in catalog
                if c["symbol"] == symbol.upper() and c["exchange"] == exchange.upper()
            ]
            return (
                True,
                {
                    "status": "success",
                    "symbol": symbol.upper(),
                    "exchange": exchange.upper(),
                    "intervals": symbol_data,
                },
                200,
            )

    except Exception as e:
        logger.exception(f"Error getting symbol data info: {e}")
        return False, {"status": "error", "message": str(e)}, 500


# =============================================================================
# Export Operations
# =============================================================================


def export_data_to_csv(
    output_dir: str,
    symbol: str = None,
    exchange: str = None,
    interval: str = None,
    start_date: str = None,
    end_date: str = None,
) -> tuple[bool, dict[str, Any], int]:
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
        parts = ["historify_data"]
        if symbol:
            parts.append(symbol.upper())
        if exchange:
            parts.append(exchange.upper())
        if interval:
            parts.append(interval)
        parts.append(datetime.now().strftime("%Y%m%d_%H%M%S"))

        filename = "_".join(parts) + ".csv"
        output_path = os.path.join(output_dir, filename)

        # Convert dates to timestamps
        start_ts = (
            int(datetime.strptime(start_date, "%Y-%m-%d").timestamp()) if start_date else None
        )
        end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp()) if end_date else None

        success, msg = db_export_to_csv(
            output_path=output_path,
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_timestamp=start_ts,
            end_timestamp=end_ts,
        )

        if success:
            file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
            return (
                True,
                {
                    "status": "success",
                    "message": msg,
                    "file_path": output_path,
                    "file_size_kb": round(file_size / 1024, 2),
                },
                200,
            )
        else:
            return False, {"status": "error", "message": msg}, 500

    except Exception as e:
        logger.exception(f"Error exporting to CSV: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def get_export_dataframe(
    symbol: str, exchange: str, interval: str, start_date: str = None, end_date: str = None
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
    start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp()) if start_date else None
    end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp()) if end_date else None

    return export_to_dataframe(symbol, exchange, interval, start_ts, end_ts)


# =============================================================================
# Utility Operations
# =============================================================================


def get_supported_timeframes(api_key: str) -> tuple[bool, dict[str, Any], int]:
    """
    Get supported timeframes from the connected broker.

    Args:
        api_key: OpenAlgo API key

    Returns:
        Tuple of (success, response_data, status_code)
    """
    return get_intervals(api_key=api_key)


def get_historify_intervals() -> tuple[bool, dict[str, Any], int]:
    """
    Get Historify-specific interval configuration.

    Returns intervals that are stored vs computed:
    - Storage intervals (1m, D): Actually downloaded and stored
    - Computed intervals (5m, 15m, 30m, 1h): Aggregated from 1m on-the-fly

    Returns:
        Tuple of (success, response_data, status_code)
    """
    return (
        True,
        {
            "status": "success",
            "storage_intervals": sorted(STORAGE_INTERVALS),
            "computed_intervals": sorted(COMPUTED_INTERVALS),
            "all_intervals": sorted(STORAGE_INTERVALS | COMPUTED_INTERVALS),
            "description": {
                "storage": "These intervals are downloaded and stored in the database",
                "computed": "These intervals are computed from 1-minute data on-the-fly",
            },
        },
        200,
    )


def get_exchanges() -> tuple[bool, dict[str, Any], int]:
    """
    Get list of supported exchanges.

    Returns:
        Tuple of (success, response_data, status_code)
    """
    return True, {"status": "success", "data": SUPPORTED_EXCHANGES}, 200


def get_stats() -> tuple[bool, dict[str, Any], int]:
    """
    Get Historify database statistics.

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        stats = get_database_stats()
        return True, {"status": "success", "data": stats}, 200
    except Exception as e:
        logger.exception(f"Error getting stats: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def delete_symbol_data(
    symbol: str, exchange: str, interval: str = None
) -> tuple[bool, dict[str, Any], int]:
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
            return True, {"status": "success", "message": msg}, 200
        else:
            return False, {"status": "error", "message": msg}, 500
    except Exception as e:
        logger.exception(f"Error deleting data: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def bulk_delete_symbol_data(
    symbols: list[dict[str, str]],
) -> tuple[bool, dict[str, Any], int]:
    """
    Delete market data for multiple symbols in a single bulk operation.

    Args:
        symbols: List of dicts with 'symbol' and 'exchange' keys

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        if not symbols:
            return False, {"status": "error", "message": "No symbols provided"}, 400

        deleted, skipped, failed = db_bulk_delete_market_data(symbols)

        total = len(symbols)
        message = f"Deleted {deleted} symbol(s)"
        if skipped > 0:
            message += f", {skipped} had no data"
        if failed:
            message += f", {len(failed)} failed"

        return (
            True,
            {
                "status": "success",
                "message": message,
                "deleted": deleted,
                "skipped": skipped,
                "failed": failed,
                "total": total,
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error bulk deleting data: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def initialize_historify() -> tuple[bool, dict[str, Any], int]:
    """
    Initialize the Historify database.
    Called on app startup to ensure database is ready.

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        init_database()
        return True, {"status": "success", "message": "Historify database initialized"}, 200
    except Exception as e:
        logger.exception(f"Error initializing Historify: {e}")
        return False, {"status": "error", "message": str(e)}, 500


# =============================================================================
# CSV Upload Operations
# =============================================================================

# Valid intervals for data import (common across brokers)
VALID_INTERVALS = {
    "1s",
    "5s",
    "10s",
    "15s",
    "30s",  # Seconds
    "1m",
    "2m",
    "3m",
    "5m",
    "10m",
    "15m",
    "20m",
    "30m",
    "45m",  # Minutes
    "1h",
    "2h",
    "3h",
    "4h",  # Hours
    "D",
    "1D",
    "W",
    "1W",
    "M",
    "1M",  # Days, Weeks, Months
}


def upload_csv_data(
    file_path: str, symbol: str, exchange: str, interval: str
) -> tuple[bool, dict[str, Any], int]:
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
            return (
                False,
                {"status": "error", "message": "Symbol, exchange, and interval are required"},
                400,
            )

        if exchange.upper() not in SUPPORTED_EXCHANGES:
            return (
                False,
                {
                    "status": "error",
                    "message": f"Invalid exchange. Supported: {', '.join(SUPPORTED_EXCHANGES)}",
                },
                400,
            )

        # Validate interval
        if interval not in VALID_INTERVALS:
            return (
                False,
                {
                    "status": "error",
                    "message": f"Invalid interval. Supported: {', '.join(sorted(VALID_INTERVALS))}",
                },
                400,
            )

        success, msg, records = db_import_from_csv(file_path, symbol, exchange, interval)

        if success:
            return (
                True,
                {
                    "status": "success",
                    "message": msg,
                    "symbol": symbol.upper(),
                    "exchange": exchange.upper(),
                    "interval": interval,
                    "records": records,
                },
                200,
            )
        else:
            return False, {"status": "error", "message": msg}, 400

    except Exception as e:
        logger.exception(f"Error uploading CSV: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def upload_parquet_data(
    file_path: str, symbol: str, exchange: str, interval: str
) -> tuple[bool, dict[str, Any], int]:
    """
    Upload Parquet data to the Historify database.

    Args:
        file_path: Path to the uploaded Parquet file
        symbol: Trading symbol
        exchange: Exchange code
        interval: Time interval

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        if not symbol or not exchange or not interval:
            return (
                False,
                {"status": "error", "message": "Symbol, exchange, and interval are required"},
                400,
            )

        if exchange.upper() not in SUPPORTED_EXCHANGES:
            return (
                False,
                {
                    "status": "error",
                    "message": f"Invalid exchange. Supported: {', '.join(SUPPORTED_EXCHANGES)}",
                },
                400,
            )

        # Validate interval
        if interval not in VALID_INTERVALS:
            return (
                False,
                {
                    "status": "error",
                    "message": f"Invalid interval. Supported: {', '.join(sorted(VALID_INTERVALS))}",
                },
                400,
            )

        success, msg, records = db_import_from_parquet(file_path, symbol, exchange, interval)

        if success:
            return (
                True,
                {
                    "status": "success",
                    "message": msg,
                    "symbol": symbol.upper(),
                    "exchange": exchange.upper(),
                    "interval": interval,
                    "records": records,
                },
                200,
            )
        else:
            return False, {"status": "error", "message": msg}, 400

    except Exception as e:
        logger.exception(f"Error uploading Parquet: {e}")
        return False, {"status": "error", "message": str(e)}, 500


# =============================================================================
# FNO Discovery Operations
# =============================================================================

# FNO Exchanges for derivatives
FNO_EXCHANGES = ["NFO", "BFO", "MCX", "CDS"]


def get_fno_underlyings(exchange: str = None) -> tuple[bool, dict[str, Any], int]:
    """
    Get list of FNO underlying symbols.

    Args:
        exchange: Filter by exchange (NFO, BFO, MCX, CDS)

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        from database.symbol import get_distinct_underlyings

        if exchange and exchange.upper() not in FNO_EXCHANGES:
            return (
                False,
                {
                    "status": "error",
                    "message": f"Invalid FNO exchange. Supported: {', '.join(FNO_EXCHANGES)}",
                },
                400,
            )

        underlyings = get_distinct_underlyings(exchange.upper() if exchange else None)

        # Filter out exchange test symbols (e.g. 011NSETEST, 021BSETEST)
        underlyings = [u for u in underlyings if "NSETEST" not in u and "BSETEST" not in u]

        return (
            True,
            {
                "status": "success",
                "data": underlyings,
                "count": len(underlyings),
                "exchange": exchange.upper() if exchange else "ALL",
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error getting FNO underlyings: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def get_fno_expiries(
    underlying: str, exchange: str = "NFO", instrumenttype: str = None
) -> tuple[bool, dict[str, Any], int]:
    """
    Get expiry dates for an underlying symbol.

    Args:
        underlying: Underlying symbol (e.g., 'NIFTY', 'BANKNIFTY')
        exchange: Exchange code (NFO, BFO, MCX, CDS)
        instrumenttype: Filter by 'FUT' or 'OPT' (optional)

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        from database.symbol import get_distinct_expiries

        if exchange.upper() not in FNO_EXCHANGES:
            return (
                False,
                {
                    "status": "error",
                    "message": f"Invalid FNO exchange. Supported: {', '.join(FNO_EXCHANGES)}",
                },
                400,
            )

        expiries = get_distinct_expiries(exchange.upper(), underlying.upper())

        return (
            True,
            {
                "status": "success",
                "data": expiries,
                "count": len(expiries),
                "underlying": underlying.upper(),
                "exchange": exchange.upper(),
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error getting FNO expiries: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def get_fno_chain(
    underlying: str,
    exchange: str = "NFO",
    expiry: str = None,
    instrumenttype: str = None,
    strike_min: float = None,
    strike_max: float = None,
    limit: int = 1000,
) -> tuple[bool, dict[str, Any], int]:
    """
    Get full option/futures chain for an underlying.

    Args:
        underlying: Underlying symbol (e.g., 'NIFTY', 'BANKNIFTY')
        exchange: Exchange code (NFO, BFO, MCX, CDS)
        expiry: Expiry date filter (e.g., '26-DEC-24')
        instrumenttype: 'FUT', 'CE', or 'PE'
        strike_min: Minimum strike price filter
        strike_max: Maximum strike price filter
        limit: Maximum symbols to return

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        from database.symbol import fno_search_symbols_db

        if exchange.upper() not in FNO_EXCHANGES:
            return (
                False,
                {
                    "status": "error",
                    "message": f"Invalid FNO exchange. Supported: {', '.join(FNO_EXCHANGES)}",
                },
                400,
            )

        symbols = fno_search_symbols_db(
            query=None,
            exchange=exchange.upper(),
            expiry=expiry,
            instrumenttype=instrumenttype,
            strike_min=strike_min,
            strike_max=strike_max,
            underlying=underlying.upper(),
            limit=limit,
        )

        return (
            True,
            {
                "status": "success",
                "data": symbols,
                "count": len(symbols),
                "underlying": underlying.upper(),
                "exchange": exchange.upper(),
                "expiry": expiry,
                "instrumenttype": instrumenttype,
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error getting FNO chain: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def get_futures_chain(underlying: str, exchange: str = "NFO") -> tuple[bool, dict[str, Any], int]:
    """
    Get all futures contracts for an underlying across all expiries.

    Args:
        underlying: Underlying symbol (e.g., 'NIFTY', 'BANKNIFTY', 'CRUDEOIL')
        exchange: Exchange code (NFO, BFO, MCX, CDS)

    Returns:
        Tuple of (success, response_data, status_code)
    """
    return get_fno_chain(underlying=underlying, exchange=exchange, instrumenttype="FUT", limit=500)


def get_option_chain_symbols(
    underlying: str,
    exchange: str = "NFO",
    expiry: str = None,
    strike_min: float = None,
    strike_max: float = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Get all option symbols (CE and PE) for an underlying and expiry.

    Args:
        underlying: Underlying symbol (e.g., 'NIFTY', 'BANKNIFTY')
        exchange: Exchange code (NFO, BFO)
        expiry: Expiry date (required for options)
        strike_min: Minimum strike price filter
        strike_max: Maximum strike price filter

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        from database.symbol import fno_search_symbols_db

        if exchange.upper() not in FNO_EXCHANGES:
            return (
                False,
                {
                    "status": "error",
                    "message": f"Invalid FNO exchange. Supported: {', '.join(FNO_EXCHANGES)}",
                },
                400,
            )

        # Get CE options
        ce_symbols = fno_search_symbols_db(
            query=None,
            exchange=exchange.upper(),
            expiry=expiry,
            instrumenttype="CE",
            strike_min=strike_min,
            strike_max=strike_max,
            underlying=underlying.upper(),
            limit=2000,
        )

        # Get PE options
        pe_symbols = fno_search_symbols_db(
            query=None,
            exchange=exchange.upper(),
            expiry=expiry,
            instrumenttype="PE",
            strike_min=strike_min,
            strike_max=strike_max,
            underlying=underlying.upper(),
            limit=2000,
        )

        all_symbols = ce_symbols + pe_symbols

        return (
            True,
            {
                "status": "success",
                "data": all_symbols,
                "count": len(all_symbols),
                "ce_count": len(ce_symbols),
                "pe_count": len(pe_symbols),
                "underlying": underlying.upper(),
                "exchange": exchange.upper(),
                "expiry": expiry,
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error getting option chain symbols: {e}")
        return False, {"status": "error", "message": str(e)}, 500


# =============================================================================
# Download Job Operations
# =============================================================================

import random
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

# Job executor pool - shared across all job operations
_job_executor = ThreadPoolExecutor(max_workers=int(os.getenv("HISTORIFY_MAX_WORKERS", "5")))

# Track running jobs for cancellation and pause state
_running_jobs: dict[str, bool] = {}
_paused_jobs: dict[str, threading.Event] = {}  # Event is set when NOT paused

# Lock for thread-safe access to job state dictionaries
_job_state_lock = threading.Lock()


def cleanup_zombie_jobs():
    """
    Clean up zombie jobs on server startup.

    Jobs that are in 'running' or 'paused' state but have no corresponding
    in-memory thread tracking are zombie jobs (likely from a server restart).
    This function marks them as 'failed' so users can retry them.
    """
    from database.historify_db import get_all_download_jobs, update_job_status

    try:
        # Get running jobs
        running_jobs = get_all_download_jobs(status="running", limit=100)
        paused_jobs = get_all_download_jobs(status="paused", limit=100)
        all_active_jobs = running_jobs + paused_jobs
        zombie_count = 0

        for job in all_active_jobs:
            # Check if there's an in-memory tracking for this job
            with _job_state_lock:
                has_in_memory_state = job["id"] in _running_jobs or job["id"] in _paused_jobs

            if not has_in_memory_state:
                # This is a zombie job - mark it as failed
                update_job_status(job["id"], "failed")
                logger.warning(f"Marked zombie job {job['id']} as failed (was: {job['status']})")
                zombie_count += 1

        if zombie_count > 0:
            logger.info(f"Cleaned up {zombie_count} zombie job(s)")

    except Exception as e:
        logger.exception(f"Error cleaning up zombie jobs: {e}")


def create_and_start_job(
    job_type: str,
    symbols: list[dict[str, str]],
    interval: str,
    start_date: str,
    end_date: str,
    api_key: str,
    config: dict[str, Any] = None,
    incremental: bool = False,
) -> tuple[bool, dict[str, Any], int]:
    """
    Create a download job and start processing in background.

    Args:
        job_type: Type of job ('watchlist', 'option_chain', 'futures_chain', 'custom')
        symbols: List of dicts with 'symbol' and 'exchange' keys
        interval: Time interval for download
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        api_key: OpenAlgo API key
        config: Optional configuration dict
        incremental: If True, only download data after last available timestamp

    Returns:
        Tuple of (success, response_data, status_code)
    """
    from database.historify_db import create_download_job, update_job_status

    try:
        if not symbols:
            return False, {"status": "error", "message": "No symbols provided"}, 400

        # Generate unique job ID
        job_id = str(uuid.uuid4())[:8]

        # Merge incremental flag into config
        job_config = config or {}
        job_config["incremental"] = incremental

        # Create job in database
        success, msg = create_download_job(
            job_id=job_id,
            job_type=job_type,
            symbols=symbols,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            config=job_config,
        )

        if not success:
            return False, {"status": "error", "message": msg}, 500

        # Mark job as running and initialize pause event (set = not paused)
        # Use lock for thread-safe initialization
        with _job_state_lock:
            _running_jobs[job_id] = True
            _paused_jobs[job_id] = threading.Event()
            _paused_jobs[job_id].set()  # Not paused initially

        # Start background processing
        _job_executor.submit(_process_download_job, job_id, api_key)

        return (
            True,
            {
                "status": "success",
                "message": f"Job started with {len(symbols)} symbols",
                "job_id": job_id,
                "total_symbols": len(symbols),
                "incremental": incremental,
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error creating job: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def _process_download_job(job_id: str, api_key: str):
    """
    Background job processor with Socket.IO progress updates.

    This runs in a separate thread and downloads data for each symbol.
    Features:
    - Random delay (1-3 seconds) between downloads to avoid rate limits
    - Pause/resume support via threading.Event
    - Checkpoint support - resumes from pending items
    - Incremental download - only fetches data after last available timestamp
    """
    import json

    from database.historify_db import (
        get_data_range,
        get_download_job,
        get_job_items,
        update_job_item_status,
        update_job_progress,
        update_job_status,
        upsert_symbol_metadata,
    )

    try:
        # Get job details
        job = get_download_job(job_id)
        if not job:
            logger.error(f"Job {job_id} not found")
            return

        # Update status to running
        update_job_status(job_id, "running")

        # Get job items - only pending or downloading (for resume)
        items = get_job_items(job_id)
        if not items:
            logger.error(f"No items found for job {job_id}")
            update_job_status(job_id, "failed", "No items to process")
            return

        # Filter to only pending items (for checkpoint resume)
        pending_items = [item for item in items if item["status"] in ("pending", "downloading")]

        # Parse config for incremental flag
        config = {}
        if job.get("config"):
            try:
                config = (
                    json.loads(job["config"]) if isinstance(job["config"], str) else job["config"]
                )
            except:
                config = {}

        incremental = config.get("incremental", False)

        # Get delay settings from environment (min and max seconds)
        delay_min = float(os.getenv("HISTORIFY_DELAY_MIN", "1"))
        delay_max = float(os.getenv("HISTORIFY_DELAY_MAX", "3"))

        # Count already completed items
        already_completed = sum(1 for item in items if item["status"] == "success")
        already_failed = sum(1 for item in items if item["status"] == "error")
        completed = already_completed
        failed = already_failed

        total_items = len(items)
        processed_count = already_completed + already_failed

        for item in pending_items:
            # Check for cancellation with thread-safe access
            with _job_state_lock:
                is_cancelled = not _running_jobs.get(job_id, False)
                pause_event = _paused_jobs.get(job_id)

            if is_cancelled:
                logger.info(f"Job {job_id} cancelled")
                update_job_status(job_id, "cancelled")
                _cleanup_job(job_id)
                return

            # Check for pause - wait if paused
            if pause_event:
                while not pause_event.is_set():
                    # Emit paused status
                    _emit_job_paused(job_id, processed_count, total_items)
                    # Wait for resume signal (check every 1 second)
                    pause_event.wait(timeout=1.0)
                    # Check for cancellation while paused (with lock)
                    with _job_state_lock:
                        is_cancelled = not _running_jobs.get(job_id, False)
                    if is_cancelled:
                        logger.info(f"Job {job_id} cancelled while paused")
                        update_job_status(job_id, "cancelled")
                        _cleanup_job(job_id)
                        return

            # Update item status
            update_job_item_status(item["id"], "downloading")

            processed_count += 1
            # Emit progress via Socket.IO
            _emit_progress(job_id, processed_count, total_items, item["symbol"])

            try:
                # Determine date ranges - use incremental if enabled
                requested_start = job["start_date"]
                requested_end = job["end_date"]
                total_records = 0
                download_error = None

                if incremental:
                    # Check existing data range for this symbol
                    data_range = get_data_range(item["symbol"], item["exchange"], job["interval"])

                    if (
                        data_range
                        and data_range.get("first_timestamp")
                        and data_range.get("last_timestamp")
                    ):
                        first_ts = data_range["first_timestamp"]
                        last_ts = data_range["last_timestamp"]
                        first_datetime = datetime.fromtimestamp(first_ts)
                        last_datetime = datetime.fromtimestamp(last_ts)

                        requested_start_dt = datetime.strptime(requested_start, "%Y-%m-%d")
                        requested_end_dt = datetime.strptime(requested_end, "%Y-%m-%d")

                        # Determine what needs to be downloaded:
                        # 1. Data BEFORE existing data (if requested_start < first_timestamp)
                        # 2. Data AFTER existing data (if requested_end > last_timestamp)

                        need_before = requested_start_dt.date() < first_datetime.date()
                        need_after = requested_end_dt.date() > last_datetime.date()

                        # For 1m data, be more precise about timing
                        if job["interval"] == "1m":
                            need_after = requested_end_dt.date() >= last_datetime.date()

                        if not need_before and not need_after:
                            # Data already covers the requested range
                            update_job_item_status(
                                item["id"], "skipped", 0, "Data already covers requested range"
                            )
                            logger.info(
                                f"Skipping {item['symbol']} - data already covers requested range"
                            )
                            continue

                        # Download data BEFORE existing range if needed
                        if need_before:
                            # End date for "before" download is the day before first existing data
                            if job["interval"] == "1m":
                                before_end = first_datetime.strftime("%Y-%m-%d")
                            else:
                                before_end = (first_datetime - timedelta(days=1)).strftime(
                                    "%Y-%m-%d"
                                )

                            if requested_start <= before_end:
                                logger.debug(
                                    f"Incremental (before): {item['symbol']} from {requested_start} to {before_end}"
                                )
                                success_before, response_before, _ = download_data(
                                    symbol=item["symbol"],
                                    exchange=item["exchange"],
                                    interval=job["interval"],
                                    start_date=requested_start,
                                    end_date=before_end,
                                    api_key=api_key,
                                )
                                if success_before:
                                    total_records += response_before.get("records", 0)
                                else:
                                    download_error = response_before.get(
                                        "message", "Error downloading earlier data"
                                    )

                        # Download data AFTER existing range if needed
                        if need_after and download_error is None:
                            # Start date for "after" download
                            if job["interval"] == "1m":
                                after_start = last_datetime.strftime("%Y-%m-%d")
                            else:
                                after_start = (last_datetime + timedelta(days=1)).strftime(
                                    "%Y-%m-%d"
                                )

                            if after_start <= requested_end:
                                logger.debug(
                                    f"Incremental (after): {item['symbol']} from {after_start} to {requested_end}"
                                )
                                success_after, response_after, _ = download_data(
                                    symbol=item["symbol"],
                                    exchange=item["exchange"],
                                    interval=job["interval"],
                                    start_date=after_start,
                                    end_date=requested_end,
                                    api_key=api_key,
                                )
                                if success_after:
                                    total_records += response_after.get("records", 0)
                                else:
                                    download_error = response_after.get(
                                        "message", "Error downloading later data"
                                    )

                        # Update status based on results
                        if download_error:
                            update_job_item_status(
                                item["id"], "error", total_records, download_error
                            )
                            failed += 1
                        else:
                            update_job_item_status(item["id"], "success", total_records)
                            completed += 1
                        continue

                # Non-incremental or no existing data: download full range
                success, response, _ = download_data(
                    symbol=item["symbol"],
                    exchange=item["exchange"],
                    interval=job["interval"],
                    start_date=requested_start,
                    end_date=requested_end,
                    api_key=api_key,
                )

                if success:
                    records = response.get("records", 0)
                    update_job_item_status(item["id"], "success", records)
                    completed += 1
                else:
                    error_msg = response.get("message", "Unknown error")
                    update_job_item_status(item["id"], "error", 0, error_msg)
                    failed += 1

            except Exception as e:
                logger.exception(f"Error downloading {item['symbol']}: {e}")
                update_job_item_status(item["id"], "error", 0, str(e))
                failed += 1

            # Update progress counters in database
            update_job_progress(job_id, completed, failed)

            # Random delay between 1-3 seconds (configurable)
            delay = random.uniform(delay_min, delay_max)
            logger.debug(f"Waiting {delay:.1f}s before next download...")
            time.sleep(delay)

        # Job completed
        final_status = "completed" if failed == 0 else "completed_with_errors"
        update_job_status(job_id, final_status)

        # Emit completion event
        _emit_job_complete(job_id, completed, failed, total_items)

        logger.info(f"Job {job_id} completed: {completed} success, {failed} failed")

        # Cleanup
        _cleanup_job(job_id)

    except Exception as e:
        logger.exception(f"Error processing job {job_id}: {e}")
        update_job_status(job_id, "failed", str(e))
        _cleanup_job(job_id)


def _cleanup_job(job_id: str):
    """Clean up job tracking state with thread-safe access."""
    with _job_state_lock:
        _running_jobs.pop(job_id, None)
        _paused_jobs.pop(job_id, None)


def _emit_progress(job_id: str, current: int, total: int, symbol: str):
    """Emit Socket.IO progress event."""
    try:
        from extensions import socketio

        socketio.emit(
            "historify_progress",
            {
                "job_id": job_id,
                "current": current,
                "total": total,
                "symbol": symbol,
                "percent": round((current / total) * 100, 1),
            },
        )
    except Exception as e:
        logger.debug(f"Could not emit progress: {e}")


def _emit_job_complete(job_id: str, completed: int, failed: int, total: int):
    """Emit Socket.IO job completion event."""
    try:
        from extensions import socketio

        socketio.emit(
            "historify_job_complete",
            {
                "job_id": job_id,
                "completed": completed,
                "failed": failed,
                "total": total,
                "status": "completed" if failed == 0 else "completed_with_errors",
            },
        )
    except Exception as e:
        logger.debug(f"Could not emit job complete: {e}")


def _emit_job_paused(job_id: str, current: int, total: int):
    """Emit Socket.IO job paused event."""
    try:
        from extensions import socketio

        socketio.emit(
            "historify_job_paused",
            {"job_id": job_id, "current": current, "total": total, "status": "paused"},
        )
    except Exception as e:
        logger.debug(f"Could not emit job paused: {e}")


def _emit_job_cancelled(job_id: str):
    """Emit Socket.IO job cancelled event."""
    try:
        from extensions import socketio

        socketio.emit("historify_job_cancelled", {"job_id": job_id, "status": "cancelled"})
    except Exception as e:
        logger.debug(f"Could not emit job cancelled: {e}")


def get_job_status(job_id: str) -> tuple[bool, dict[str, Any], int]:
    """
    Get status of a download job.

    Args:
        job_id: Job identifier

    Returns:
        Tuple of (success, response_data, status_code)
    """
    from database.historify_db import get_download_job, get_job_items

    try:
        job = get_download_job(job_id)
        if not job:
            return False, {"status": "error", "message": "Job not found"}, 404

        items = get_job_items(job_id)

        return True, {"status": "success", "job": job, "items": items}, 200

    except Exception as e:
        logger.exception(f"Error getting job status: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def get_all_jobs(status: str = None, limit: int = 50) -> tuple[bool, dict[str, Any], int]:
    """
    Get all download jobs.

    Args:
        status: Filter by status (optional)
        limit: Max jobs to return

    Returns:
        Tuple of (success, response_data, status_code)
    """
    from database.historify_db import get_all_download_jobs

    try:
        jobs = get_all_download_jobs(status, limit)

        return True, {"status": "success", "data": jobs, "count": len(jobs)}, 200

    except Exception as e:
        logger.exception(f"Error getting jobs: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def cancel_job(job_id: str) -> tuple[bool, dict[str, Any], int]:
    """
    Cancel a running job.

    Args:
        job_id: Job identifier

    Returns:
        Tuple of (success, response_data, status_code)
    """
    from database.historify_db import get_download_job, update_job_status

    try:
        job = get_download_job(job_id)
        if not job:
            return False, {"status": "error", "message": "Job not found"}, 404

        if job["status"] not in ("running", "paused"):
            return (
                False,
                {
                    "status": "error",
                    "message": f"Job is not running or paused (status: {job['status']})",
                },
                400,
            )

        # Immediately update database status to 'cancelled'
        update_job_status(job_id, "cancelled")
        logger.info(f"Job {job_id} cancelled")

        # Use lock for thread-safe state modification
        with _job_state_lock:
            # Signal cancellation to stop the processing thread
            _running_jobs[job_id] = False
            # Resume if paused so thread can exit cleanly
            pause_event = _paused_jobs.get(job_id)
            if pause_event:
                pause_event.set()
            # Clean up in-memory state
            _cleanup_job(job_id)

        # Emit cancellation event to frontend
        _emit_job_cancelled(job_id)

        return True, {"status": "success", "message": "Job cancelled"}, 200

    except Exception as e:
        logger.exception(f"Error cancelling job: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def pause_job(job_id: str) -> tuple[bool, dict[str, Any], int]:
    """
    Pause a running job.

    Args:
        job_id: Job identifier

    Returns:
        Tuple of (success, response_data, status_code)
    """
    from database.historify_db import get_download_job, update_job_status

    try:
        job = get_download_job(job_id)
        if not job:
            return False, {"status": "error", "message": "Job not found"}, 404

        if job["status"] != "running":
            return (
                False,
                {"status": "error", "message": f"Job is not running (status: {job['status']})"},
                400,
            )

        # Use lock for thread-safe state modification
        with _job_state_lock:
            pause_event = _paused_jobs.get(job_id)

            # Check if already paused
            if pause_event and not pause_event.is_set():
                return False, {"status": "error", "message": "Job is already paused"}, 400

            # Signal pause (clear the event)
            if pause_event:
                pause_event.clear()
                update_job_status(job_id, "paused")
                logger.info(f"Job {job_id} paused")
                return True, {"status": "success", "message": "Job paused"}, 200
            else:
                return False, {"status": "error", "message": "Job not found in running jobs"}, 400

    except Exception as e:
        logger.exception(f"Error pausing job: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def resume_job(job_id: str) -> tuple[bool, dict[str, Any], int]:
    """
    Resume a paused job.

    Args:
        job_id: Job identifier

    Returns:
        Tuple of (success, response_data, status_code)
    """
    from database.historify_db import get_download_job, update_job_status

    try:
        job = get_download_job(job_id)
        if not job:
            return False, {"status": "error", "message": "Job not found"}, 404

        if job["status"] != "paused":
            return (
                False,
                {"status": "error", "message": f"Job is not paused (status: {job['status']})"},
                400,
            )

        # Use lock for thread-safe state modification
        with _job_state_lock:
            pause_event = _paused_jobs.get(job_id)
            if pause_event:
                pause_event.set()
                update_job_status(job_id, "running")
                logger.info(f"Job {job_id} resumed")
                return True, {"status": "success", "message": "Job resumed"}, 200
            else:
                return False, {"status": "error", "message": "Job not found in running jobs"}, 400

    except Exception as e:
        logger.exception(f"Error resuming job: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def delete_job(job_id: str) -> tuple[bool, dict[str, Any], int]:
    """
    Delete a job and its items.

    Args:
        job_id: Job identifier

    Returns:
        Tuple of (success, response_data, status_code)
    """
    from database.historify_db import delete_download_job, get_download_job

    try:
        job = get_download_job(job_id)
        if not job:
            return False, {"status": "error", "message": "Job not found"}, 404

        if job["status"] == "running":
            return (
                False,
                {"status": "error", "message": "Cannot delete running job. Cancel it first."},
                400,
            )

        success, msg = delete_download_job(job_id)

        if success:
            return True, {"status": "success", "message": msg}, 200
        else:
            return False, {"status": "error", "message": msg}, 500

    except Exception as e:
        logger.exception(f"Error deleting job: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def retry_failed_items(job_id: str, api_key: str) -> tuple[bool, dict[str, Any], int]:
    """
    Retry failed items in a job.

    Args:
        job_id: Job identifier
        api_key: OpenAlgo API key

    Returns:
        Tuple of (success, response_data, status_code)
    """
    from database.historify_db import get_download_job, get_job_items, update_job_status

    try:
        job = get_download_job(job_id)
        if not job:
            return False, {"status": "error", "message": "Job not found"}, 404

        if job["status"] == "running":
            return False, {"status": "error", "message": "Job is already running"}, 400

        # Get failed items
        failed_items = get_job_items(job_id, status="error")
        if not failed_items:
            return True, {"status": "success", "message": "No failed items to retry"}, 200

        # Reset failed items to pending
        from database.historify_db import update_job_item_status

        for item in failed_items:
            update_job_item_status(item["id"], "pending")

        # Reset job counters
        update_job_status(job_id, "pending")

        # Mark job as running with thread-safe access
        with _job_state_lock:
            _running_jobs[job_id] = True
            _paused_jobs[job_id] = threading.Event()
            _paused_jobs[job_id].set()  # Not paused initially

        # Start background processing
        _job_executor.submit(_process_download_job, job_id, api_key)

        return (
            True,
            {
                "status": "success",
                "message": f"Retrying {len(failed_items)} failed items",
                "retry_count": len(failed_items),
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error retrying job: {e}")
        return False, {"status": "error", "message": str(e)}, 500


# =============================================================================
# Bulk Metadata Operations
# =============================================================================


def enrich_and_save_metadata(symbols: list[dict[str, str]]) -> tuple[bool, dict[str, Any], int]:
    """
    Fetch metadata from master contract cache and save to historify metadata table.

    Args:
        symbols: List of dicts with 'symbol' and 'exchange' keys

    Returns:
        Tuple of (success, response_data, status_code)
    """
    from database.historify_db import upsert_symbol_metadata

    try:
        from database.token_db_enhanced import get_symbol_from_cache

        enriched = []
        for sym in symbols:
            try:
                # Try to get metadata from master contract cache
                cached = get_symbol_from_cache(sym["symbol"].upper(), sym["exchange"].upper())
                if cached:
                    enriched.append(
                        {
                            "symbol": cached.get("symbol"),
                            "exchange": cached.get("exchange"),
                            "name": cached.get("name"),
                            "expiry": cached.get("expiry"),
                            "strike": cached.get("strike"),
                            "lotsize": cached.get("lotsize"),
                            "instrumenttype": cached.get("instrumenttype"),
                            "tick_size": cached.get("tick_size"),
                        }
                    )
                else:
                    # Just save basic info
                    enriched.append(
                        {"symbol": sym["symbol"].upper(), "exchange": sym["exchange"].upper()}
                    )
            except Exception:
                enriched.append(
                    {"symbol": sym["symbol"].upper(), "exchange": sym["exchange"].upper()}
                )

        # Save to database
        count = upsert_symbol_metadata(enriched)

        return (
            True,
            {
                "status": "success",
                "message": f"Enriched metadata for {count} symbols",
                "count": count,
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error enriching metadata: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def get_catalog_with_metadata_service() -> tuple[bool, dict[str, Any], int]:
    """
    Get data catalog enriched with symbol metadata.

    Returns:
        Tuple of (success, response_data, status_code)
    """
    from database.historify_db import get_catalog_with_metadata

    try:
        catalog = get_catalog_with_metadata()

        # Convert timestamps to dates
        for item in catalog:
            if item.get("first_timestamp"):
                item["first_date"] = datetime.fromtimestamp(item["first_timestamp"]).strftime(
                    "%Y-%m-%d"
                )
            if item.get("last_timestamp"):
                item["last_date"] = datetime.fromtimestamp(item["last_timestamp"]).strftime(
                    "%Y-%m-%d"
                )

        return True, {"status": "success", "data": catalog, "count": len(catalog)}, 200

    except Exception as e:
        logger.exception(f"Error getting catalog with metadata: {e}")
        return False, {"status": "error", "message": str(e)}, 500


def get_catalog_grouped_service(group_by: str = "underlying") -> tuple[bool, dict[str, Any], int]:
    """
    Get data catalog grouped by underlying or exchange.

    Args:
        group_by: 'underlying' or 'exchange'

    Returns:
        Tuple of (success, response_data, status_code)
    """
    from database.historify_db import get_catalog_grouped

    try:
        grouped = get_catalog_grouped(group_by)

        # Convert timestamps to dates in each group
        for key, items in grouped.items():
            for item in items:
                if item.get("first_timestamp"):
                    item["first_date"] = datetime.fromtimestamp(item["first_timestamp"]).strftime(
                        "%Y-%m-%d"
                    )
                if item.get("last_timestamp"):
                    item["last_date"] = datetime.fromtimestamp(item["last_timestamp"]).strftime(
                        "%Y-%m-%d"
                    )

        return (
            True,
            {
                "status": "success",
                "data": grouped,
                "group_by": group_by,
                "group_count": len(grouped),
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error getting grouped catalog: {e}")
        return False, {"status": "error", "message": str(e)}, 500


# =============================================================================
# Module Initialization
# =============================================================================

# Clean up any zombie jobs from previous server runs
# This runs once when the module is first imported
try:
    cleanup_zombie_jobs()
except Exception as e:
    logger.exception(f"Failed to cleanup zombie jobs on startup: {e}")
