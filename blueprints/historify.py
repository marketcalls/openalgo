# blueprints/historify.py
"""
Historify Blueprint

API routes for historical market data management.
Note: The /historify page is served by react_app.py (React frontend).
"""

import os
import tempfile
import traceback

from flask import Blueprint, Response, jsonify, request, send_file, session

from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

historify_bp = Blueprint("historify_bp", __name__, url_prefix="/historify")


# =============================================================================
# Watchlist API Endpoints
# =============================================================================


@historify_bp.route("/api/watchlist", methods=["GET"])
@check_session_validity
def get_watchlist():
    """Get all symbols in the watchlist."""
    try:
        from services.historify_service import get_watchlist as service_get_watchlist

        success, response, status_code = service_get_watchlist()
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error getting watchlist: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/watchlist", methods=["POST"])
@check_session_validity
def add_watchlist():
    """Add a symbol to the watchlist."""
    try:
        from services.historify_service import add_to_watchlist

        data = request.get_json()
        symbol = data.get("symbol", "").upper()
        exchange = data.get("exchange", "").upper()
        display_name = data.get("display_name")

        success, response, status_code = add_to_watchlist(symbol, exchange, display_name)
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error adding to watchlist: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/watchlist", methods=["DELETE"])
@check_session_validity
def remove_watchlist():
    """Remove a symbol from the watchlist."""
    try:
        from services.historify_service import remove_from_watchlist

        data = request.get_json()
        symbol = data.get("symbol", "").upper()
        exchange = data.get("exchange", "").upper()

        success, response, status_code = remove_from_watchlist(symbol, exchange)
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error removing from watchlist: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/watchlist/bulk/delete", methods=["POST"])
@check_session_validity
def bulk_remove_watchlist():
    """Remove multiple symbols from the watchlist."""
    try:
        from services.historify_service import bulk_remove_from_watchlist

        data = request.get_json()
        symbols = data.get("symbols", [])

        if not symbols:
            return jsonify({"status": "error", "message": "No symbols provided"}), 400

        success, response, status_code = bulk_remove_from_watchlist(symbols)
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error bulk removing from watchlist: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/watchlist/bulk", methods=["POST"])
@check_session_validity
def bulk_add_watchlist():
    """Add multiple symbols to the watchlist."""
    try:
        from services.historify_service import bulk_add_to_watchlist

        data = request.get_json()
        symbols = data.get("symbols", [])

        success, response, status_code = bulk_add_to_watchlist(symbols)
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error bulk adding to watchlist: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


# =============================================================================
# Data Download Endpoints
# =============================================================================


@historify_bp.route("/api/download", methods=["POST"])
@check_session_validity
def download_data():
    """Download historical data for a symbol."""
    try:
        from database.auth_db import get_api_key_for_tradingview
        from services.historify_service import download_data as service_download_data

        data = request.get_json()
        symbol = data.get("symbol", "").upper()
        exchange = data.get("exchange", "").upper()
        interval = data.get("interval", "D")
        start_date = data.get("start_date")
        end_date = data.get("end_date")

        # Get API key for the logged-in user
        user = session.get("user")
        api_key = get_api_key_for_tradingview(user)

        if not api_key:
            return jsonify(
                {
                    "status": "error",
                    "message": "No API key found. Please generate an API key first.",
                }
            ), 400

        success, response, status_code = service_download_data(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            api_key=api_key,
        )
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error downloading data: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/download/watchlist", methods=["POST"])
@check_session_validity
def download_watchlist():
    """Download data for all symbols in the watchlist."""
    try:
        from database.auth_db import get_api_key_for_tradingview
        from services.historify_service import download_watchlist_data

        data = request.get_json()
        interval = data.get("interval", "D")
        start_date = data.get("start_date")
        end_date = data.get("end_date")

        # Get API key for the logged-in user
        user = session.get("user")
        api_key = get_api_key_for_tradingview(user)

        if not api_key:
            return jsonify(
                {
                    "status": "error",
                    "message": "No API key found. Please generate an API key first.",
                }
            ), 400

        success, response, status_code = download_watchlist_data(
            interval=interval, start_date=start_date, end_date=end_date, api_key=api_key
        )
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error downloading watchlist data: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


# =============================================================================
# Data Retrieval Endpoints
# =============================================================================


@historify_bp.route("/api/data", methods=["GET"])
@check_session_validity
def get_chart_data():
    """Get OHLCV data for charting."""
    try:
        from services.historify_service import get_chart_data as service_get_chart_data

        symbol = request.args.get("symbol", "").upper()
        exchange = request.args.get("exchange", "").upper()
        interval = request.args.get("interval", "D")
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")

        success, response, status_code = service_get_chart_data(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
        )
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error getting chart data: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/catalog", methods=["GET"])
@check_session_validity
def get_catalog():
    """Get catalog of all available data."""
    try:
        from services.historify_service import get_data_catalog

        success, response, status_code = get_data_catalog()
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error getting catalog: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/symbol-info", methods=["GET"])
@check_session_validity
def get_symbol_info():
    """Get data availability info for a symbol."""
    try:
        from services.historify_service import get_symbol_data_info

        symbol = request.args.get("symbol", "").upper()
        exchange = request.args.get("exchange", "").upper()
        interval = request.args.get("interval")

        success, response, status_code = get_symbol_data_info(symbol, exchange, interval)
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error getting symbol info: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


