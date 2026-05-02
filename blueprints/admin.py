import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from database.market_calendar_db import (
    DEFAULT_MARKET_TIMINGS,
    SUPPORTED_EXCHANGES,
    Holiday,
    HolidayExchange,
    MarketTiming,
    clear_market_calendar_cache,
    get_all_market_timings,
    get_holidays_by_year,
    get_market_timings_for_date,
    update_market_timing,
)
from database.market_calendar_db import db_session as calendar_db_session
from database.qty_freeze_db import (
    QtyFreeze,
    get_all_freeze_qty,
    load_freeze_qty_cache,
    load_freeze_qty_from_csv,
)
from database.qty_freeze_db import db_session as freeze_db_session
from limiter import limiter
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

# Use existing rate limits from .env (same as API endpoints)
API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "50 per second")

admin_bp = Blueprint("admin_bp", __name__, url_prefix="/admin")


@admin_bp.errorhandler(429)
def ratelimit_handler(e):
    """Handle rate limit exceeded errors"""
    flash("Rate limit exceeded. Please try again later.", "error")
    return redirect(request.referrer or url_for("admin_bp.index"))


# ============================================================================
# Legacy Jinja Template Routes (Commented out - React handles these now)
# ============================================================================
# Note: The following routes have been migrated to React frontend.
# They are kept commented for reference during the migration period.
# React routes are defined in react_app.py

# @admin_bp.route('/')
# @check_session_validity
# @limiter.limit(API_RATE_LIMIT)
# def index():
#     """Admin dashboard with links to all admin functions"""
#     freeze_count = QtyFreeze.query.count()
#     holiday_count = Holiday.query.count()
#     return render_template('admin/index.html',
#                           freeze_count=freeze_count,
#                           holiday_count=holiday_count)

# @admin_bp.route('/freeze')
# @check_session_validity
# @limiter.limit(API_RATE_LIMIT)
# def freeze_qty():
#     """View freeze quantities"""
#     freeze_data = QtyFreeze.query.order_by(QtyFreeze.symbol).all()
#     return render_template('admin/freeze.html', freeze_data=freeze_data)

# @admin_bp.route('/freeze/add', methods=['POST'])
# ... (form-based routes migrated to /api/freeze POST)

# @admin_bp.route('/freeze/edit/<int:id>', methods=['POST'])
# ... (form-based routes migrated to /api/freeze/<id> PUT)

# @admin_bp.route('/freeze/delete/<int:id>', methods=['POST'])
# ... (form-based routes migrated to /api/freeze/<id> DELETE)

# @admin_bp.route('/freeze/upload', methods=['POST'])
# ... (form-based routes migrated to /api/freeze/upload POST)

# @admin_bp.route('/holidays')
# ... (migrated to React /admin/holidays)

# @admin_bp.route('/holidays/add', methods=['POST'])
# ... (form-based routes migrated to /api/holidays POST)

# @admin_bp.route('/holidays/delete/<int:id>', methods=['POST'])
# ... (form-based routes migrated to /api/holidays/<id> DELETE)

# @admin_bp.route('/timings')
# ... (migrated to React /admin/timings)

# @admin_bp.route('/timings/edit/<exchange>', methods=['POST'])
# ... (form-based routes migrated to /api/timings/<exchange> PUT)

# @admin_bp.route('/timings/check', methods=['POST'])
# ... (form-based routes migrated to /api/timings/check POST)


# ============================================================================
# JSON API Endpoints for React Frontend
# ============================================================================


