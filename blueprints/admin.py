import os
from datetime import date, datetime

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