# =============================================================================
# Export Endpoints
# =============================================================================


@historify_bp.route("/api/export", methods=["POST"])
@check_session_validity
def export_data():
    """Export data to CSV and return download link."""
    try:
        from services.historify_service import export_data_to_csv

        data = request.get_json()
        symbol = data.get("symbol")
        exchange = data.get("exchange")
        interval = data.get("interval")
        start_date = data.get("start_date")
        end_date = data.get("end_date")

        # Use temp directory for exports
        output_dir = tempfile.gettempdir()

        success, response, status_code = export_data_to_csv(
            output_dir=output_dir,
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
        )

        if success:
            # Store file path in session for download
            session["export_file"] = response.get("file_path")

        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error exporting data: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/export/download", methods=["GET"])
@check_session_validity
def download_export():
    """Download the exported CSV file."""
    file_path = None
    try:
        file_path = session.get("export_file")

        if not file_path or not os.path.exists(file_path):
            return jsonify({"status": "error", "message": "Export file not found"}), 404

        # Validate file is within temp directory (security check)
        temp_dir = tempfile.gettempdir()
        abs_path = os.path.abspath(file_path)
        if not abs_path.startswith(os.path.abspath(temp_dir)):
            return jsonify({"status": "error", "message": "Invalid file path"}), 400

        filename = os.path.basename(file_path)

        # Clean up session before sending (file will be deleted after send)
        session.pop("export_file", None)

        # Use send_file with streaming for memory efficiency
        # Note: We need to read the file since we want to delete it after sending
        # Using a generator to stream and delete after
        def generate_and_cleanup():
            try:
                with open(file_path) as f:
                    while True:
                        chunk = f.read(8192)  # 8KB chunks
                        if not chunk:
                            break
                        yield chunk
            finally:
                # Clean up file after streaming
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                except Exception:
                    pass

        return Response(
            generate_and_cleanup(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.error(f"Error downloading export: {e}")
        traceback.print_exc()
        # Clean up file on error
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        return jsonify({"status": "error", "message": str(e)}), 500


# =============================================================================
# Bulk Export Endpoints (Parquet, ZIP, TXT, CSV)
# =============================================================================


@historify_bp.route("/api/export/preview", methods=["POST"])
@check_session_validity
def get_export_preview():
    """Get preview of what will be exported (record count, size estimate)."""
    try:
        from database.historify_db import get_export_preview as db_get_preview

        data = request.get_json()
        symbols = data.get("symbols")  # Optional list of {symbol, exchange}
        interval = data.get("interval")
        start_date = data.get("start_date")
        end_date = data.get("end_date")

        # Convert dates to timestamps if provided
        start_timestamp = None
        end_timestamp = None
        if start_date:
            from datetime import datetime

            start_timestamp = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp())
        if end_date:
            from datetime import datetime

            # End of day
            end_timestamp = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp()) + 86400

        preview = db_get_preview(
            symbols=symbols,
            interval=interval,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        )

        return jsonify({"status": "success", "data": preview}), 200
    except Exception as e:
        logger.error(f"Error getting export preview: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/export/bulk", methods=["POST"])
