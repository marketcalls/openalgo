# blueprints/historify.py
"""
Historify Blueprint

API routes for historical market data management.
Note: The /historify page is served by react_app.py (React frontend).
"""

from flask import Blueprint, jsonify, request, session, Response, send_file
from utils.session import check_session_validity
from utils.logging import get_logger
import traceback
import os
import tempfile

logger = get_logger(__name__)

historify_bp = Blueprint('historify_bp', __name__, url_prefix='/historify')


# =============================================================================
# Watchlist API Endpoints
# =============================================================================

@historify_bp.route('/api/watchlist', methods=['GET'])
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
        return jsonify({'status': 'error', 'message': str(e)}), 500


@historify_bp.route('/api/watchlist', methods=['POST'])
@check_session_validity
def add_watchlist():
    """Add a symbol to the watchlist."""
    try:
        from services.historify_service import add_to_watchlist

        data = request.get_json()
        symbol = data.get('symbol', '').upper()
        exchange = data.get('exchange', '').upper()
        display_name = data.get('display_name')

        success, response, status_code = add_to_watchlist(symbol, exchange, display_name)
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error adding to watchlist: {e}")
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@historify_bp.route('/api/watchlist', methods=['DELETE'])
@check_session_validity
def remove_watchlist():
    """Remove a symbol from the watchlist."""
    try:
        from services.historify_service import remove_from_watchlist

        data = request.get_json()
        symbol = data.get('symbol', '').upper()
        exchange = data.get('exchange', '').upper()

        success, response, status_code = remove_from_watchlist(symbol, exchange)
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error removing from watchlist: {e}")
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@historify_bp.route('/api/watchlist/bulk', methods=['POST'])
@check_session_validity
def bulk_add_watchlist():
    """Add multiple symbols to the watchlist."""
    try:
        from services.historify_service import bulk_add_to_watchlist

        data = request.get_json()
        symbols = data.get('symbols', [])

        success, response, status_code = bulk_add_to_watchlist(symbols)
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error bulk adding to watchlist: {e}")
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# =============================================================================
# Data Download Endpoints
# =============================================================================

@historify_bp.route('/api/download', methods=['POST'])
@check_session_validity
def download_data():
    """Download historical data for a symbol."""
    try:
        from services.historify_service import download_data as service_download_data
        from database.auth_db import get_api_key_for_tradingview

        data = request.get_json()
        symbol = data.get('symbol', '').upper()
        exchange = data.get('exchange', '').upper()
        interval = data.get('interval', 'D')
        start_date = data.get('start_date')
        end_date = data.get('end_date')

        # Get API key for the logged-in user
        user = session.get('user')
        api_key = get_api_key_for_tradingview(user)

        if not api_key:
            return jsonify({
                'status': 'error',
                'message': 'No API key found. Please generate an API key first.'
            }), 400

        success, response, status_code = service_download_data(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            api_key=api_key
        )
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error downloading data: {e}")
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@historify_bp.route('/api/download/watchlist', methods=['POST'])
@check_session_validity
def download_watchlist():
    """Download data for all symbols in the watchlist."""
    try:
        from services.historify_service import download_watchlist_data
        from database.auth_db import get_api_key_for_tradingview

        data = request.get_json()
        interval = data.get('interval', 'D')
        start_date = data.get('start_date')
        end_date = data.get('end_date')

        # Get API key for the logged-in user
        user = session.get('user')
        api_key = get_api_key_for_tradingview(user)

        if not api_key:
            return jsonify({
                'status': 'error',
                'message': 'No API key found. Please generate an API key first.'
            }), 400

        success, response, status_code = download_watchlist_data(
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            api_key=api_key
        )
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error downloading watchlist data: {e}")
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# =============================================================================
# Data Retrieval Endpoints
# =============================================================================

@historify_bp.route('/api/data', methods=['GET'])
@check_session_validity
def get_chart_data():
    """Get OHLCV data for charting."""
    try:
        from services.historify_service import get_chart_data as service_get_chart_data

        symbol = request.args.get('symbol', '').upper()
        exchange = request.args.get('exchange', '').upper()
        interval = request.args.get('interval', 'D')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        success, response, status_code = service_get_chart_data(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_date=start_date,
            end_date=end_date
        )
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error getting chart data: {e}")
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@historify_bp.route('/api/catalog', methods=['GET'])
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
        return jsonify({'status': 'error', 'message': str(e)}), 500


@historify_bp.route('/api/symbol-info', methods=['GET'])
@check_session_validity
def get_symbol_info():
    """Get data availability info for a symbol."""
    try:
        from services.historify_service import get_symbol_data_info

        symbol = request.args.get('symbol', '').upper()
        exchange = request.args.get('exchange', '').upper()
        interval = request.args.get('interval')

        success, response, status_code = get_symbol_data_info(symbol, exchange, interval)
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error getting symbol info: {e}")
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# =============================================================================
# Export Endpoints
# =============================================================================

