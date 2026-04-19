# services/replay_data_service.py
"""
Replay Data Service

Handles ZIP file uploads for market data (NSE CM bhavcopy, FO bhavcopy, intraday 1m)
and imports into Historify DuckDB for replay-based paper trading.
"""

import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime
from typing import Any

import pandas as pd
import pytz

from database.historify_db import get_connection, upsert_market_data
from utils.logging import get_logger

logger = get_logger(__name__)

# IST timezone
IST = pytz.timezone("Asia/Kolkata")

# Maximum allowed ZIP file size (default 200MB, configurable via env)
MAX_ZIP_SIZE = int(os.getenv("REPLAY_MAX_ZIP_SIZE_MB", "200")) * 1024 * 1024

# Allowed file extensions inside ZIP
ALLOWED_EXTENSIONS = {".csv", ".txt"}

# Valid NSE CM series: EQ=Equity, BE=Book Entry, BZ=Z-category
VALID_CM_SERIES = {'EQ', 'BE', 'BZ'}


def validate_zip_file(file_storage) -> tuple[bool, str]:
    """
    Validate an uploaded ZIP file.

    Args:
        file_storage: Flask FileStorage object

    Returns:
        (is_valid, error_message)
    """
    if not file_storage or not file_storage.filename:
        return False, "No file provided"

    # Check extension
    if not file_storage.filename.lower().endswith(".zip"):
        return False, "Only .zip files are accepted"

    # Check file size by reading content length
    file_storage.seek(0, 2)  # Seek to end
    size = file_storage.tell()
    file_storage.seek(0)  # Reset to beginning

    if size > MAX_ZIP_SIZE:
        max_mb = MAX_ZIP_SIZE // (1024 * 1024)
        return False, f"File too large. Maximum size is {max_mb}MB"

    if size == 0:
        return False, "File is empty"

    return True, ""


def _safe_extract_csvs(zip_path: str) -> tuple[list[str], str]:
    """
    Safely extract CSV files from a ZIP, with zip-slip protection.

    Returns:
        (list_of_csv_paths, temp_dir_path)
    """
    temp_dir = tempfile.mkdtemp(prefix="openalgo_replay_")
    csv_files = []

    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for member in zf.infolist():
                # Skip directories
                if member.is_dir():
                    continue

                # Get filename without path (zip-slip protection)
                filename = os.path.basename(member.filename)
                if not filename:
                    continue

                # Check extension
                _, ext = os.path.splitext(filename.lower())
                if ext not in ALLOWED_EXTENSIONS:
                    logger.warning(f"Skipping non-CSV file in ZIP: {member.filename}")
                    continue

                # Zip-slip protection: ensure the resolved path is within temp_dir
                target_path = os.path.join(temp_dir, filename)
                target_path = os.path.realpath(target_path)
                if not target_path.startswith(os.path.realpath(temp_dir)):
                    logger.warning(f"Zip-slip attempt detected, skipping: {member.filename}")
                    continue

                # Extract the file
                with zf.open(member) as source, open(target_path, 'wb') as target:
                    target.write(source.read())

                csv_files.append(target_path)

        return csv_files, temp_dir

    except zipfile.BadZipFile:
        # Clean up on error
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise ValueError("Invalid or corrupt ZIP file")


def _cleanup_temp_dir(temp_dir: str):
    """Remove temporary directory and all contents."""
    try:
        shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception as e:
        logger.warning(f"Failed to cleanup temp dir {temp_dir}: {e}")