@check_session_validity
def bulk_export():
    """Export data in various formats (CSV, TXT, ZIP, Parquet).

    Supports multi-timeframe export where computed intervals (5m, 15m, 30m, 1h)
    are aggregated from 1m data and exported as separate files.
    """
    try:
        from datetime import datetime

        from database.historify_db import (
            export_bulk_csv,
            export_to_parquet,
            export_to_txt,
            export_to_zip,
        )

        data = request.get_json()
        format_type = data.get("format", "csv").lower()
        symbols = data.get("symbols")  # Optional list of {symbol, exchange}
        interval = data.get("interval")  # Single interval (legacy)
        intervals = data.get("intervals")  # Multiple intervals (new)
        start_date = data.get("start_date")
        end_date = data.get("end_date")
        split_by = data.get("split_by", "symbol")  # For ZIP: 'symbol' or 'none'
        compression = data.get("compression", "zstd")  # For Parquet

        # Validate intervals parameter using parse_interval for dynamic validation
        from database.historify_db import parse_interval

        if intervals is not None:
            if not isinstance(intervals, list):
                return jsonify({"status": "error", "message": "intervals must be an array"}), 400
            if len(intervals) == 0:
                return jsonify(
                    {"status": "error", "message": "At least one interval must be specified"}
                ), 400
            intervals = list(set(intervals))  # Remove duplicates
            invalid = [i for i in intervals if parse_interval(i) is None]
            if invalid:
                return jsonify({"status": "error", "message": f"Invalid intervals: {invalid}"}), 400

        # Convert dates to timestamps if provided
        start_timestamp = None
        end_timestamp = None
        if start_date:
            start_timestamp = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp())
        if end_date:
            # End of day
            end_timestamp = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp()) + 86400

        # Generate filename
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        if symbols and len(symbols) == 1:
            base_name = f"historify_{symbols[0]['symbol']}_{timestamp_str}"
        else:
            base_name = f"historify_export_{timestamp_str}"

        # Check if any interval requires aggregation from 1m data (custom intervals)
        from database.historify_db import is_custom_interval

        # Force ZIP format if:
        # 1. Multiple intervals selected, OR
        # 2. Any computed/custom interval is selected (since only ZIP supports aggregation)
        has_computed = intervals and any(is_custom_interval(i) for i in intervals)
        if (intervals and len(intervals) > 1) or has_computed:
            format_type = "zip"

        # Create temp file path
        if format_type == "parquet":
            file_ext = ".parquet"
        elif format_type == "zip":
            file_ext = ".zip"
        elif format_type == "txt":
            file_ext = ".txt"
        else:
            file_ext = ".csv"

        output_path = os.path.join(tempfile.gettempdir(), f"{base_name}{file_ext}")

        # Execute export based on format
        if format_type == "parquet":
            success, message, record_count = export_to_parquet(
                output_path=output_path,
                symbols=symbols,
                interval=intervals[0] if intervals else interval,
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
                compression=compression,
            )
            mime_type = "application/octet-stream"
        elif format_type == "zip":
            success, message, record_count = export_to_zip(
                output_path=output_path,
                symbols=symbols,
                intervals=intervals if intervals else ([interval] if interval else None),
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
                split_by=split_by,
            )
            mime_type = "application/zip"
        elif format_type == "txt":
            success, message, record_count = export_to_txt(
                output_path=output_path,
                symbols=symbols,
                interval=intervals[0] if intervals else interval,
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
            )
            mime_type = "text/plain"
        else:  # csv
            success, message, record_count = export_bulk_csv(
                output_path=output_path,
                symbols=symbols if symbols else [],
                interval=intervals[0] if intervals else interval,
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
            )
            mime_type = "text/csv"

        if not success:
            return jsonify({"status": "error", "message": message}), 400

        # Store file path in session for download
        session["bulk_export_file"] = output_path
        session["bulk_export_mime"] = mime_type
        session["bulk_export_name"] = f"{base_name}{file_ext}"

        return jsonify(
            {
                "status": "success",
                "message": message,
                "record_count": record_count,
                "filename": f"{base_name}{file_ext}",
            }
        ), 200

    except Exception as e:
        logger.error(f"Error in bulk export: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/export/bulk/download", methods=["GET"])