@historify_bp.route('/api/export', methods=['POST'])
@check_session_validity
def export_data():
    """Export data to CSV and return download link."""
    try:
        from services.historify_service import export_data_to_csv

        data = request.get_json()
        symbol = data.get('symbol')
        exchange = data.get('exchange')
        interval = data.get('interval')
        start_date = data.get('start_date')
        end_date = data.get('end_date')

        # Use temp directory for exports
        output_dir = tempfile.gettempdir()

        success, response, status_code = export_data_to_csv(
            output_dir=output_dir,
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_date=start_date,
            end_date=end_date
        )

        if success:
            # Store file path in session for download
            session['export_file'] = response.get('file_path')

        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error exporting data: {e}")
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@historify_bp.route('/api/export/download', methods=['GET'])
@check_session_validity
def download_export():
    """Download the exported CSV file."""
    file_path = None
    try:
        file_path = session.get('export_file')

        if not file_path or not os.path.exists(file_path):
            return jsonify({'status': 'error', 'message': 'Export file not found'}), 404

        # Validate file is within temp directory (security check)
        temp_dir = tempfile.gettempdir()
        abs_path = os.path.abspath(file_path)
        if not abs_path.startswith(os.path.abspath(temp_dir)):
            return jsonify({'status': 'error', 'message': 'Invalid file path'}), 400

        filename = os.path.basename(file_path)

        # Clean up session before sending (file will be deleted after send)
        session.pop('export_file', None)

        # Use send_file with streaming for memory efficiency
        # Note: We need to read the file since we want to delete it after sending
        # Using a generator to stream and delete after
        def generate_and_cleanup():
            try:
                with open(file_path, 'r') as f:
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
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename={filename}'}
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
        return jsonify({'status': 'error', 'message': str(e)}), 500


# =============================================================================
# Utility Endpoints
# =============================================================================

@historify_bp.route('/api/intervals', methods=['GET'])
@check_session_validity
def get_intervals():
    """Get supported intervals from the broker."""
    try:
        from services.historify_service import get_supported_timeframes
        from database.auth_db import get_api_key_for_tradingview

        # Get API key for the logged-in user
        user = session.get('user')
        api_key = get_api_key_for_tradingview(user)

        if not api_key:
            return jsonify({
                'status': 'error',
                'message': 'No API key found. Please generate an API key first.'
            }), 400

        success, response, status_code = get_supported_timeframes(api_key)
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error getting intervals: {e}")
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@historify_bp.route('/api/exchanges', methods=['GET'])
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
        return jsonify({'status': 'error', 'message': str(e)}), 500


@historify_bp.route('/api/stats', methods=['GET'])
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
        return jsonify({'status': 'error', 'message': str(e)}), 500


@historify_bp.route('/api/delete', methods=['DELETE'])
@check_session_validity
def delete_data():
    """Delete data for a symbol."""
    try:
        from services.historify_service import delete_symbol_data

        data = request.get_json()
        symbol = data.get('symbol', '').upper()
        exchange = data.get('exchange', '').upper()
        interval = data.get('interval')

        success, response, status_code = delete_symbol_data(symbol, exchange, interval)
        return jsonify(response), status_code
    except Exception as e:
        logger.error(f"Error deleting data: {e}")
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# =============================================================================
# CSV Upload Endpoint
# =============================================================================

# Maximum file size for CSV uploads (100 MB)
MAX_UPLOAD_SIZE = 100 * 1024 * 1024


@historify_bp.route('/api/upload', methods=['POST'])
@check_session_validity
def upload_csv():
    """Upload CSV file with OHLCV data."""
    temp_file = None
    try:
        from services.historify_service import upload_csv_data

        # Check if file is present
        if 'file' not in request.files:
            return jsonify({'status': 'error', 'message': 'No file provided'}), 400

        file = request.files['file']

        if file.filename == '':
            return jsonify({'status': 'error', 'message': 'No file selected'}), 400

        if not file.filename.lower().endswith('.csv'):
            return jsonify({'status': 'error', 'message': 'File must be a CSV'}), 400

        # Check file size by reading content length or checking stream
        file.seek(0, 2)  # Seek to end
        file_size = file.tell()
        file.seek(0)  # Reset to beginning

        if file_size > MAX_UPLOAD_SIZE:
            return jsonify({
                'status': 'error',
                'message': f'File too large. Maximum size is {MAX_UPLOAD_SIZE // (1024 * 1024)} MB'
            }), 400

        # Get form data
        symbol = request.form.get('symbol', '').upper()
        exchange = request.form.get('exchange', '').upper()
        interval = request.form.get('interval', '')

        if not symbol or not exchange or not interval:
            return jsonify({
                'status': 'error',
                'message': 'Symbol, exchange, and interval are required'
            }), 400

        # Save file to secure temporary file with unique name
        temp_file = tempfile.NamedTemporaryFile(
            mode='wb',
            suffix='.csv',
            prefix='historify_upload_',
            delete=False
        )
        temp_path = temp_file.name
        file.save(temp_path)
        temp_file.close()

        try:
            success, response, status_code = upload_csv_data(
                file_path=temp_path,
                symbol=symbol,
                exchange=exchange,
                interval=interval
            )
            return jsonify(response), status_code
        finally:
            # Clean up temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)

    except Exception as e:
        logger.error(f"Error uploading CSV: {e}")
        traceback.print_exc()
        # Clean up temp file on error
        if temp_file and os.path.exists(temp_file.name):
            os.remove(temp_file.name)
        return jsonify({'status': 'error', 'message': str(e)}), 500