def _parse_nse_date(date_str: str) -> datetime:
    """Parse various NSE date formats to datetime."""
    date_str = str(date_str).strip()

    # Try common NSE date formats
    formats = [
        "%d-%b-%Y",    # 01-Jan-2024  (FO bhavcopy expiry column)
        "%d-%B-%Y",    # 01-January-2024
        "%Y-%m-%d",    # 2024-01-01
        "%d/%m/%Y",    # 01/01/2024
        "%d-%m-%Y",    # 01-01-2024
        "%Y%m%d",      # 20240101
        "%d%b%Y",      # 01JAN2024  (NSE CM bhav filename: cm01JAN2024bhav.csv)
        "%d%b%y",      # 01JAN24
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    raise ValueError(f"Cannot parse date: {date_str}")


def _date_to_epoch(dt: datetime) -> int:
    """Convert a datetime to epoch seconds (IST-aware, set to market close 15:30)."""
    if dt.tzinfo is None:
        dt = IST.localize(dt.replace(hour=15, minute=30, second=0, microsecond=0))
    return int(dt.timestamp())


def _format_strike_price(strike) -> str:
    """Format a strike price value, removing trailing .0 for whole numbers."""
    strike_val = float(strike) if strike and str(strike) != 'nan' else 0
    if strike_val == int(strike_val):
        return str(int(strike_val))
    return str(strike_val)


def _extract_date_from_filename(basename: str) -> int | None:
    """
    Extract a date epoch from an NSE filename using multiple date patterns.

    Tries (in order):
    1. DDMonYYYY  – e.g. 01JAN2024  (classic NSE bhav naming)
    2. DDMMYYYY   – e.g. 17042026   (newer NSE CM package, pr*.csv)
    3. DDMMYY     – e.g. 170426     (newer NSE FO package, fo*.csv)

    Returns epoch seconds (IST 15:30) or None if no pattern matched.
    """
    # 1. DDMonYYYY  (e.g. 01JAN2024)
    match = re.search(r'(\d{2}[A-Za-z]{3}\d{4})', basename)
    if match:
        try:
            dt = _parse_nse_date(match.group(1).upper())
            return _date_to_epoch(dt)
        except ValueError:
            pass

    # 2. DDMMYYYY  (e.g. 17042026)
    match = re.search(r'(\d{8})', basename)
    if match:
        try:
            dt = datetime.strptime(match.group(1), '%d%m%Y')
            return _date_to_epoch(dt)
        except ValueError:
            pass

    # 3. DDMMYY  (e.g. 170426)
    match = re.search(r'(\d{6})', basename)
    if match:
        try:
            dt = datetime.strptime(match.group(1), '%d%m%y')
            return _date_to_epoch(dt)
        except ValueError:
            pass

    return None


def _parse_contract_descriptor(contract_d: str) -> tuple:
    """
    Parse an NSE FO contract descriptor (CONTRACT_D column).

    Examples:
    - 'FUTSTK SBIN 27-APR-2025'
    - 'FUTIDX NIFTY 27-APR-2025'
    - 'OPTSTK SBIN 27-APR-2025 500.00 CE'
    - 'OPTIDX NIFTY 27-APR-2025 22000.00 CE'

    Returns:
        (instrument, symbol, expiry_str, strike_str, option_type)
        All elements are strings; empty string when not applicable.
    """
    try:
        parts = str(contract_d).strip().split()
        if len(parts) < 3:
            return ('', '', '', '', '')

        instrument = parts[0].upper()
        symbol = parts[1].upper()
        expiry = parts[2]
        strike = ''
        opt_type = ''

        if len(parts) >= 5:
            strike = parts[3]
            opt_type = parts[4].upper()

        return (instrument, symbol, expiry, strike, opt_type)
    except Exception:
        return ('', '', '', '', '')


def import_cm_bhavcopy_zip(zip_path: str) -> dict[str, Any]:
    """
    Import NSE CM (Cash Market) Bhavcopy ZIP into DuckDB.

    NSE CM bhavcopy CSVs typically have columns like:
    SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, LAST, PREVCLOSE, TOTTRDQTY, TOTTRDVAL,
    TIMESTAMP, TOTALTRADES, ISIN

    We filter for EQ series only and store as interval='D', exchange='NSE'.

    Returns:
        dict with import stats
    """
    stats = {
        "upload_type": "CM_BHAVCOPY",
        "rows_upserted": 0,
        "symbols_count": 0,
        "min_timestamp": None,
        "max_timestamp": None,
        "errors": [],
        "files_processed": 0,
    }

    csv_files = []
    temp_dir = None

    try:
        csv_files, temp_dir = _safe_extract_csvs(zip_path)

        if not csv_files:
            stats["errors"].append("No CSV files found in ZIP")
            return stats

        all_rows = []

        for csv_path in csv_files:
            try:
                basename = os.path.basename(csv_path)
                _, ext = os.path.splitext(basename.lower())

                # Try reading with different encodings
                for encoding in ['utf-8', 'latin-1', 'cp1252']:
                    try:
                        df = pd.read_csv(csv_path, encoding=encoding)
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    stats["errors"].append(f"Cannot read {basename}: encoding error")
                    continue

                # Normalize column names (strip whitespace, uppercase)
                df.columns = df.columns.str.strip().str.upper()

                # Detect CM bhavcopy format — try alternative column names first
                required_cols = {'SYMBOL', 'OPEN', 'HIGH', 'LOW', 'CLOSE'}
                col_map = {}
                for col in df.columns:
                    col_lower = col.lower().strip()
                    if 'symbol' in col_lower or 'tckr' in col_lower or 'tkr' in col_lower:
                        col_map[col] = 'SYMBOL'
                    elif col_lower in ('open', 'open_price', 'openprc', 'open price'):
                        col_map[col] = 'OPEN'
                    elif col_lower in ('high', 'high_price', 'highprc', 'high price'):
                        col_map[col] = 'HIGH'
                    elif col_lower in ('low', 'low_price', 'lowprc', 'low price'):
                        col_map[col] = 'LOW'
                    elif col_lower in ('close', 'close_price', 'closeprc', 'close price'):
                        col_map[col] = 'CLOSE'
                    elif col_lower in ('volume', 'tottrdqty', 'ttl_trd_qnty',
                                       'net_trdqty', 'net traded qty'):
                        col_map[col] = 'VOLUME'
                    elif col_lower in ('timestamp', 'trade_date', 'trd_dt', 'date',
                                       'trade date'):
                        col_map[col] = 'DATE'

                if col_map:
                    df = df.rename(columns=col_map)

                # Fallback: 'SECURITY' → SYMBOL for NSE CM pr*.csv format
                if 'SYMBOL' not in df.columns and 'SECURITY' in df.columns:
                    df = df.rename(columns={'SECURITY': 'SYMBOL'})

                if not required_cols.issubset(set(df.columns)):
                    # Only warn when the file has some OHLCV-like columns; otherwise
                    # skip silently (e.g. bcXX.csv, hlXX.csv, readme.txt, etc.)
                    ohlcv_hint = {'OPEN', 'HIGH', 'LOW', 'CLOSE'}
                    if ohlcv_hint.intersection(set(df.columns)):
                        stats["errors"].append(
                            f"File {basename}: Missing required columns. "
                            f"Found: {list(df.columns)}"
                        )
                    continue

                # Filter for EQ series if SERIES column exists
                if 'SERIES' in df.columns:
                    df = df[df['SERIES'].str.strip().isin(VALID_CM_SERIES)]

                if df.empty:
                    continue

                # Parse date
                date_col = None
                for col_name in ['DATE', 'TIMESTAMP', 'TRADE_DATE', 'TRD_DT']:
                    if col_name in df.columns:
                        date_col = col_name
                        break

                if date_col:
                    df['timestamp'] = df[date_col].apply(lambda x: _date_to_epoch(_parse_nse_date(x)))
                else:
                    # Try to extract date from filename
                    # Supports DDMonYYYY (cm01JAN2024), DDMMYYYY (pr17042026), DDMMYY (fo170426)
                    epoch = _extract_date_from_filename(basename)
                    if epoch is not None:
                        df['timestamp'] = epoch
                    else:
                        stats["errors"].append(f"File {basename}: No date column found")
                        continue

                # Map volume
                if 'VOLUME' not in df.columns:
                    for vol_col in ['TOTTRDQTY', 'TTL_TRD_QNTY', 'TOTAL_TRADED_QUANTITY',
                                    'NET_TRDQTY', 'NET TRADED QTY']:
                        if vol_col in df.columns:
                            df['VOLUME'] = df[vol_col]
                            break
                    else:
                        df['VOLUME'] = 0

                # Build normalized rows
                normalized = pd.DataFrame({
                    'timestamp': df['timestamp'],
                    'open': pd.to_numeric(df['OPEN'], errors='coerce'),
                    'high': pd.to_numeric(df['HIGH'], errors='coerce'),
                    'low': pd.to_numeric(df['LOW'], errors='coerce'),
                    'close': pd.to_numeric(df['CLOSE'], errors='coerce'),
                    'volume': pd.to_numeric(df['VOLUME'], errors='coerce').fillna(0).astype('int64'),
                    'oi': 0,
                    'symbol': df['SYMBOL'].str.strip().str.upper(),
                })

                # Drop invalid OHLC rows
                normalized = normalized.dropna(subset=['open', 'high', 'low', 'close'])

                if not normalized.empty:
                    all_rows.append(normalized)
                    stats["files_processed"] += 1

            except Exception as e:
                _basename = os.path.basename(csv_path)
                _, _ext = os.path.splitext(_basename.lower())
                # Silently skip non-CSV files and bare parse/tokenization errors
                # (e.g. readme.txt, an*.txt, bm*.txt found in NSE CM package ZIPs)
                if _ext != '.csv' or isinstance(e, pd.errors.ParserError):
                    logger.debug(f"Skipping non-data file {_basename}: {e}")
                else:
                    stats["errors"].append(f"Error processing {_basename}: {str(e)}")

        if all_rows:
            combined = pd.concat(all_rows, ignore_index=True)

            # Upsert per symbol for proper catalog tracking (using groupby for efficiency)
            total_upserted = 0

            for symbol, group_df in combined.groupby('symbol'):
                sym_df = group_df.drop(columns=['symbol']).copy()
                try:
                    count = upsert_market_data(sym_df, symbol, 'NSE', 'D')
                    total_upserted += count
                except Exception as e:
                    stats["errors"].append(f"Error upserting {symbol}: {str(e)}")

            stats["rows_upserted"] = total_upserted
            stats["symbols_count"] = combined['symbol'].nunique()

            timestamps = combined['timestamp'].dropna()
            if not timestamps.empty:
                stats["min_timestamp"] = int(timestamps.min())
                stats["max_timestamp"] = int(timestamps.max())

        return stats

    finally:
        if temp_dir:
            _cleanup_temp_dir(temp_dir)


def import_fo_bhavcopy_zip(zip_path: str) -> dict[str, Any]:
    """
    Import NSE FO (F&O) Bhavcopy ZIP into DuckDB.

    NSE FO bhavcopy CSVs typically have columns like:
    INSTRUMENT, SYMBOL, EXPIRY_DT, STRIKE_PR, OPTION_TYP, OPEN, HIGH, LOW, CLOSE,
    SETTLE_PR, CONTRACTS, VAL_INLAKH, OPEN_INT, CHG_IN_OI, TIMESTAMP

    Store as interval='D', exchange='NFO'.
    """
    stats = {
        "upload_type": "FO_BHAVCOPY",
        "rows_upserted": 0,
        "symbols_count": 0,
        "min_timestamp": None,
        "max_timestamp": None,
        "errors": [],
        "files_processed": 0,
    }

    csv_files = []
    temp_dir = None

    try:
        csv_files, temp_dir = _safe_extract_csvs(zip_path)

        if not csv_files:
            stats["errors"].append("No CSV files found in ZIP")
            return stats

        all_rows = []

        for csv_path in csv_files:
            try:
                basename = os.path.basename(csv_path)
                _, ext = os.path.splitext(basename.lower())

                for encoding in ['utf-8', 'latin-1', 'cp1252']:
                    try:
                        df = pd.read_csv(csv_path, encoding=encoding)
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    stats["errors"].append(f"Cannot read {basename}: encoding error")
                    continue

                df.columns = df.columns.str.strip().str.upper()

                # --- New NSE FO format: CONTRACT_D descriptor column ---
                # Newer NSE FO bhav ZIPs export from DBF/SHX with 10-char field names.
                # CONTRACT_D = full contract descriptor, e.g.:
                #   'FUTSTK SBIN 27-APR-2025'
                #   'OPTIDX NIFTY 27-APR-2025 22000.00 CE'
                if 'CONTRACT_D' in df.columns:
                    parsed = df['CONTRACT_D'].apply(_parse_contract_descriptor)
                    df['INSTRUMENT'] = parsed.apply(lambda x: x[0])
                    df['SYMBOL'] = parsed.apply(lambda x: x[1])
                    df['EXPIRY_DT'] = parsed.apply(lambda x: x[2])
                    df['STRIKE_PR'] = parsed.apply(lambda x: x[3])
                    df['OPTION_TYP'] = parsed.apply(lambda x: x[4])
                    # Rename truncated column names produced by the DBF export
                    _cd_rename = {
                        'CLOSE_PRIC': 'CLOSE',    # CLOSE_PRICE → 10 chars
                        'OI_NO_CON': 'OI',         # OI_NO_OF_CONTRACTS
                        'TRADED_QUA': 'VOLUME',    # TRADED_QUANTITY
                    }
                    df = df.rename(columns={k: v for k, v in _cd_rename.items() if k in df.columns})

                # FO bhavcopy required columns
                required_cols = {'SYMBOL', 'OPEN', 'HIGH', 'LOW', 'CLOSE'}

                # Try column mapping for alternative names
                col_map = {}
                for col in df.columns:
                    col_lower = col.lower().strip()
                    if col_lower in ('symbol', 'tckrsymb'):
                        col_map[col] = 'SYMBOL'
                    elif col_lower in ('open', 'open_price', 'openprc'):
                        col_map[col] = 'OPEN'
                    elif col_lower in ('high', 'high_price', 'highprc'):
                        col_map[col] = 'HIGH'
                    elif col_lower in ('low', 'low_price', 'lowprc'):
                        col_map[col] = 'LOW'
                    elif col_lower in ('close', 'close_price', 'closeprc'):
                        col_map[col] = 'CLOSE'
                    elif col_lower in ('contracts', 'tottrdqty', 'ttl_trd_qnty'):
                        col_map[col] = 'VOLUME'
                    elif col_lower in ('open_int', 'oi', 'open_interest', 'opnlntrst'):
                        col_map[col] = 'OI'
                    elif col_lower in ('timestamp', 'trade_date', 'trd_dt', 'date'):
                        col_map[col] = 'DATE'
                    elif col_lower in ('expiry_dt', 'xpry_date', 'expiry_date', 'expiry'):
                        col_map[col] = 'EXPIRY_DT'
                    elif col_lower in ('strike_pr', 'strk_price', 'strike_price', 'strike'):
                        col_map[col] = 'STRIKE_PR'
                    elif col_lower in ('option_typ', 'optn_tp', 'option_type'):
                        col_map[col] = 'OPTION_TYP'
                    elif col_lower in ('instrument', 'instrm_tp'):
                        col_map[col] = 'INSTRUMENT'

                if col_map:
                    df = df.rename(columns=col_map)

                if not required_cols.issubset(set(df.columns)):
                    # Only warn when the file has OHLCV-like or CONTRACT_D columns;
                    # silently skip unrelated files inside the ZIP.
                    ohlcv_hint = {'OPEN', 'HIGH', 'LOW', 'CLOSE', 'CONTRACT_D'}
                    if ohlcv_hint.intersection(set(df.columns)):
                        stats["errors"].append(
                            f"File {basename}: Missing required columns. "
                            f"Found: {list(df.columns)}"
                        )
                    continue

                if df.empty:
                    continue

                # Build full F&O symbol name (e.g., NIFTY28MAR2420800CE)
                def build_fo_symbol(row):
                    base = str(row.get('SYMBOL', '')).strip().upper()

                    expiry = str(row.get('EXPIRY_DT', '')).strip()
                    strike = row.get('STRIKE_PR', '')
                    opt_type = str(row.get('OPTION_TYP', '')).strip().upper()
                    instrument = str(row.get('INSTRUMENT', '')).strip().upper()

                    if expiry and expiry not in ('nan', ''):
                        try:
                            exp_dt = _parse_nse_date(expiry)
                            exp_str = exp_dt.strftime('%d%b%y').upper()  # e.g., 28MAR24
                        except ValueError:
                            exp_str = expiry.replace('-', '')

                        if instrument in ('FUTIDX', 'FUTSTK') or opt_type in ('XX', '', 'nan', 'NONE'):
                            return f"{base}{exp_str}FUT"
                        elif opt_type in ('CE', 'PE'):
                            strike_str = _format_strike_price(strike)
                            return f"{base}{exp_str}{strike_str}{opt_type}"

                    return base

                df['full_symbol'] = df.apply(build_fo_symbol, axis=1)

                # Parse date
                date_col = None
                for col_name in ['DATE', 'TIMESTAMP', 'TRADE_DATE', 'TRD_DT']:
                    if col_name in df.columns:
                        date_col = col_name
                        break

                if date_col:
                    df['timestamp'] = df[date_col].apply(lambda x: _date_to_epoch(_parse_nse_date(x)))
                else:
                    # Try to extract date from filename
                    # Supports DDMonYYYY (fo01JAN2024), DDMMYYYY (fo17042026),
                    # and DDMMYY (fo170426 — newer NSE FO package format)
                    epoch = _extract_date_from_filename(basename)
                    if epoch is not None:
                        df['timestamp'] = epoch
                    else:
                        stats["errors"].append(f"File {basename}: No date column found")
                        continue

                # Volume
                if 'VOLUME' not in df.columns:
                    for vol_col in ['CONTRACTS', 'TOTTRDQTY', 'TTL_TRD_QNTY']:
                        if vol_col in df.columns:
                            df['VOLUME'] = df[vol_col]
                            break
                    else:
                        df['VOLUME'] = 0

                # OI
                if 'OI' not in df.columns:
                    for oi_col in ['OPEN_INT', 'OPEN_INTEREST', 'OPNLNTRST']:
                        if oi_col in df.columns:
                            df['OI'] = df[oi_col]
                            break
                    else:
                        df['OI'] = 0

                normalized = pd.DataFrame({
                    'timestamp': df['timestamp'],
                    'open': pd.to_numeric(df['OPEN'], errors='coerce'),
                    'high': pd.to_numeric(df['HIGH'], errors='coerce'),
                    'low': pd.to_numeric(df['LOW'], errors='coerce'),
                    'close': pd.to_numeric(df['CLOSE'], errors='coerce'),
                    'volume': pd.to_numeric(df['VOLUME'], errors='coerce').fillna(0).astype('int64'),
                    'oi': pd.to_numeric(df['OI'], errors='coerce').fillna(0).astype('int64'),
                    'symbol': df['full_symbol'],
                })

                normalized = normalized.dropna(subset=['open', 'high', 'low', 'close'])

                if not normalized.empty:
                    all_rows.append(normalized)
                    stats["files_processed"] += 1

            except Exception as e:
                _basename = os.path.basename(csv_path)
                _, _ext = os.path.splitext(_basename.lower())
                # Silently skip non-CSV files and bare parse/tokenization errors
                if _ext != '.csv' or isinstance(e, pd.errors.ParserError):
                    logger.debug(f"Skipping non-data file {_basename}: {e}")
                else:
                    stats["errors"].append(f"Error processing {_basename}: {str(e)}")

        if all_rows:
            combined = pd.concat(all_rows, ignore_index=True)
            total_upserted = 0

            for symbol, group_df in combined.groupby('symbol'):
                sym_df = group_df.drop(columns=['symbol']).copy()
                try:
                    count = upsert_market_data(sym_df, symbol, 'NFO', 'D')
                    total_upserted += count
                except Exception as e:
                    stats["errors"].append(f"Error upserting {symbol}: {str(e)}")

            stats["rows_upserted"] = total_upserted
            stats["symbols_count"] = combined['symbol'].nunique()

            timestamps = combined['timestamp'].dropna()
            if not timestamps.empty:
                stats["min_timestamp"] = int(timestamps.min())
                stats["max_timestamp"] = int(timestamps.max())

        return stats

    finally:
        if temp_dir:
            _cleanup_temp_dir(temp_dir)


def import_intraday_1m_zip(zip_path: str) -> dict[str, Any]:
    """
    Import intraday 1-minute OHLCV data ZIP into DuckDB.

    Expected CSV columns (flexible mapping):
    - timestamp (epoch seconds or ISO datetime)
    - symbol
    - exchange (NSE/NFO, defaults to NSE if missing)
    - open, high, low, close
    - volume
    - oi (optional)

    Store as interval='1m'.
    """
    stats = {
        "upload_type": "INTRADAY_1M",
        "rows_upserted": 0,
        "symbols_count": 0,
        "min_timestamp": None,
        "max_timestamp": None,
        "errors": [],
        "files_processed": 0,
    }

    csv_files = []
    temp_dir = None

    try:
        csv_files, temp_dir = _safe_extract_csvs(zip_path)

        if not csv_files:
            stats["errors"].append("No CSV files found in ZIP")
            return stats

        all_rows = []

        for csv_path in csv_files:
            try:
                for encoding in ['utf-8', 'latin-1', 'cp1252']:
                    try:
                        df = pd.read_csv(csv_path, encoding=encoding)
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    stats["errors"].append(f"Cannot read {os.path.basename(csv_path)}: encoding error")
                    continue

                df.columns = df.columns.str.strip().str.upper()

                # Column mapping
                col_map = {}
                for col in df.columns:
                    col_lower = col.lower().strip()
                    if col_lower in ('symbol', 'ticker', 'scrip'):
                        col_map[col] = 'SYMBOL'
                    elif col_lower in ('timestamp', 'datetime', 'date', 'time'):
                        col_map[col] = 'TIMESTAMP'
                    elif col_lower in ('open', 'open_price'):
                        col_map[col] = 'OPEN'
                    elif col_lower in ('high', 'high_price'):
                        col_map[col] = 'HIGH'
                    elif col_lower in ('low', 'low_price'):
                        col_map[col] = 'LOW'
                    elif col_lower in ('close', 'close_price'):
                        col_map[col] = 'CLOSE'
                    elif col_lower in ('volume', 'vol', 'qty'):
                        col_map[col] = 'VOLUME'
                    elif col_lower in ('oi', 'open_interest', 'openinterest'):
                        col_map[col] = 'OI'
                    elif col_lower in ('exchange', 'exch'):
                        col_map[col] = 'EXCHANGE'

                if col_map:
                    df = df.rename(columns=col_map)

                required = {'SYMBOL', 'OPEN', 'HIGH', 'LOW', 'CLOSE'}
                if not required.issubset(set(df.columns)):
                    stats["errors"].append(
                        f"File {os.path.basename(csv_path)}: Missing columns. "
                        f"Need: symbol, open, high, low, close. Found: {list(df.columns)}"
                    )
                    continue

                if 'TIMESTAMP' not in df.columns:
                    stats["errors"].append(
                        f"File {os.path.basename(csv_path)}: No timestamp/datetime column found"
                    )
                    continue

                # Parse timestamps
                ts_col = df['TIMESTAMP']
                # Check if numeric (epoch seconds)
                if pd.to_numeric(ts_col, errors='coerce').notna().all():
                    df['timestamp'] = pd.to_numeric(ts_col).astype('int64')
                else:
                    # Parse as datetime string
                    parsed = pd.to_datetime(ts_col, errors='coerce')
                    # Localize to IST if not timezone-aware
                    if parsed.dt.tz is None:
                        parsed = parsed.dt.tz_localize(IST)
                    df['timestamp'] = parsed.astype('int64') // 10**9

                # Exchange (default to NSE)
                if 'EXCHANGE' in df.columns:
                    df['exchange'] = df['EXCHANGE'].str.strip().str.upper()
                else:
                    df['exchange'] = 'NSE'

                # Volume and OI
                if 'VOLUME' not in df.columns:
                    df['VOLUME'] = 0
                if 'OI' not in df.columns:
                    df['OI'] = 0

                normalized = pd.DataFrame({
                    'timestamp': df['timestamp'],
                    'open': pd.to_numeric(df['OPEN'], errors='coerce'),
                    'high': pd.to_numeric(df['HIGH'], errors='coerce'),
                    'low': pd.to_numeric(df['LOW'], errors='coerce'),
                    'close': pd.to_numeric(df['CLOSE'], errors='coerce'),
                    'volume': pd.to_numeric(df['VOLUME'], errors='coerce').fillna(0).astype('int64'),
                    'oi': pd.to_numeric(df['OI'], errors='coerce').fillna(0).astype('int64'),
                    'symbol': df['SYMBOL'].str.strip().str.upper(),
                    'exchange': df['exchange'],
                })

                normalized = normalized.dropna(subset=['open', 'high', 'low', 'close', 'timestamp'])

                if not normalized.empty:
                    all_rows.append(normalized)
                    stats["files_processed"] += 1

            except Exception as e:
                stats["errors"].append(f"Error processing {os.path.basename(csv_path)}: {str(e)}")

        if all_rows:
            combined = pd.concat(all_rows, ignore_index=True)

            # Group by symbol and exchange for upsert
            groups = combined.groupby(['symbol', 'exchange'])
            total_upserted = 0
            unique_symbols = set()

            for (symbol, exchange), group_df in groups:
                sym_df = group_df.drop(columns=['symbol', 'exchange']).copy()
                try:
                    count = upsert_market_data(sym_df, symbol, exchange, '1m')
                    total_upserted += count
                    unique_symbols.add(symbol)
                except Exception as e:
                    stats["errors"].append(f"Error upserting {symbol}@{exchange}: {str(e)}")

            stats["rows_upserted"] = total_upserted
            stats["symbols_count"] = len(unique_symbols)

            timestamps = combined['timestamp'].dropna()
            if not timestamps.empty:
                stats["min_timestamp"] = int(timestamps.min())
                stats["max_timestamp"] = int(timestamps.max())

        return stats

    finally:
        if temp_dir:
            _cleanup_temp_dir(temp_dir)


def process_upload(file_storage, upload_type: str) -> dict[str, Any]:
    """
    Main entry point for processing an uploaded ZIP file.

    Args:
        file_storage: Flask FileStorage object
        upload_type: One of 'CM_BHAVCOPY', 'FO_BHAVCOPY', 'INTRADAY_1M'

    Returns:
        dict with import stats
    """
    # Validate
    valid, error = validate_zip_file(file_storage)
    if not valid:
        return {"status": "error", "message": error}

    # Save to temp file
    temp_fd, temp_path = tempfile.mkstemp(suffix='.zip', prefix='openalgo_upload_')
    try:
        os.close(temp_fd)
        file_storage.save(temp_path)

        # Route to appropriate parser
        if upload_type == 'CM_BHAVCOPY':
            stats = import_cm_bhavcopy_zip(temp_path)
        elif upload_type == 'FO_BHAVCOPY':
            stats = import_fo_bhavcopy_zip(temp_path)
        elif upload_type == 'INTRADAY_1M':
            stats = import_intraday_1m_zip(temp_path)
        else:
            return {"status": "error", "message": f"Invalid upload type: {upload_type}"}

        stats["status"] = "success" if stats["rows_upserted"] > 0 else "warning"
        if stats["rows_upserted"] == 0 and not stats["errors"]:
            stats["message"] = "No data rows found to import"
        elif stats["errors"]:
            stats["message"] = f"Imported with {len(stats['errors'])} warning(s)"
        else:
            stats["message"] = (
                f"Successfully imported {stats['rows_upserted']} rows "
                f"for {stats['symbols_count']} symbols"
            )

        return stats

    except Exception as e:
        logger.exception(f"Error processing upload: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        # Clean up temp file
        try:
            os.unlink(temp_path)
        except OSError:
            pass