@check_session_validity
def download_bulk_export():
    """Download the bulk exported file."""
    file_path = None
    try:
        file_path = session.get("bulk_export_file")
        mime_type = session.get("bulk_export_mime", "application/octet-stream")
        filename = session.get("bulk_export_name", "export.bin")

        if not file_path or not os.path.exists(file_path):
            return jsonify({"status": "error", "message": "Export file not found"}), 404

        # Validate file is within temp directory (security check)
        temp_dir = tempfile.gettempdir()
        abs_path = os.path.abspath(file_path)
        if not abs_path.startswith(os.path.abspath(temp_dir)):
            return jsonify({"status": "error", "message": "Invalid file path"}), 400

        # Clean up session
        session.pop("bulk_export_file", None)
        session.pop("bulk_export_mime", None)
        session.pop("bulk_export_name", None)

        # Stream file and cleanup after
        def generate_and_cleanup():
            try:
                with open(file_path, "rb") as f:
                    while True:
                        chunk = f.read(65536)  # 64KB chunks for binary files
                        if not chunk:
                            break
                        yield chunk
            finally:
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                except Exception:
                    pass

        return Response(
            generate_and_cleanup(),
            mimetype=mime_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.error(f"Error downloading bulk export: {e}")
        traceback.print_exc()
        # Clean up file on error
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        return jsonify({"status": "error", "message": str(e)}), 500


# =============================================================================
# Utility Endpoints
# =============================================================================


@historify_bp.route("/api/intervals", methods=["GET"])
@check_session_validity
def get_intervals():
    """Get supported intervals from the broker."""
    try:
        from database.auth_db import get_api_key_for_tradingview
        from services.historify_service import get_supported_timeframes

        # Get API key for the logged-in user
        user = session.get("user")
        api_key = get_api_key_for_tradingview(user)

        if not api_key:
            return jsonify(
                {
                    "status": "error",
                    "message": "No API key found. Please generate an API key first.",
                }
            ), 400

        success, response, status_code = get_supported_timeframes(api_key)
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error getting intervals: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/historify-intervals", methods=["GET"])
@check_session_validity
def get_historify_intervals():
    """Get Historify-specific interval configuration (storage vs computed)."""
    try:
        from services.historify_service import get_historify_intervals as service_get_intervals

        success, response, status_code = service_get_intervals()
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error getting historify intervals: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/exchanges", methods=["GET"])
@check_session_validity
def get_exchanges():
    """Get list of supported exchanges."""
    try:
        from services.historify_service import get_exchanges as service_get_exchanges

        success, response, status_code = service_get_exchanges()
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error getting exchanges: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/stats", methods=["GET"])
@check_session_validity
def get_stats():
    """Get database statistics."""
    try:
        from services.historify_service import get_stats as service_get_stats

        success, response, status_code = service_get_stats()
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/delete", methods=["DELETE"])
@check_session_validity
def delete_data():
    """Delete data for a symbol."""
    try:
        from services.historify_service import delete_symbol_data

        data = request.get_json()
        symbol = data.get("symbol", "").upper()
        exchange = data.get("exchange", "").upper()
        interval = data.get("interval")

        success, response, status_code = delete_symbol_data(symbol, exchange, interval)
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error deleting data: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/delete/bulk", methods=["POST"])
@check_session_validity
def bulk_delete_data():
    """Delete data for multiple symbols in bulk."""
    try:
        from services.historify_service import bulk_delete_symbol_data

        data = request.get_json()
        symbols = data.get("symbols", [])

        if not symbols:
            return jsonify({"status": "error", "message": "No symbols provided"}), 400

        success, response, status_code = bulk_delete_symbol_data(symbols)
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error bulk deleting data: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


# =============================================================================
# CSV Upload Endpoint
# =============================================================================

# Maximum file size for CSV uploads (100 MB)
MAX_UPLOAD_SIZE = 100 * 1024 * 1024


@historify_bp.route("/api/upload", methods=["POST"])
@check_session_validity
def upload_data():
    """Upload CSV or Parquet file with OHLCV data."""
    temp_file = None
    try:
        from services.historify_service import upload_csv_data, upload_parquet_data

        # Check if file is present
        if "file" not in request.files:
            return jsonify({"status": "error", "message": "No file provided"}), 400

        file = request.files["file"]

        if file.filename == "":
            return jsonify({"status": "error", "message": "No file selected"}), 400

        filename_lower = file.filename.lower()
        is_csv = filename_lower.endswith(".csv")
        is_parquet = filename_lower.endswith(".parquet")

        if not is_csv and not is_parquet:
            return jsonify({"status": "error", "message": "File must be CSV or Parquet"}), 400

        # Check file size by reading content length or checking stream
        file.seek(0, 2)  # Seek to end
        file_size = file.tell()
        file.seek(0)  # Reset to beginning

        if file_size > MAX_UPLOAD_SIZE:
            return jsonify(
                {
                    "status": "error",
                    "message": f"File too large. Maximum size is {MAX_UPLOAD_SIZE // (1024 * 1024)} MB",
                }
            ), 400

        # Get form data
        symbol = request.form.get("symbol", "").upper()
        exchange = request.form.get("exchange", "").upper()
        interval = request.form.get("interval", "")

        if not symbol or not exchange or not interval:
            return jsonify(
                {"status": "error", "message": "Symbol, exchange, and interval are required"}
            ), 400

        # Save file to secure temporary file with unique name
        suffix = ".csv" if is_csv else ".parquet"
        temp_file = tempfile.NamedTemporaryFile(
            mode="wb", suffix=suffix, prefix="historify_upload_", delete=False
        )
        temp_path = temp_file.name
        file.save(temp_path)
        temp_file.close()

        try:
            if is_csv:
                success, response, status_code = upload_csv_data(
                    file_path=temp_path, symbol=symbol, exchange=exchange, interval=interval
                )
            else:
                success, response, status_code = upload_parquet_data(
                    file_path=temp_path, symbol=symbol, exchange=exchange, interval=interval
                )
            return jsonify(response), status_code
        finally:
            # Clean up temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)

    except Exception as e:
        logger.error(f"Error uploading data: {e}")
        traceback.print_exc()
        # Clean up temp file on error
        if temp_file and os.path.exists(temp_file.name):
            os.remove(temp_file.name)
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/sample/<format_type>", methods=["GET"])
@check_session_validity
def download_sample(format_type):
    """Download sample CSV or Parquet file for import reference."""
    import io

    import pandas as pd

    try:
        # Create sample data with Date and Time columns (trader-friendly format)
        sample_data = {
            "date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
            "time": ["09:15:00", "09:15:00", "09:15:00", "09:15:00", "09:15:00"],
            "open": [100.0, 102.5, 101.0, 103.0, 104.5],
            "high": [103.0, 104.0, 103.5, 105.0, 106.0],
            "low": [99.5, 101.0, 100.5, 102.5, 103.5],
            "close": [102.5, 101.0, 103.0, 104.5, 105.5],
            "volume": [10000, 12000, 11000, 15000, 13000],
            "oi": [0, 0, 0, 0, 0],
        }
        df = pd.DataFrame(sample_data)

        if format_type == "csv":
            output = io.StringIO()
            df.to_csv(output, index=False)
            output.seek(0)
            return Response(
                output.getvalue(),
                mimetype="text/csv",
                headers={"Content-Disposition": "attachment; filename=sample_ohlcv.csv"},
            )
        elif format_type == "parquet":
            output = io.BytesIO()
            df.to_parquet(output, index=False, engine="pyarrow", compression="zstd")
            output.seek(0)
            return Response(
                output.getvalue(),
                mimetype="application/octet-stream",
                headers={"Content-Disposition": "attachment; filename=sample_ohlcv.parquet"},
            )
        else:
            return jsonify(
                {"status": "error", "message": "Invalid format. Use csv or parquet"}
            ), 400

    except Exception as e:
        logger.exception(f"Error generating sample file: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# =============================================================================
# FNO Discovery Endpoints
# =============================================================================


@historify_bp.route("/api/fno/underlyings", methods=["GET"])
@check_session_validity
def get_fno_underlyings():
    """Get list of FNO underlyings for an exchange."""
    try:
        from services.historify_service import get_fno_underlyings as service_get_underlyings

        exchange = request.args.get("exchange")  # Optional, returns all if not specified

        success, response, status_code = service_get_underlyings(exchange)
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error getting FNO underlyings: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/fno/expiries", methods=["GET"])
@check_session_validity
def get_fno_expiries():
    """Get expiries for an underlying."""
    try:
        from services.historify_service import get_fno_expiries as service_get_expiries

        underlying = request.args.get("underlying", "").upper()
        exchange = request.args.get("exchange", "NFO").upper()
        instrumenttype = request.args.get(
            "instrumenttype"
        )  # Optional: FUTSTK, FUTIDX, OPTIDX, OPTSTK

        if not underlying:
            return jsonify({"status": "error", "message": "Underlying is required"}), 400

        success, response, status_code = service_get_expiries(underlying, exchange, instrumenttype)
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error getting FNO expiries: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/fno/chain", methods=["GET"])
@check_session_validity
def get_fno_chain():
    """Get full option/futures chain for an underlying."""
    try:
        from services.historify_service import get_fno_chain as service_get_chain

        underlying = request.args.get("underlying", "").upper()
        exchange = request.args.get("exchange", "NFO").upper()
        expiry = request.args.get("expiry")
        instrumenttype = request.args.get("instrumenttype")  # CE, PE, FUT
        strike_min = request.args.get("strike_min", type=float)
        strike_max = request.args.get("strike_max", type=float)
        limit = request.args.get("limit", 1000, type=int)

        if not underlying:
            return jsonify({"status": "error", "message": "Underlying is required"}), 400

        success, response, status_code = service_get_chain(
            underlying=underlying,
            exchange=exchange,
            expiry=expiry,
            instrumenttype=instrumenttype,
            strike_min=strike_min,
            strike_max=strike_max,
            limit=limit,
        )
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error getting FNO chain: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/fno/futures", methods=["GET"])
@check_session_validity
def get_futures_chain():
    """Get all futures contracts for an underlying."""
    try:
        from services.historify_service import get_futures_chain as service_get_futures

        underlying = request.args.get("underlying", "").upper()
        exchange = request.args.get("exchange", "NFO").upper()

        if not underlying:
            return jsonify({"status": "error", "message": "Underlying is required"}), 400

        success, response, status_code = service_get_futures(underlying, exchange)
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error getting futures chain: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/fno/options", methods=["GET"])
@check_session_validity
def get_option_chain():
    """Get option chain symbols for an underlying."""
    try:
        from services.historify_service import get_option_chain_symbols as service_get_options

        underlying = request.args.get("underlying", "").upper()
        exchange = request.args.get("exchange", "NFO").upper()
        expiry = request.args.get("expiry")
        strike_min = request.args.get("strike_min", type=float)
        strike_max = request.args.get("strike_max", type=float)

        if not underlying:
            return jsonify({"status": "error", "message": "Underlying is required"}), 400

        success, response, status_code = service_get_options(
            underlying=underlying,
            exchange=exchange,
            expiry=expiry,
            strike_min=strike_min,
            strike_max=strike_max,
        )
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error getting option chain: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


# =============================================================================
# Download Job Management Endpoints
# =============================================================================


@historify_bp.route("/api/jobs", methods=["GET"])
@check_session_validity
def get_jobs():
    """Get list of download jobs."""
    try:
        from services.historify_service import get_all_jobs

        status = request.args.get("status")  # Optional filter
        limit = request.args.get("limit", 50, type=int)

        success, response, status_code = get_all_jobs(status, limit)
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error getting jobs: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/jobs", methods=["POST"])
@check_session_validity
def create_job():
    """Create and start a new download job."""
    try:
        from database.auth_db import get_api_key_for_tradingview
        from services.historify_service import create_and_start_job

        data = request.get_json()
        job_type = data.get("job_type", "custom")
        symbols = data.get("symbols", [])  # List of {symbol, exchange}
        interval = data.get("interval", "D")
        start_date = data.get("start_date")
        end_date = data.get("end_date")
        config = data.get("config", {})
        incremental = data.get("incremental", False)  # Only download new data

        if not symbols:
            return jsonify({"status": "error", "message": "No symbols provided"}), 400

        # Get API key for the logged-in user
        user = session.get("user")
        api_key = get_api_key_for_tradingview(user)

        if not api_key:
            return jsonify(
                {
                    "status": "error",
                    "message": "No API key found. Please generate an API key first.",
                }
            ), 400

        success, response, status_code = create_and_start_job(
            job_type=job_type,
            symbols=symbols,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            api_key=api_key,
            config=config,
            incremental=incremental,
        )
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error creating job: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/jobs/<job_id>", methods=["GET"])
@check_session_validity
def get_job_status(job_id):
    """Get status and progress of a specific job."""
    try:
        from services.historify_service import get_job_status as service_get_job_status

        success, response, status_code = service_get_job_status(job_id)
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error getting job status: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/jobs/<job_id>/cancel", methods=["POST"])
@check_session_validity
def cancel_job(job_id):
    """Cancel a running job."""
    try:
        from services.historify_service import cancel_job as service_cancel_job

        success, response, status_code = service_cancel_job(job_id)
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error cancelling job: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/jobs/<job_id>/pause", methods=["POST"])
@check_session_validity
def pause_job(job_id):
    """Pause a running job."""
    try:
        from services.historify_service import pause_job as service_pause_job

        success, response, status_code = service_pause_job(job_id)
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error pausing job: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/jobs/<job_id>/resume", methods=["POST"])
@check_session_validity
def resume_job_endpoint(job_id):
    """Resume a paused job."""
    try:
        from services.historify_service import resume_job as service_resume_job

        success, response, status_code = service_resume_job(job_id)
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error resuming job: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/jobs/<job_id>/retry", methods=["POST"])
@check_session_validity
def retry_job(job_id):
    """Retry failed items in a job."""
    try:
        from database.auth_db import get_api_key_for_tradingview
        from services.historify_service import retry_failed_items

        # Get API key for the logged-in user
        user = session.get("user")
        api_key = get_api_key_for_tradingview(user)

        if not api_key:
            return jsonify(
                {
                    "status": "error",
                    "message": "No API key found. Please generate an API key first.",
                }
            ), 400

        success, response, status_code = retry_failed_items(job_id, api_key)
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error retrying job: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/jobs/<job_id>", methods=["DELETE"])
@check_session_validity
def delete_job(job_id):
    """Delete a job and its items."""
    try:
        from services.historify_service import delete_job as service_delete_job

        success, response, status_code = service_delete_job(job_id)
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error deleting job: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


# =============================================================================
# Enhanced Catalog Endpoints
# =============================================================================


@historify_bp.route("/api/catalog/grouped", methods=["GET"])
@check_session_validity
def get_catalog_grouped():
    """Get catalog grouped by underlying/exchange/instrument type."""
    try:
        from services.historify_service import get_catalog_grouped_service

        group_by = request.args.get(
            "group_by", "underlying"
        )  # underlying, exchange, instrumenttype

        success, response, status_code = get_catalog_grouped_service(group_by)
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error getting grouped catalog: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/catalog/metadata", methods=["GET"])
@check_session_validity
def get_catalog_with_metadata():
    """Get catalog with enriched metadata."""
    try:
        from services.historify_service import get_catalog_with_metadata_service

        success, response, status_code = get_catalog_with_metadata_service()
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error getting catalog with metadata: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/metadata/enrich", methods=["POST"])
@check_session_validity
def enrich_metadata():
    """Enrich and save metadata for symbols."""
    try:
        from services.historify_service import enrich_and_save_metadata

        data = request.get_json()
        symbols = data.get("symbols", [])  # List of {symbol, exchange}

        if not symbols:
            return jsonify({"status": "error", "message": "No symbols provided"}), 400

        success, response, status_code = enrich_and_save_metadata(symbols)
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error enriching metadata: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


# =============================================================================
# Scheduler API Endpoints
# =============================================================================


@historify_bp.route("/api/schedules", methods=["GET"])
@check_session_validity
def get_schedules():
    """Get all schedules."""
    try:
        from database.historify_db import get_all_schedules
        from services.historify_scheduler_service import get_historify_scheduler

        schedules = get_all_schedules()

        # Enrich with next_run_at from APScheduler
        scheduler = get_historify_scheduler()
        for schedule in schedules:
            next_run = scheduler.get_next_run_time(schedule["id"])
            if next_run:
                schedule["next_run_at"] = next_run.isoformat()

        return jsonify({"status": "success", "data": schedules, "count": len(schedules)}), 200
    except Exception as e:
        logger.error(f"Error getting schedules: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/schedules", methods=["POST"])
@check_session_validity
def create_schedule():
    """Create a new schedule."""
    try:
        import uuid

        from services.historify_scheduler_service import get_historify_scheduler

        data = request.get_json()

        # Validate required fields
        name = data.get("name", "").strip()
        schedule_type = data.get("schedule_type")
        data_interval = data.get("data_interval", "D")

        if not name:
            return jsonify({"status": "error", "message": "Schedule name is required"}), 400

        if schedule_type not in ("interval", "daily"):
            return jsonify(
                {
                    "status": "error",
                    "message": 'Invalid schedule type. Must be "interval" or "daily"',
                }
            ), 400

        if data_interval not in ("1m", "D"):
            return jsonify(
                {"status": "error", "message": 'Invalid data interval. Must be "1m" or "D"'}
            ), 400

        # Validate schedule-type-specific fields
        if schedule_type == "interval":
            interval_value = data.get("interval_value")
            interval_unit = data.get("interval_unit", "minutes")

            if not interval_value or not isinstance(interval_value, int) or interval_value < 1:
                return jsonify({"status": "error", "message": "Invalid interval value"}), 400

            if interval_unit not in ("minutes", "hours"):
                return jsonify(
                    {
                        "status": "error",
                        "message": 'Invalid interval unit. Must be "minutes" or "hours"',
                    }
                ), 400

        elif schedule_type == "daily":
            time_of_day = data.get("time_of_day", "09:15")
            # Validate time format HH:MM
            try:
                hour, minute = map(int, time_of_day.split(":"))
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError("Invalid time range")
            except (ValueError, AttributeError):
                return jsonify(
                    {"status": "error", "message": "Invalid time format. Use HH:MM (e.g., 09:15)"}
                ), 400

        # Validate lookback_days
        lookback_days = data.get("lookback_days", 1)
        if not isinstance(lookback_days, int) or lookback_days < 1 or lookback_days > 365:
            return jsonify(
                {"status": "error", "message": "lookback_days must be between 1 and 365"}
            ), 400

        # Generate schedule ID
        schedule_id = str(uuid.uuid4())[:8]

        # Create schedule (always uses watchlist as download source)
        scheduler = get_historify_scheduler()
        success, msg = scheduler.add_schedule(
            schedule_id=schedule_id,
            name=name,
            schedule_type=schedule_type,
            data_interval=data_interval,
            interval_value=data.get("interval_value"),
            interval_unit=data.get("interval_unit", "minutes"),
            time_of_day=data.get("time_of_day", "09:15"),
            lookback_days=lookback_days,
            description=data.get("description"),
        )

        if success:
            return jsonify({"status": "success", "message": msg, "schedule_id": schedule_id}), 201
        else:
            return jsonify({"status": "error", "message": msg}), 400

    except Exception as e:
        logger.error(f"Error creating schedule: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/schedules/<schedule_id>", methods=["GET"])
@check_session_validity
def get_schedule(schedule_id):
    """Get a specific schedule."""
    try:
        from database.historify_db import get_schedule as db_get_schedule
        from services.historify_scheduler_service import get_historify_scheduler

        schedule = db_get_schedule(schedule_id)

        if not schedule:
            return jsonify({"status": "error", "message": "Schedule not found"}), 404

        # Enrich with next_run_at from APScheduler
        scheduler = get_historify_scheduler()
        next_run = scheduler.get_next_run_time(schedule_id)
        if next_run:
            schedule["next_run_at"] = next_run.isoformat()

        return jsonify({"status": "success", "data": schedule}), 200

    except Exception as e:
        logger.error(f"Error getting schedule: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/schedules/<schedule_id>", methods=["PUT"])
@check_session_validity
def update_schedule(schedule_id):
    """Update a schedule."""
    try:
        from database.historify_db import get_schedule as db_get_schedule
        from services.historify_scheduler_service import get_historify_scheduler

        # Check if schedule exists
        existing = db_get_schedule(schedule_id)
        if not existing:
            return jsonify({"status": "error", "message": "Schedule not found"}), 404

        data = request.get_json()

        # Validate schedule-type-specific fields if provided
        schedule_type = data.get("schedule_type", existing.get("schedule_type"))

        if schedule_type == "interval":
            interval_value = data.get("interval_value", existing.get("interval_value"))
            interval_unit = data.get("interval_unit", existing.get("interval_unit", "minutes"))

            if interval_value is not None and (
                not isinstance(interval_value, int) or interval_value < 1
            ):
                return jsonify({"status": "error", "message": "Invalid interval value"}), 400

            if interval_unit not in ("minutes", "hours"):
                return jsonify({"status": "error", "message": "Invalid interval unit"}), 400

        elif schedule_type == "daily":
            time_of_day = data.get("time_of_day", existing.get("time_of_day", "09:15"))
            try:
                hour, minute = map(int, time_of_day.split(":"))
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError("Invalid time range")
            except (ValueError, AttributeError):
                return jsonify(
                    {"status": "error", "message": "Invalid time format. Use HH:MM"}
                ), 400

        # Update schedule
        scheduler = get_historify_scheduler()
        success, msg = scheduler.update_schedule(
            schedule_id=schedule_id,
            name=data.get("name"),
            description=data.get("description"),
            schedule_type=data.get("schedule_type"),
            interval_value=data.get("interval_value"),
            interval_unit=data.get("interval_unit"),
            time_of_day=data.get("time_of_day"),
            data_interval=data.get("data_interval"),
            lookback_days=data.get("lookback_days"),
        )

        if success:
            return jsonify({"status": "success", "message": msg}), 200
        else:
            return jsonify({"status": "error", "message": msg}), 400

    except Exception as e:
        logger.error(f"Error updating schedule: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/schedules/<schedule_id>", methods=["DELETE"])
@check_session_validity
def delete_schedule(schedule_id):
    """Delete a schedule."""
    try:
        from services.historify_scheduler_service import get_historify_scheduler

        scheduler = get_historify_scheduler()
        success, msg = scheduler.delete_schedule(schedule_id)

        if success:
            return jsonify({"status": "success", "message": msg}), 200
        else:
            return jsonify({"status": "error", "message": msg}), 400

    except Exception as e:
        logger.error(f"Error deleting schedule: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/schedules/<schedule_id>/enable", methods=["POST"])
@check_session_validity
def enable_schedule(schedule_id):
    """Enable a schedule."""
    try:
        from services.historify_scheduler_service import get_historify_scheduler

        scheduler = get_historify_scheduler()
        success, msg = scheduler.enable_schedule(schedule_id)

        if success:
            return jsonify({"status": "success", "message": msg}), 200
        else:
            return jsonify({"status": "error", "message": msg}), 400

    except Exception as e:
        logger.error(f"Error enabling schedule: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/schedules/<schedule_id>/disable", methods=["POST"])
@check_session_validity
def disable_schedule(schedule_id):
    """Disable a schedule."""
    try:
        from services.historify_scheduler_service import get_historify_scheduler

        scheduler = get_historify_scheduler()
        success, msg = scheduler.disable_schedule(schedule_id)

        if success:
            return jsonify({"status": "success", "message": msg}), 200
        else:
            return jsonify({"status": "error", "message": msg}), 400

    except Exception as e:
        logger.error(f"Error disabling schedule: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/schedules/<schedule_id>/pause", methods=["POST"])
@check_session_validity
def pause_schedule(schedule_id):
    """Pause a schedule."""
    try:
        from services.historify_scheduler_service import get_historify_scheduler

        scheduler = get_historify_scheduler()
        success, msg = scheduler.pause_schedule(schedule_id)

        if success:
            return jsonify({"status": "success", "message": msg}), 200
        else:
            return jsonify({"status": "error", "message": msg}), 400

    except Exception as e:
        logger.error(f"Error pausing schedule: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/schedules/<schedule_id>/resume", methods=["POST"])
@check_session_validity
def resume_schedule(schedule_id):
    """Resume a paused schedule."""
    try:
        from services.historify_scheduler_service import get_historify_scheduler

        scheduler = get_historify_scheduler()
        success, msg = scheduler.resume_schedule(schedule_id)

        if success:
            return jsonify({"status": "success", "message": msg}), 200
        else:
            return jsonify({"status": "error", "message": msg}), 400

    except Exception as e:
        logger.error(f"Error resuming schedule: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/schedules/<schedule_id>/trigger", methods=["POST"])
@check_session_validity
def trigger_schedule(schedule_id):
    """Manually trigger a schedule execution."""
    try:
        from services.historify_scheduler_service import get_historify_scheduler

        scheduler = get_historify_scheduler()
        success, msg = scheduler.trigger_schedule(schedule_id)

        if success:
            return jsonify({"status": "success", "message": msg}), 200
        else:
            return jsonify({"status": "error", "message": msg}), 400

    except Exception as e:
        logger.error(f"Error triggering schedule: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@historify_bp.route("/api/schedules/<schedule_id>/executions", methods=["GET"])
@check_session_validity
def get_schedule_executions(schedule_id):
    """Get execution history for a schedule."""
    try:
        from database.historify_db import get_schedule_executions as db_get_executions

        limit = min(request.args.get("limit", 20, type=int), 100)
        executions = db_get_executions(schedule_id, limit)

        return jsonify({"status": "success", "data": executions, "count": len(executions)}), 200

    except Exception as e:
        logger.error(f"Error getting executions: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