@admin_bp.route("/api/stats")
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def api_stats():
    """Get admin dashboard stats"""
    try:
        freeze_count = QtyFreeze.query.count()
        holiday_count = Holiday.query.count()
        return jsonify(
            {"status": "success", "freeze_count": freeze_count, "holiday_count": holiday_count}
        )
    except Exception as e:
        logger.exception(f"Error fetching admin stats: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ============================================================================
# Freeze Quantity API Endpoints
# ============================================================================


@admin_bp.route("/api/freeze")
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def api_freeze_list():
    """Get all freeze quantities"""
    try:
        freeze_data = QtyFreeze.query.order_by(QtyFreeze.symbol).all()
        return jsonify(
            {
                "status": "success",
                "data": [
                    {
                        "id": f.id,
                        "exchange": f.exchange,
                        "symbol": f.symbol,
                        "freeze_qty": f.freeze_qty,
                    }
                    for f in freeze_data
                ],
            }
        )
    except Exception as e:
        logger.exception(f"Error fetching freeze data: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@admin_bp.route("/api/freeze", methods=["POST"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def api_freeze_add():
    """Add a new freeze quantity entry"""
    try:
        data = request.get_json()
        exchange = data.get("exchange", "NFO").strip().upper()
        symbol = data.get("symbol", "").strip().upper()
        freeze_qty = data.get("freeze_qty")

        if not symbol or freeze_qty is None:
            return jsonify(
                {"status": "error", "message": "Symbol and freeze_qty are required"}
            ), 400

        # Check if already exists
        existing = QtyFreeze.query.filter_by(exchange=exchange, symbol=symbol).first()
        if existing:
            return jsonify(
                {"status": "error", "message": f"{symbol} already exists for {exchange}"}
            ), 400

        entry = QtyFreeze(exchange=exchange, symbol=symbol, freeze_qty=int(freeze_qty))
        freeze_db_session.add(entry)
        freeze_db_session.commit()
        load_freeze_qty_cache()

        return jsonify(
            {
                "status": "success",
                "message": f"Added freeze qty for {symbol}: {freeze_qty}",
                "data": {
                    "id": entry.id,
                    "exchange": entry.exchange,
                    "symbol": entry.symbol,
                    "freeze_qty": entry.freeze_qty,
                },
            }
        )
    except Exception as e:
        freeze_db_session.rollback()
        logger.exception(f"Error adding freeze qty: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@admin_bp.route("/api/freeze/<int:id>", methods=["PUT"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def api_freeze_edit(id):
    """Edit a freeze quantity entry"""
    try:
        entry = QtyFreeze.query.get(id)
        if not entry:
            return jsonify({"status": "error", "message": "Entry not found"}), 404

        data = request.get_json()
        freeze_qty = data.get("freeze_qty")

        if freeze_qty is not None:
            entry.freeze_qty = int(freeze_qty)
            freeze_db_session.commit()
            load_freeze_qty_cache()

            return jsonify(
                {
                    "status": "success",
                    "message": f"Updated freeze qty for {entry.symbol}: {freeze_qty}",
                    "data": {
                        "id": entry.id,
                        "exchange": entry.exchange,
                        "symbol": entry.symbol,
                        "freeze_qty": entry.freeze_qty,
                    },
                }
            )

        return jsonify({"status": "error", "message": "No freeze_qty provided"}), 400
    except Exception as e:
        freeze_db_session.rollback()
        logger.exception(f"Error editing freeze qty: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@admin_bp.route("/api/freeze/<int:id>", methods=["DELETE"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def api_freeze_delete(id):
    """Delete a freeze quantity entry"""
    try:
        entry = QtyFreeze.query.get(id)
        if not entry:
            return jsonify({"status": "error", "message": "Entry not found"}), 404

        symbol = entry.symbol
        freeze_db_session.delete(entry)
        freeze_db_session.commit()
        load_freeze_qty_cache()

        return jsonify({"status": "success", "message": f"Deleted freeze qty for {symbol}"})
    except Exception as e:
        freeze_db_session.rollback()
        logger.exception(f"Error deleting freeze qty: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@admin_bp.route("/api/freeze/upload", methods=["POST"])
@check_session_validity
@limiter.limit("10/minute")
def api_freeze_upload():
    """Upload CSV file to update freeze quantities"""
    try:
        if "csv_file" not in request.files:
            return jsonify({"status": "error", "message": "No file selected"}), 400

        file = request.files["csv_file"]
        if file.filename == "":
            return jsonify({"status": "error", "message": "No file selected"}), 400

        if not file.filename.endswith(".csv"):
            return jsonify({"status": "error", "message": "Please upload a CSV file"}), 400

        # Save temporarily and load
        temp_path = "/tmp/qtyfreeze_upload.csv"
        file.save(temp_path)

        exchange = request.form.get("exchange", "NFO").strip().upper()
        result = load_freeze_qty_from_csv(temp_path, exchange)

        # Clean up
        if os.path.exists(temp_path):
            os.remove(temp_path)

        if result:
            count = QtyFreeze.query.filter_by(exchange=exchange).count()
            return jsonify(
                {
                    "status": "success",
                    "message": f"Successfully loaded {count} freeze quantities for {exchange}",
                    "count": count,
                }
            )
        else:
            return jsonify({"status": "error", "message": "Error loading CSV file"}), 500

    except Exception as e:
        logger.exception(f"Error uploading freeze qty CSV: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ============================================================================
# Holiday API Endpoints
# ============================================================================


@admin_bp.route("/api/holidays")
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def api_holidays_list():
    """Get holidays for a specific year"""
    try:
        current_year = datetime.now().year
        year = request.args.get("year", current_year, type=int)

        holidays_list = (
            Holiday.query.filter(Holiday.year == year).order_by(Holiday.holiday_date).all()
        )

        holidays_data = []
        for holiday in holidays_list:
            exchanges = HolidayExchange.query.filter(HolidayExchange.holiday_id == holiday.id).all()
            closed_exchanges = [ex.exchange_code for ex in exchanges if not ex.is_open]

            holidays_data.append(
                {
                    "id": holiday.id,
                    "date": holiday.holiday_date.strftime("%Y-%m-%d"),
                    "day_name": holiday.holiday_date.strftime("%A"),
                    "description": holiday.description,
                    "holiday_type": holiday.holiday_type,
                    "closed_exchanges": closed_exchanges,
                }
            )

        # Get available years
        from sqlalchemy import func

        available_years = (
            calendar_db_session.query(func.distinct(Holiday.year)).order_by(Holiday.year).all()
        )
        years = [y[0] for y in available_years] if available_years else [current_year]

        if current_year not in years:
            years.append(current_year)
        if current_year + 1 not in years:
            years.append(current_year + 1)
        years = sorted(years)

        return jsonify(
            {
                "status": "success",
                "data": holidays_data,
                "current_year": year,
                "years": years,
                "exchanges": SUPPORTED_EXCHANGES,
            }
        )
    except Exception as e:
        logger.exception(f"Error fetching holidays: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@admin_bp.route("/api/holidays", methods=["POST"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def api_holiday_add():
    """Add a new holiday"""
    try:
        data = request.get_json()
        date_str = data.get("date", "").strip()
        description = data.get("description", "").strip()
        holiday_type = data.get("holiday_type", "TRADING_HOLIDAY").strip()
        closed_exchanges = data.get("closed_exchanges", [])
        open_exchanges = data.get("open_exchanges", [])  # For special sessions

        if not date_str or not description:
            return jsonify({"status": "error", "message": "Date and description are required"}), 400

        # Validate special session has open exchanges with timings
        if holiday_type == "SPECIAL_SESSION" and not open_exchanges:
            return jsonify(
                {"status": "error", "message": "Special session requires at least one exchange with timings"}
            ), 400

        holiday_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        year = holiday_date.year

        holiday = Holiday(
            holiday_date=holiday_date, description=description, holiday_type=holiday_type, year=year
        )
        calendar_db_session.add(holiday)
        calendar_db_session.flush()

        # Add closed exchanges (for trading holidays)
        for exchange in closed_exchanges:
            exchange_entry = HolidayExchange(
                holiday_id=holiday.id, exchange_code=exchange, is_open=False
            )
            calendar_db_session.add(exchange_entry)

        # Add open exchanges with special timings (for special sessions)
        for open_ex in open_exchanges:
            exchange_code = open_ex.get("exchange", "").strip()
            start_time = open_ex.get("start_time")  # epoch milliseconds
            end_time = open_ex.get("end_time")  # epoch milliseconds

            if not exchange_code or start_time is None or end_time is None:
                continue

            exchange_entry = HolidayExchange(
                holiday_id=holiday.id,
                exchange_code=exchange_code,
                is_open=True,
                start_time=start_time,
                end_time=end_time,
            )
            calendar_db_session.add(exchange_entry)

        calendar_db_session.commit()
        clear_market_calendar_cache()

        return jsonify(
            {
                "status": "success",
                "message": f"Added holiday: {description} on {date_str}",
                "data": {
                    "id": holiday.id,
                    "date": date_str,
                    "description": description,
                    "holiday_type": holiday_type,
                    "closed_exchanges": closed_exchanges,
                    "open_exchanges": open_exchanges,
                },
            }
        )
    except Exception as e:
        calendar_db_session.rollback()
        logger.exception(f"Error adding holiday: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@admin_bp.route("/api/holidays/<int:id>", methods=["DELETE"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def api_holiday_delete(id):
    """Delete a holiday"""
    try:
        holiday = Holiday.query.get(id)
        if not holiday:
            return jsonify({"status": "error", "message": "Holiday not found"}), 404

        description = holiday.description
        HolidayExchange.query.filter_by(holiday_id=id).delete()
        calendar_db_session.delete(holiday)
        calendar_db_session.commit()
        clear_market_calendar_cache()

        return jsonify({"status": "success", "message": f"Deleted holiday: {description}"})
    except Exception as e:
        calendar_db_session.rollback()
        logger.exception(f"Error deleting holiday: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ============================================================================
# Market Timings API Endpoints
# ============================================================================


@admin_bp.route("/api/timings")
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def api_timings_list():
    """Get all market timings"""
    try:
        timings_data = get_all_market_timings()

        today = date.today()
        today_timings = get_market_timings_for_date(today)

        # Convert epoch to readable time for today's timings (for display)
        today_timings_formatted = []
        for t in today_timings:
            start_dt = datetime.fromtimestamp(t["start_time"] / 1000)
            end_dt = datetime.fromtimestamp(t["end_time"] / 1000)
            today_timings_formatted.append(
                {
                    "exchange": t["exchange"],
                    "start_time": start_dt.strftime("%H:%M"),
                    "end_time": end_dt.strftime("%H:%M"),
                }
            )

        return jsonify(
            {
                "status": "success",
                # data: admin config data with HH:MM strings (for admin UI)
                "data": timings_data,
                # market_status: epoch-based timings for frontend market status checks
                "market_status": today_timings,
                "today_timings": today_timings_formatted,
                "today": today.strftime("%Y-%m-%d"),
                "exchanges": SUPPORTED_EXCHANGES,
            }
        )
    except Exception as e:
        logger.exception(f"Error fetching timings: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@admin_bp.route("/api/timings/<exchange>", methods=["PUT"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def api_timings_edit(exchange):
    """Edit market timing for an exchange"""
    try:
        data = request.get_json()
        start_time = data.get("start_time", "").strip()
        end_time = data.get("end_time", "").strip()

        if not start_time or not end_time:
            return jsonify(
                {"status": "error", "message": "Start time and end time are required"}
            ), 400

        # Validate time format
        try:
            datetime.strptime(start_time, "%H:%M")
            datetime.strptime(end_time, "%H:%M")
        except ValueError:
            return jsonify({"status": "error", "message": "Invalid time format. Use HH:MM"}), 400

        if update_market_timing(exchange, start_time, end_time):
            return jsonify(
                {
                    "status": "success",
                    "message": f"Updated timing for {exchange}: {start_time} - {end_time}",
                }
            )
        else:
            return jsonify(
                {"status": "error", "message": f"Error updating timing for {exchange}"}
            ), 500

    except Exception as e:
        logger.exception(f"Error editing timing: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@admin_bp.route("/api/timings/check", methods=["POST"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def api_timings_check():
    """Check market timings for a specific date"""
    try:
        data = request.get_json()
        date_str = data.get("date", "").strip()

        if not date_str:
            return jsonify({"status": "error", "message": "Date is required"}), 400

        check_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        check_timings = get_market_timings_for_date(check_date)

        # Convert epoch to readable time
        result_timings = []
        for t in check_timings:
            start_dt = datetime.fromtimestamp(t["start_time"] / 1000)
            end_dt = datetime.fromtimestamp(t["end_time"] / 1000)
            result_timings.append(
                {
                    "exchange": t["exchange"],
                    "start_time": start_dt.strftime("%H:%M"),
                    "end_time": end_dt.strftime("%H:%M"),
                }
            )

        return jsonify({"status": "success", "date": date_str, "timings": result_timings})
    except Exception as e:
        logger.exception(f"Error checking timings: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ============================================================================
# Diagnostics: Errors, System Info, Health Probes, Downloadable Report
# ============================================================================
#
# Security model for this section:
#   - All endpoints require a valid admin session (@check_session_validity).
#   - All endpoints are rate-limited.
#   - Inputs from the client are validated against allowlists; ints are clamped.
#   - File reads are restricted to a fixed log directory resolved at call time
#     and verified to be inside the configured LOG_DIR.
#   - Secrets (APP_KEY, API_KEY_PEPPER, BROKER_API_SECRET, tokens) are NEVER
#     emitted; only their presence is reported as a boolean.
#   - Outputs are JSON or text/markdown — no user input is interpolated into
#     HTML. The frontend renders all values as React text.

_ERROR_LEVELS = frozenset({"ERROR", "CRITICAL", "WARNING", "INFO", "DEBUG"})
_ALLOWED_ERROR_KEYS = frozenset(
    {"ts", "level", "logger", "module", "file", "message", "exception", "request"}
)
_MAX_LIMIT = 200
_MAX_QUERY_LEN = 200
_MAX_FIELD_BYTES = 20_000
_MAX_TAIL_BYTES = 10 * 1024 * 1024  # 10 MB cap on tail-read
_REPORT_RATE = "10/minute"
_DIAG_RATE = "10/minute"

# Sensitive env var names — never emit values, only "set"/"not set"
_SECRET_ENV_KEYS = frozenset(
    {
        "APP_KEY",
        "API_KEY_PEPPER",
        "BROKER_API_KEY",
        "BROKER_API_SECRET",
        "BROKER_API_KEY_MARKET",
        "BROKER_API_SECRET_MARKET",
        "REDIRECT_URL",
        "SMTP_PASSWORD",
        "TELEGRAM_BOT_TOKEN",
        "GOOGLE_CLIENT_SECRET",
    }
)


def _errors_file_path():
    """Resolve log/errors.jsonl, ensuring it stays inside LOG_DIR."""
    log_dir = Path(os.getenv("LOG_DIR", "log")).resolve()
    target = (log_dir / "errors.jsonl").resolve()
    try:
        target.relative_to(log_dir)
    except ValueError:
        return None
    return target


def _truncate_field(value, max_len=_MAX_FIELD_BYTES):
    if isinstance(value, str) and len(value) > max_len:
        return value[:max_len] + "...[truncated]"
    if isinstance(value, list):
        joined = "\n".join(str(x) for x in value)
        if len(joined) > max_len:
            return [joined[:max_len] + "...[truncated]"]
    return value


def _sanitize_error_entry(entry):
    """Whitelist allowed keys from an errors.jsonl entry and truncate large fields."""
    out = {}
    for key in _ALLOWED_ERROR_KEYS:
        if key in entry:
            out[key] = _truncate_field(entry[key])
    return out


def _tail_jsonl(path, max_bytes=_MAX_TAIL_BYTES):
    """Tail-read a file up to max_bytes. Returns list of raw lines (strings)."""
    if not path or not path.exists():
        return []
    try:
        size = path.stat().st_size
    except OSError:
        return []
    if size <= 0:
        return []
    read_size = min(size, max_bytes)
    try:
        with path.open("rb") as f:
            f.seek(size - read_size)
            chunk = f.read(read_size)
    except OSError:
        return []
    text = chunk.decode("utf-8", errors="replace")
    lines = text.splitlines()
    # Drop possibly-partial first line when we didn't read from byte 0
    if read_size < size and lines:
        lines = lines[1:]
    return lines


def _parse_jsonl_lines(raw_lines):
    """Yield parsed dict entries from raw JSONL lines, skipping malformed ones."""
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(entry, dict):
            yield entry


@admin_bp.route("/api/errors")
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def api_errors_list():
    """Return recent entries from log/errors.jsonl (read-only, sandboxed)."""
    try:
        # --- validate inputs ---
        try:
            limit = int(request.args.get("limit", 100))
        except (TypeError, ValueError):
            limit = 100
        limit = max(1, min(limit, _MAX_LIMIT))

        level_filter = (request.args.get("level", "") or "").strip().upper()
        if level_filter and level_filter not in _ERROR_LEVELS:
            return jsonify({"status": "error", "message": "Invalid level"}), 400

        q = (request.args.get("q", "") or "").strip()[:_MAX_QUERY_LEN]
        q_lower = q.lower() if q else None

        path = _errors_file_path()
        if path is None:
            return jsonify({"status": "error", "message": "Log directory misconfigured"}), 500

        raw_lines = _tail_jsonl(path)

        results = []
        scanned = 0
        for entry in _parse_jsonl_lines(reversed(raw_lines)):
            scanned += 1
            if level_filter and entry.get("level") != level_filter:
                continue
            if q_lower:
                msg = str(entry.get("message", "")).lower()
                exc = entry.get("exception")
                exc_text = (
                    "".join(str(x) for x in exc).lower()
                    if isinstance(exc, list)
                    else str(exc or "").lower()
                )
                if q_lower not in msg and q_lower not in exc_text:
                    continue
            results.append(_sanitize_error_entry(entry))
            if len(results) >= limit:
                break
        results.reverse()

        total = sum(1 for _ in _parse_jsonl_lines(raw_lines))

        resp = jsonify(
            {
                "status": "success",
                "data": results,
                "count": len(results),
                "scanned": scanned,
                "total_in_window": total,
            }
        )
        resp.headers["Cache-Control"] = "no-store, max-age=0"
        return resp
    except Exception as e:
        logger.exception(f"Error reading error log: {e}")
        return jsonify({"status": "error", "message": "Failed to read error log"}), 500


_CLIENT_REPORT_RATE = "30/minute"
_MAX_CLIENT_MESSAGE_LEN = 2000
_MAX_CLIENT_STACK_LEN = 20_000
_MAX_CLIENT_URL_LEN = 2000
_MAX_CLIENT_COMPONENT_STACK_LEN = 5000
_MAX_CLIENT_USER_AGENT_LEN = 500
_CLIENT_LEVEL_ALLOWLIST = frozenset({"ERROR", "WARN"})

# Logger dedicated to browser-reported errors. Distinct name so they're easy
# to filter in errors.jsonl and in the grouped view.
_client_logger = None


def _get_client_logger():
    global _client_logger
    if _client_logger is None:
        from utils.logging import get_logger as _glr

        _client_logger = _glr("client.browser")
    return _client_logger


def _scrub_control_chars(text):
    """Strip ANSI/control chars, keep printable + whitespace. No regex backtracking."""
    if not isinstance(text, str):
        return ""
    return "".join(ch for ch in text if ch == "\n" or ch == "\t" or (ch.isprintable()))


@admin_bp.route("/api/errors/client", methods=["POST"])
@check_session_validity
@limiter.limit(_CLIENT_REPORT_RATE)
def api_errors_client_report():
    """Receive a browser-side error report and route it into errors.jsonl.

    Auth-gated; rate-limited; every field validated and length-capped. The
    server never echoes the client payload back; it only writes to the log.
    """
    try:
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify({"status": "error", "message": "Invalid payload"}), 400

        level = (data.get("level") or "ERROR").strip().upper()
        if level not in _CLIENT_LEVEL_ALLOWLIST:
            level = "ERROR"

        message = _scrub_control_chars(str(data.get("message") or ""))[:_MAX_CLIENT_MESSAGE_LEN]
        stack = _scrub_control_chars(str(data.get("stack") or ""))[:_MAX_CLIENT_STACK_LEN]
        url = _scrub_control_chars(str(data.get("url") or ""))[:_MAX_CLIENT_URL_LEN]
        component_stack = _scrub_control_chars(str(data.get("component_stack") or ""))[
            :_MAX_CLIENT_COMPONENT_STACK_LEN
        ]
        user_agent = _scrub_control_chars(str(data.get("user_agent") or ""))[
            :_MAX_CLIENT_USER_AGENT_LEN
        ]

        if not message:
            return jsonify({"status": "error", "message": "Missing message"}), 400

        # Compose a single readable line for the log message; full details in
        # the synthesized "exception" so JSONErrorFormatter captures it.
        details = []
        if url:
            details.append(f"URL: {url}")
        if user_agent:
            details.append(f"UA: {user_agent}")
        if component_stack:
            details.append("Component stack:\n" + component_stack)
        if stack:
            details.append("Stack:\n" + stack)

        log_msg = f"[CLIENT] {message}"
        client_logger = _get_client_logger()
        if level == "WARN":
            client_logger.warning(log_msg + (("\n" + "\n\n".join(details)) if details else ""))
        else:
            # Use logger.error with extra context appended — JSONErrorFormatter
            # captures exc_info only when a real exception is present, so we
            # synthesize a structured detail block in the message itself.
            client_logger.error(log_msg + (("\n" + "\n\n".join(details)) if details else ""))

        return jsonify({"status": "success"})
    except Exception as e:
        logger.exception(f"Error recording client report: {e}")
        return jsonify({"status": "error", "message": "Failed to record"}), 500


@admin_bp.route("/api/errors/stats")
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def api_errors_stats():
    """Return error counts by level and recent (1h, 24h) windows."""
    try:
        path = _errors_file_path()
        if path is None or not path.exists():
            return jsonify(
                {
                    "status": "success",
                    "total": 0,
                    "by_level": {},
                    "last_24h": 0,
                    "last_1h": 0,
                }
            )

        raw_lines = _tail_jsonl(path)

        by_level = {}
        last_24h = 0
        last_1h = 0
        total = 0
        now = datetime.now()
        cutoff_24h = now - timedelta(hours=24)
        cutoff_1h = now - timedelta(hours=1)

        for entry in _parse_jsonl_lines(raw_lines):
            total += 1
            level = entry.get("level", "UNKNOWN")
            by_level[level] = by_level.get(level, 0) + 1
            ts_str = entry.get("ts")
            if isinstance(ts_str, str):
                try:
                    ts_dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
                if ts_dt >= cutoff_24h:
                    last_24h += 1
                if ts_dt >= cutoff_1h:
                    last_1h += 1

        resp = jsonify(
            {
                "status": "success",
                "total": total,
                "by_level": by_level,
                "last_24h": last_24h,
                "last_1h": last_1h,
            }
        )
        resp.headers["Cache-Control"] = "no-store, max-age=0"
        return resp
    except Exception as e:
        logger.exception(f"Error reading error log stats: {e}")
        return jsonify({"status": "error", "message": "Failed to read error log"}), 500


def _normalize_signature(text):
    """Collapse variable parts so the same error class fingerprints stably.

    Strip hex addresses, ISO timestamps, and standalone integers.
    """
    import re

    if not isinstance(text, str):
        return ""
    out = re.sub(r"0x[0-9a-fA-F]+", "0x?", text)
    out = re.sub(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\b", "<ts>", out)
    out = re.sub(r"\b\d{1,}\b", "<n>", out)
    out = re.sub(r"\s+", " ", out).strip()
    return out[:300]


def _fingerprint_entry(entry):
    """Stable signature for grouping. Same exception class + module = same group."""
    import hashlib

    parts = [
        entry.get("level") or "",
        entry.get("logger") or "",
        entry.get("module") or "",
    ]
    exc = entry.get("exception")
    if isinstance(exc, list) and exc:
        # The last frame is "ExceptionType: message" — keep the type only.
        last = str(exc[-1])
        head = last.split(":", 1)[0] if ":" in last else last
        parts.append(_normalize_signature(head))
    elif isinstance(exc, str) and exc:
        parts.append(_normalize_signature(exc[:200]))
    else:
        parts.append(_normalize_signature(str(entry.get("message") or "")[:200]))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12]


@admin_bp.route("/api/errors/groups")
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def api_errors_groups():
    """Aggregate errors.jsonl entries by fingerprint. Returns top groups by count."""
    try:
        try:
            limit = int(request.args.get("limit", 50))
        except (TypeError, ValueError):
            limit = 50
        limit = max(1, min(limit, _MAX_LIMIT))

        path = _errors_file_path()
        if path is None or not path.exists():
            return jsonify({"status": "success", "groups": [], "total_entries": 0})

        raw_lines = _tail_jsonl(path)

        groups = {}
        total = 0
        for entry in _parse_jsonl_lines(raw_lines):
            total += 1
            fp = _fingerprint_entry(entry)
            ts = entry.get("ts")
            existing = groups.get(fp)
            if existing is None:
                groups[fp] = {
                    "fingerprint": fp,
                    "count": 1,
                    "level": entry.get("level"),
                    "logger": entry.get("logger"),
                    "module": entry.get("module"),
                    "first_seen": ts,
                    "last_seen": ts,
                    "sample": _sanitize_error_entry(entry),
                }
            else:
                existing["count"] += 1
                if isinstance(ts, str):
                    if not existing["first_seen"] or ts < existing["first_seen"]:
                        existing["first_seen"] = ts
                    if not existing["last_seen"] or ts > existing["last_seen"]:
                        existing["last_seen"] = ts
                # Keep the most recent sample so the user sees the latest values
                if (
                    isinstance(ts, str)
                    and isinstance(existing.get("last_seen"), str)
                    and ts >= existing["last_seen"]
                ):
                    existing["sample"] = _sanitize_error_entry(entry)

        # Sort by count desc, then last_seen desc
        ordered = sorted(
            groups.values(),
            key=lambda g: (g["count"], g.get("last_seen") or ""),
            reverse=True,
        )[:limit]

        resp = jsonify(
            {
                "status": "success",
                "groups": ordered,
                "total_entries": total,
                "total_groups": len(groups),
            }
        )
        resp.headers["Cache-Control"] = "no-store, max-age=0"
        return resp
    except Exception as e:
        logger.exception(f"Error grouping error log: {e}")
        return jsonify({"status": "error", "message": "Failed to group errors"}), 500


# ----------------------------------------------------------------------------
# System info — host, runtime, hardware, build, brokers, mode, db health
# ----------------------------------------------------------------------------


def _detect_container_and_device():
    """Best-effort detection of Docker, Raspberry Pi, Termux/Android."""
    info = {
        "in_docker": Path("/.dockerenv").exists(),
        "is_raspberry_pi": False,
        "rpi_model": None,
        "is_termux": bool(os.getenv("TERMUX_VERSION")) or Path("/data/data/com.termux").exists(),
        "is_android": bool(os.getenv("ANDROID_ROOT")),
    }
    try:
        cpuinfo = Path("/proc/cpuinfo")
        if cpuinfo.exists():
            text = cpuinfo.read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines():
                if line.lower().startswith("model") and "raspberry pi" in line.lower():
                    info["is_raspberry_pi"] = True
                    info["rpi_model"] = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    return info


def _detect_linux_distro():
    """Read /etc/os-release on Linux. Returns dict or None."""
    try:
        path = Path("/etc/os-release")
        if not path.exists():
            return None
        result = {}
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip().strip('"')
        return {
            "name": result.get("PRETTY_NAME") or result.get("NAME"),
            "id": result.get("ID"),
            "version_id": result.get("VERSION_ID"),
        }
    except OSError:
        return None


def _hardware_snapshot():
    """CPU/RAM/disk via stdlib + psutil (already a dependency)."""
    import platform as _platform
    import shutil as _shutil

    snap = {
        "cpu_count": os.cpu_count(),
        "cpu_model": _platform.processor() or None,
        "memory_total_mb": None,
        "memory_available_mb": None,
        "memory_percent": None,
        "disk_log": None,
        "disk_db": None,
    }
    try:
        import psutil

        vm = psutil.virtual_memory()
        snap["memory_total_mb"] = round(vm.total / (1024 * 1024), 1)
        snap["memory_available_mb"] = round(vm.available / (1024 * 1024), 1)
        snap["memory_percent"] = vm.percent
        # Use a non-deprecated approach for CPU model on Linux
        if _platform.system() == "Linux":
            try:
                cpuinfo = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
                for line in cpuinfo.splitlines():
                    if line.lower().startswith("model name"):
                        snap["cpu_model"] = line.split(":", 1)[1].strip()
                        break
            except OSError:
                pass
    except Exception:
        pass

    for label, target in (("disk_log", "log"), ("disk_db", "db")):
        try:
            usage = _shutil.disk_usage(target)
            snap[label] = {
                "total_gb": round(usage.total / (1024**3), 2),
                "free_gb": round(usage.free / (1024**3), 2),
                "used_percent": round(100 * (usage.total - usage.free) / usage.total, 1),
            }
        except OSError:
            snap[label] = None
    return snap


def _runtime_info():
    """Python version, eventlet status, WSGI hint, uptime."""
    import sys as _sys

    info = {
        "python_version": _sys.version.split()[0],
        "python_implementation": _sys.implementation.name,
        "eventlet_active": False,
        "wsgi_hint": "flask-dev",
        "process_uptime_seconds": None,
    }
    try:
        import eventlet.patcher as _patcher

        info["eventlet_active"] = bool(_patcher.is_monkey_patched("socket"))
    except Exception:
        pass
    if info["eventlet_active"]:
        info["wsgi_hint"] = "gunicorn-eventlet"

    try:
        import psutil

        proc = psutil.Process(os.getpid())
        info["process_uptime_seconds"] = int(datetime.now().timestamp() - proc.create_time())
    except Exception:
        pass
    return info


def _build_info():
    """Platform version, SDK version, git ref, frontend build mtime."""
    info = {
        "openalgo_version": None,
        "openalgo_sdk_version": None,
        "git_branch": None,
        "git_commit": None,
        "frontend_build_time": None,
    }
    try:
        from utils.version import get_version

        info["openalgo_version"] = get_version()
    except Exception:
        pass
    try:
        from importlib import metadata as _metadata

        info["openalgo_sdk_version"] = _metadata.version("openalgo")
    except Exception:
        pass

    # Read .git/HEAD without subprocess. Restrict to repo root.
    try:
        repo_root = Path(__file__).resolve().parent.parent
        head_file = (repo_root / ".git" / "HEAD").resolve()
        if head_file.is_file() and repo_root in head_file.parents:
            head = head_file.read_text(encoding="utf-8", errors="replace").strip()
            if head.startswith("ref: "):
                ref = head[5:].strip()
                # Only allow refs/heads/* or refs/tags/* — never absolute paths
                if ref.startswith(("refs/heads/", "refs/tags/")) and ".." not in ref:
                    info["git_branch"] = ref.split("/", 2)[-1]
                    ref_path = (repo_root / ".git" / ref).resolve()
                    if repo_root in ref_path.parents and ref_path.is_file():
                        info["git_commit"] = ref_path.read_text(encoding="utf-8").strip()[:12]
            else:
                info["git_commit"] = head[:12]
    except OSError:
        pass

    try:
        idx = Path("frontend/dist/index.html")
        if idx.exists():
            info["frontend_build_time"] = datetime.fromtimestamp(idx.stat().st_mtime).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
    except OSError:
        pass
    return info


def _safe_config_snapshot():
    """Public-safe view of config — secrets reduced to set/not-set booleans."""
    secret_status = {key: bool(os.getenv(key)) for key in _SECRET_ENV_KEYS}
    return {
        "valid_brokers": [
            b.strip() for b in (os.getenv("VALID_BROKERS") or "").split(",") if b.strip()
        ],
        "log_level": os.getenv("LOG_LEVEL", "INFO"),
        "log_to_file": (os.getenv("LOG_TO_FILE") or "False").lower() == "true",
        "log_dir": os.getenv("LOG_DIR", "log"),
        "websocket_host": os.getenv("WEBSOCKET_HOST", "127.0.0.1"),
        "websocket_port": os.getenv("WEBSOCKET_PORT", "8765"),
        "max_symbols_per_websocket": os.getenv("MAX_SYMBOLS_PER_WEBSOCKET", "1000"),
        "max_websocket_connections": os.getenv("MAX_WEBSOCKET_CONNECTIONS", "3"),
        "api_rate_limit": os.getenv("API_RATE_LIMIT", "50 per second"),
        "flask_debug": (os.getenv("FLASK_DEBUG") or "False").lower() == "true",
        "secrets_present": secret_status,
    }


def _broker_snapshot():
    """List configured brokers and the active session, without exposing tokens."""
    from flask import has_request_context, session

    info = {
        "configured_brokers": [],
        "active_broker": None,
        "user_logged_in": False,
    }
    if has_request_context():
        info["active_broker"] = session.get("broker")
        info["user_logged_in"] = bool(session.get("logged_in"))
    try:
        from utils.plugin_loader import load_broker_capabilities

        caps = load_broker_capabilities()
        info["configured_brokers"] = sorted(caps.keys()) if isinstance(caps, dict) else []
    except Exception:
        pass
    return info


def _database_snapshot():
    """File presence/size/mtime for each known DB. No live queries."""
    db_files = [
        ("openalgo", "db/openalgo.db"),
        ("logs", "db/logs.db"),
        ("latency", "db/latency.db"),
        ("health", "db/health.db"),
        ("sandbox", "db/sandbox.db"),
        ("historify", "db/historify.duckdb"),
    ]
    out = []
    for name, rel in db_files:
        p = Path(rel)
        try:
            if p.exists():
                st = p.stat()
                out.append(
                    {
                        "name": name,
                        "exists": True,
                        "size_mb": round(st.st_size / (1024 * 1024), 2),
                        "modified": datetime.fromtimestamp(st.st_mtime).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                    }
                )
            else:
                out.append({"name": name, "exists": False, "size_mb": 0, "modified": None})
        except OSError:
            out.append({"name": name, "exists": False, "size_mb": 0, "modified": None})
    return out


def _trading_mode():
    """Return Live / Analyze and a safe label."""
    try:
        from database.settings_db import get_analyze_mode

        mode = get_analyze_mode()
        return {"analyze_mode": bool(mode), "label": "ANALYZE" if mode else "LIVE"}
    except Exception:
        return {"analyze_mode": None, "label": "UNKNOWN"}


def _server_time_info():
    """Server local time + IST + timezone label."""
    try:
        from zoneinfo import ZoneInfo

        now_local = datetime.now()
        now_ist = datetime.now(tz=ZoneInfo("Asia/Kolkata"))
        return {
            "server_time": now_local.strftime("%Y-%m-%d %H:%M:%S"),
            "server_tz": str(now_local.astimezone().tzinfo),
            "ist_time": now_ist.strftime("%Y-%m-%d %H:%M:%S %Z"),
        }
    except Exception:
        return {
            "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "server_tz": None,
            "ist_time": None,
        }


def _build_system_payload():
    """Assemble the full system snapshot. No secrets, no external calls."""
    import platform as _platform

    distro = _detect_linux_distro()
    extras = _detect_container_and_device()
    return {
        "mode": _trading_mode(),
        "host": {
            "system": _platform.system(),
            "release": _platform.release(),
            "version": _platform.version(),
            "machine": _platform.machine(),
            "platform": _platform.platform(),
            "distro": distro,
            "in_docker": extras["in_docker"],
            "is_raspberry_pi": extras["is_raspberry_pi"],
            "rpi_model": extras["rpi_model"],
            "is_termux": extras["is_termux"],
            "is_android": extras["is_android"],
        },
        "runtime": _runtime_info(),
        "hardware": _hardware_snapshot(),
        "build": _build_info(),
        "config": _safe_config_snapshot(),
        "brokers": _broker_snapshot(),
        "databases": _database_snapshot(),
        "time": _server_time_info(),
    }


@admin_bp.route("/api/system")
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def api_system_info():
    """Return a snapshot of host, runtime, hardware, build, brokers, mode."""
    try:
        resp = jsonify({"status": "success", "data": _build_system_payload()})
        resp.headers["Cache-Control"] = "no-store, max-age=0"
        return resp
    except Exception as e:
        logger.exception(f"Error building system info: {e}")
        return jsonify({"status": "error", "message": "Failed to build system info"}), 500


# ----------------------------------------------------------------------------
# Diagnostics — latency probes (button-triggered, stricter rate limit)
# ----------------------------------------------------------------------------


def _check_db_read():
    """Open a SQLite connection and run SELECT 1. Returns ms or error."""
    import sqlite3
    import time

    db_path = Path("db/openalgo.db")
    if not db_path.exists():
        return {"name": "DB read (openalgo.db)", "ok": False, "ms": None, "detail": "Not found"}
    started = time.perf_counter()
    try:
        conn = sqlite3.connect(str(db_path), timeout=2.0)
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        return {"name": "DB read (openalgo.db)", "ok": True, "ms": elapsed, "detail": "OK"}
    except Exception as e:
        return {"name": "DB read (openalgo.db)", "ok": False, "ms": None, "detail": str(e)[:200]}


def _check_loopback_http():
    """HEAD / on the local Flask app — measures internal request latency."""
    import time
    import urllib.request

    started = time.perf_counter()
    try:
        # FLASK_PORT is the canonical OpenAlgo var; PORT is the Docker/Railway
        # convention (gunicorn binds to ${PORT:-5000} in start.sh).
        port = os.getenv("FLASK_PORT") or os.getenv("PORT") or "5000"
        req = urllib.request.Request(f"http://127.0.0.1:{port}/", method="HEAD")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            return {
                "name": "Loopback HTTP",
                "ok": resp.status < 500,
                "ms": elapsed,
                "detail": f"HTTP {resp.status}",
            }
    except Exception as e:
        return {"name": "Loopback HTTP", "ok": False, "ms": None, "detail": str(e)[:200]}


def _check_websocket_proxy():
    """TCP-connect to the local websocket proxy (no handshake)."""
    import socket
    import time

    host = os.getenv("WEBSOCKET_HOST", "127.0.0.1")
    try:
        port = int(os.getenv("WEBSOCKET_PORT", "8765"))
    except ValueError:
        port = 8765
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=2.0):
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            return {
                "name": f"WebSocket proxy {host}:{port}",
                "ok": True,
                "ms": elapsed,
                "detail": "TCP connect OK",
            }
    except Exception as e:
        return {
            "name": f"WebSocket proxy {host}:{port}",
            "ok": False,
            "ms": None,
            "detail": str(e)[:200],
        }


# Allowlist of broker hostnames we are willing to probe with a TCP-connect.
# No HTTP request, no auth, no API call — just a TCP open + immediate close.
_BROKER_PROBE_HOSTS = {
    "zerodha": "api.kite.trade",
    "angel": "apiconnect.angelbroking.com",
    "dhan": "api.dhan.co",
    "upstox": "api.upstox.com",
    "fyers": "api.fyers.in",
    "icici": "api.icicidirect.com",
    "kotak": "tradeapi.kotaksecurities.com",
    "5paisa": "openapi.5paisa.com",
    "alice": "ant.aliceblueonline.com",
    "iifl": "api.iiflsecurities.com",
    "aliceblue": "ant.aliceblueonline.com",
    "shoonya": "api.shoonya.com",
    "flattrade": "piconnect.flattrade.in",
    "definedge": "trading.definedgesecurities.com",
    "wisdom": "api.wisdomcapital.in",
    "groww": "api.groww.in",
}


def _check_active_broker_tcp():
    """TCP connect (not HTTP) to the active broker's API host. No payload."""
    import socket
    import time

    from flask import has_request_context, session

    broker = session.get("broker") if has_request_context() else None
    if not broker:
        return {
            "name": "Broker reachability",
            "ok": False,
            "ms": None,
            "detail": "No active broker session",
        }
    host = _BROKER_PROBE_HOSTS.get(broker.lower())
    if not host:
        return {
            "name": f"Broker reachability ({broker})",
            "ok": False,
            "ms": None,
            "detail": "Probe host not in allowlist",
        }
    started = time.perf_counter()
    try:
        with socket.create_connection((host, 443), timeout=3.0):
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            return {
                "name": f"Broker reachability ({broker} → {host})",
                "ok": True,
                "ms": elapsed,
                "detail": "TCP/443 connect OK",
            }
    except Exception as e:
        return {
            "name": f"Broker reachability ({broker} → {host})",
            "ok": False,
            "ms": None,
            "detail": str(e)[:200],
        }


@admin_bp.route("/api/system/diagnostics", methods=["POST"])
@check_session_validity
@limiter.limit(_DIAG_RATE)
def api_system_diagnostics():
    """Run a fixed set of latency/connectivity probes. No client-supplied targets."""
    try:
        checks = [
            _check_db_read(),
            _check_loopback_http(),
            _check_websocket_proxy(),
            _check_active_broker_tcp(),
        ]
        resp = jsonify(
            {
                "status": "success",
                "ran_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "checks": checks,
            }
        )
        resp.headers["Cache-Control"] = "no-store, max-age=0"
        return resp
    except Exception as e:
        logger.exception(f"Error running diagnostics: {e}")
        return jsonify({"status": "error", "message": "Failed to run diagnostics"}), 500


# ----------------------------------------------------------------------------
# Downloadable report (.md / .txt) — server-rendered, sanitized
# ----------------------------------------------------------------------------


def _md_kv(label, value):
    if value is None or value == "":
        return f"- **{label}:** _not set_"
    return f"- **{label}:** {value}"


def _strip_ansi(text):
    import re

    return re.sub(r"\x1b\[[0-9;]*m", "", str(text))


def _render_report(payload, errors_summary, errors_recent, fmt):
    """Render a self-contained system report. Markdown by default, plaintext on fmt=txt."""
    is_md = fmt == "md"
    bullet = "- " if is_md else "  - "
    h1 = "# " if is_md else ""
    h2 = "## " if is_md else ""
    code_open = "```\n" if is_md else ""
    code_close = "```\n" if is_md else ""

    lines = []
    lines.append(f"{h1}OpenAlgo System Report")
    lines.append("")
    lines.append(_md_kv("Generated", datetime.now().strftime("%Y-%m-%d %H:%M:%S")) if is_md else f"Generated: {datetime.now()}")
    lines.append("")

    mode = payload.get("mode") or {}
    lines.append(f"{h2}Trading Mode")
    lines.append(_md_kv("Mode", mode.get("label", "UNKNOWN")))
    lines.append("")

    host = payload.get("host") or {}
    lines.append(f"{h2}Host")
    lines.append(_md_kv("System", host.get("system")))
    lines.append(_md_kv("Release", host.get("release")))
    lines.append(_md_kv("Machine", host.get("machine")))
    lines.append(_md_kv("Platform", host.get("platform")))
    if host.get("distro"):
        d = host["distro"]
        lines.append(_md_kv("Distro", f"{d.get('name')} ({d.get('id')} {d.get('version_id')})"))
    lines.append(_md_kv("In Docker", host.get("in_docker")))
    if host.get("is_raspberry_pi"):
        lines.append(_md_kv("Raspberry Pi", host.get("rpi_model")))
    if host.get("is_termux"):
        lines.append(_md_kv("Termux", True))
    if host.get("is_android"):
        lines.append(_md_kv("Android", True))
    lines.append("")

    runtime = payload.get("runtime") or {}
    lines.append(f"{h2}Runtime")
    lines.append(_md_kv("Python", runtime.get("python_version")))
    lines.append(_md_kv("Implementation", runtime.get("python_implementation")))
    lines.append(_md_kv("Eventlet active", runtime.get("eventlet_active")))
    lines.append(_md_kv("WSGI", runtime.get("wsgi_hint")))
    lines.append(_md_kv("Process uptime (s)", runtime.get("process_uptime_seconds")))
    lines.append("")

    hw = payload.get("hardware") or {}
    lines.append(f"{h2}Hardware")
    lines.append(_md_kv("CPU count", hw.get("cpu_count")))
    lines.append(_md_kv("CPU model", hw.get("cpu_model")))
    lines.append(_md_kv("Memory total (MB)", hw.get("memory_total_mb")))
    lines.append(_md_kv("Memory available (MB)", hw.get("memory_available_mb")))
    lines.append(_md_kv("Memory used (%)", hw.get("memory_percent")))
    if hw.get("disk_log"):
        lines.append(
            _md_kv("Disk log", f"{hw['disk_log']['free_gb']} GB free of {hw['disk_log']['total_gb']} GB")
        )
    if hw.get("disk_db"):
        lines.append(
            _md_kv("Disk db", f"{hw['disk_db']['free_gb']} GB free of {hw['disk_db']['total_gb']} GB")
        )
    lines.append("")

    build = payload.get("build") or {}
    lines.append(f"{h2}Build")
    lines.append(_md_kv("OpenAlgo", build.get("openalgo_version")))
    lines.append(_md_kv("OpenAlgo SDK", build.get("openalgo_sdk_version")))
    lines.append(_md_kv("Git branch", build.get("git_branch")))
    lines.append(_md_kv("Git commit", build.get("git_commit")))
    lines.append(_md_kv("Frontend build", build.get("frontend_build_time")))
    lines.append("")

    cfg = payload.get("config") or {}
    lines.append(f"{h2}Configuration")
    lines.append(_md_kv("Valid brokers", ", ".join(cfg.get("valid_brokers") or []) or "_none_"))
    lines.append(_md_kv("Log level", cfg.get("log_level")))
    lines.append(_md_kv("Log to file", cfg.get("log_to_file")))
    lines.append(_md_kv("Flask debug", cfg.get("flask_debug")))
    lines.append(_md_kv("WebSocket", f"{cfg.get('websocket_host')}:{cfg.get('websocket_port')}"))
    lines.append(_md_kv("Max symbols / WS", cfg.get("max_symbols_per_websocket")))
    secrets = cfg.get("secrets_present") or {}
    if secrets:
        lines.append("")
        lines.append(f"{h2}Secrets (presence only)")
        for k, v in sorted(secrets.items()):
            lines.append(f"{bullet}{k}: {'set' if v else 'not set'}")
    lines.append("")

    brokers = payload.get("brokers") or {}
    lines.append(f"{h2}Brokers")
    lines.append(_md_kv("Active broker", brokers.get("active_broker")))
    lines.append(_md_kv("User logged in", brokers.get("user_logged_in")))
    lines.append(_md_kv("Configured", ", ".join(brokers.get("configured_brokers") or []) or "_none_"))
    lines.append("")

    dbs = payload.get("databases") or []
    lines.append(f"{h2}Databases")
    for db in dbs:
        if db.get("exists"):
            lines.append(f"{bullet}{db['name']}: {db['size_mb']} MB (modified {db['modified']})")
        else:
            lines.append(f"{bullet}{db['name']}: _missing_")
    lines.append("")

    t = payload.get("time") or {}
    lines.append(f"{h2}Time")
    lines.append(_md_kv("Server time", t.get("server_time")))
    lines.append(_md_kv("IST time", t.get("ist_time")))
    lines.append(_md_kv("Server timezone", t.get("server_tz")))
    lines.append("")

    if errors_summary:
        lines.append(f"{h2}Errors summary")
        lines.append(_md_kv("Total in window", errors_summary.get("total")))
        lines.append(_md_kv("Last 24h", errors_summary.get("last_24h")))
        lines.append(_md_kv("Last 1h", errors_summary.get("last_1h")))
        by_level = errors_summary.get("by_level") or {}
        for lvl, count in sorted(by_level.items()):
            lines.append(f"{bullet}{lvl}: {count}")
        lines.append("")

    if errors_recent:
        lines.append(f"{h2}Recent errors (latest first, max 50)")
        lines.append("")
        for entry in errors_recent[-50:][::-1]:
            ts = entry.get("ts", "?")
            lvl = entry.get("level", "?")
            mod = entry.get("module", "?")
            msg = _strip_ansi(entry.get("message", ""))[:500]
            lines.append(f"{bullet}`{ts}` **{lvl}** in `{mod}`: {msg}" if is_md else f"  - [{ts}] {lvl} in {mod}: {msg}")
        lines.append("")

    body = "\n".join(lines)
    # Hard-cap report size at 1 MB
    if len(body) > 1_000_000:
        body = body[:1_000_000] + "\n\n...[report truncated]\n"
    return body


@admin_bp.route("/api/system/report")
@check_session_validity
@limiter.limit(_REPORT_RATE)
def api_system_report():
    """Download a sanitized system report as .md or .txt for community support posts."""
    try:
        fmt = (request.args.get("format", "md") or "md").lower().strip()
        if fmt not in {"md", "txt"}:
            fmt = "md"

        payload = _build_system_payload()

        # Errors summary (cheap pass over errors.jsonl)
        errors_summary = None
        recent = []
        path = _errors_file_path()
        if path is not None and path.exists():
            raw_lines = _tail_jsonl(path)
            by_level = {}
            last_24h = 0
            last_1h = 0
            total = 0
            now = datetime.now()
            cutoff_24h = now - timedelta(hours=24)
            cutoff_1h = now - timedelta(hours=1)
            for entry in _parse_jsonl_lines(raw_lines):
                total += 1
                lvl = entry.get("level", "UNKNOWN")
                by_level[lvl] = by_level.get(lvl, 0) + 1
                ts = entry.get("ts")
                if isinstance(ts, str):
                    try:
                        ts_dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        continue
                    if ts_dt >= cutoff_24h:
                        last_24h += 1
                    if ts_dt >= cutoff_1h:
                        last_1h += 1
                recent.append(_sanitize_error_entry(entry))
            errors_summary = {
                "total": total,
                "by_level": by_level,
                "last_24h": last_24h,
                "last_1h": last_1h,
            }
            recent = recent[-50:]

        body = _render_report(payload, errors_summary, recent, fmt)
        filename = f"openalgo-system-report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.{fmt}"
        mimetype = "text/markdown" if fmt == "md" else "text/plain"

        from flask import Response

        resp = Response(body, mimetype=f"{mimetype}; charset=utf-8")
        # Set Content-Disposition with a fixed-pattern filename — no client input
        resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        resp.headers["Cache-Control"] = "no-store, max-age=0"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp
    except Exception as e:
        logger.exception(f"Error generating system report: {e}")
        return jsonify({"status": "error", "message": "Failed to generate report"}), 500
