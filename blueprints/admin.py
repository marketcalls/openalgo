from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from utils.session import check_session_validity
from utils.logging import get_logger
from limiter import limiter
from database.qty_freeze_db import (
    QtyFreeze, db_session as freeze_db_session,
    load_freeze_qty_from_csv, load_freeze_qty_cache, get_all_freeze_qty
)
from database.market_calendar_db import (
    Holiday, HolidayExchange, MarketTiming, db_session as calendar_db_session,
    get_holidays_by_year, get_market_timings_for_date, get_all_market_timings,
    update_market_timing, DEFAULT_MARKET_TIMINGS, SUPPORTED_EXCHANGES,
    clear_market_calendar_cache
)
from datetime import datetime, date
import os

logger = get_logger(__name__)

# Use existing rate limits from .env (same as API endpoints)
API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "50 per second")

admin_bp = Blueprint('admin_bp', __name__, url_prefix='/admin')


@admin_bp.errorhandler(429)
def ratelimit_handler(e):
    """Handle rate limit exceeded errors"""
    flash('Rate limit exceeded. Please try again later.', 'error')
    return redirect(request.referrer or url_for('admin_bp.index'))


# ============================================================================
# Admin Index
# ============================================================================

@admin_bp.route('/')
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def index():
    """Admin dashboard with links to all admin functions"""
    # Get counts for stats
    freeze_count = QtyFreeze.query.count()
    holiday_count = Holiday.query.count()
    return render_template('admin/index.html',
                          freeze_count=freeze_count,
                          holiday_count=holiday_count)


# ============================================================================
# Freeze Quantity Routes
# ============================================================================

@admin_bp.route('/freeze')
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def freeze_qty():
    """View freeze quantities"""
    freeze_data = QtyFreeze.query.order_by(QtyFreeze.symbol).all()
    return render_template('admin/freeze.html', freeze_data=freeze_data)


@admin_bp.route('/freeze/add', methods=['POST'])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def freeze_qty_add():
    """Add a new freeze quantity entry"""
    try:
        exchange = request.form.get('exchange', 'NFO').strip().upper()
        symbol = request.form.get('symbol', '').strip().upper()
        freeze_qty = request.form.get('freeze_qty', '').strip()

        if not symbol or not freeze_qty:
            flash('Symbol and Freeze Qty are required', 'error')
            return redirect(url_for('admin_bp.freeze_qty'))

        # Check if already exists
        existing = QtyFreeze.query.filter_by(exchange=exchange, symbol=symbol).first()
        if existing:
            flash(f'{symbol} already exists for {exchange}. Use edit instead.', 'error')
            return redirect(url_for('admin_bp.freeze_qty'))

        entry = QtyFreeze(
            exchange=exchange,
            symbol=symbol,
            freeze_qty=int(freeze_qty)
        )
        freeze_db_session.add(entry)
        freeze_db_session.commit()
        load_freeze_qty_cache()

        flash(f'Added freeze qty for {symbol}: {freeze_qty}', 'success')
    except Exception as e:
        freeze_db_session.rollback()
        logger.error(f"Error adding freeze qty: {e}")
        flash(f'Error adding entry: {str(e)}', 'error')

    return redirect(url_for('admin_bp.freeze_qty'))


@admin_bp.route('/freeze/edit/<int:id>', methods=['POST'])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def freeze_qty_edit(id):
    """Edit a freeze quantity entry"""
    try:
        entry = QtyFreeze.query.get(id)
        if not entry:
            flash('Entry not found', 'error')
            return redirect(url_for('admin_bp.freeze_qty'))

        freeze_qty = request.form.get('freeze_qty', '').strip()
        if freeze_qty:
            entry.freeze_qty = int(freeze_qty)
            freeze_db_session.commit()
            load_freeze_qty_cache()
            flash(f'Updated freeze qty for {entry.symbol}: {freeze_qty}', 'success')
    except Exception as e:
        freeze_db_session.rollback()
        logger.error(f"Error editing freeze qty: {e}")
        flash(f'Error updating entry: {str(e)}', 'error')

    return redirect(url_for('admin_bp.freeze_qty'))


@admin_bp.route('/freeze/delete/<int:id>', methods=['POST'])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def freeze_qty_delete(id):
    """Delete a freeze quantity entry"""
    try:
        entry = QtyFreeze.query.get(id)
        if entry:
            symbol = entry.symbol
            freeze_db_session.delete(entry)
            freeze_db_session.commit()
            load_freeze_qty_cache()
            flash(f'Deleted freeze qty for {symbol}', 'success')
        else:
            flash('Entry not found', 'error')
    except Exception as e:
        freeze_db_session.rollback()
        logger.error(f"Error deleting freeze qty: {e}")
        flash(f'Error deleting entry: {str(e)}', 'error')

    return redirect(url_for('admin_bp.freeze_qty'))


@admin_bp.route('/freeze/upload', methods=['POST'])
@check_session_validity
@limiter.limit("10/minute")
def freeze_qty_upload():
    """Upload CSV file to update freeze quantities"""
    try:
        if 'csv_file' not in request.files:
            flash('No file selected', 'error')
            return redirect(url_for('admin_bp.freeze_qty'))

        file = request.files['csv_file']
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(url_for('admin_bp.freeze_qty'))

        if not file.filename.endswith('.csv'):
            flash('Please upload a CSV file', 'error')
            return redirect(url_for('admin_bp.freeze_qty'))

        # Save temporarily and load
        temp_path = '/tmp/qtyfreeze_upload.csv'
        file.save(temp_path)

        exchange = request.form.get('exchange', 'NFO').strip().upper()
        result = load_freeze_qty_from_csv(temp_path, exchange)

        if result:
            count = QtyFreeze.query.filter_by(exchange=exchange).count()
            flash(f'Successfully loaded {count} freeze quantities for {exchange}', 'success')
        else:
            flash('Error loading CSV file', 'error')

        # Clean up
        if os.path.exists(temp_path):
            os.remove(temp_path)

    except Exception as e:
        logger.error(f"Error uploading freeze qty CSV: {e}")
        flash(f'Error uploading file: {str(e)}', 'error')

    return redirect(url_for('admin_bp.freeze_qty'))


# ============================================================================
# Market Holidays Routes
# ============================================================================

@admin_bp.route('/holidays')
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def holidays():
    """View market holidays"""
    current_year = datetime.now().year
    year = request.args.get('year', current_year, type=int)

    # Query holidays directly to get IDs for deletion
    holidays_list = Holiday.query.filter(Holiday.year == year).order_by(Holiday.holiday_date).all()

    holidays_data = []
    for holiday in holidays_list:
        # Get exchange information
        exchanges = HolidayExchange.query.filter(HolidayExchange.holiday_id == holiday.id).all()
        closed_exchanges = [ex.exchange_code for ex in exchanges if not ex.is_open]

        holidays_data.append({
            'id': holiday.id,
            'date': holiday.holiday_date.strftime('%Y-%m-%d'),
            'day_name': holiday.holiday_date.strftime('%A'),
            'description': holiday.description,
            'holiday_type': holiday.holiday_type,
            'closed_exchanges': closed_exchanges
        })

    # Get available years from database dynamically
    from sqlalchemy import func
    available_years = calendar_db_session.query(func.distinct(Holiday.year)).order_by(Holiday.year).all()
    years = [y[0] for y in available_years] if available_years else [current_year]

    # Ensure current year and next year are in the list for adding new holidays
    if current_year not in years:
        years.append(current_year)
    if current_year + 1 not in years:
        years.append(current_year + 1)
    years = sorted(years)

    return render_template('admin/holidays.html',
                          holidays=holidays_data,
                          current_year=year,
                          years=years,
                          exchanges=SUPPORTED_EXCHANGES)


@admin_bp.route('/holidays/add', methods=['POST'])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def holiday_add():
    """Add a new holiday"""
    try:
        date_str = request.form.get('date', '').strip()
        description = request.form.get('description', '').strip()
        holiday_type = request.form.get('holiday_type', 'TRADING_HOLIDAY').strip()
        closed_exchanges = request.form.getlist('closed_exchanges')

        if not date_str or not description:
            flash('Date and description are required', 'error')
            return redirect(url_for('admin_bp.holidays'))

        holiday_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        year = holiday_date.year

        # Create holiday
        holiday = Holiday(
            holiday_date=holiday_date,
            description=description,
            holiday_type=holiday_type,
            year=year
        )
        calendar_db_session.add(holiday)
        calendar_db_session.flush()

        # Add closed exchanges
        for exchange in closed_exchanges:
            exchange_entry = HolidayExchange(
                holiday_id=holiday.id,
                exchange_code=exchange,
                is_open=False
            )
            calendar_db_session.add(exchange_entry)

        calendar_db_session.commit()
        clear_market_calendar_cache()

        flash(f'Added holiday: {description} on {date_str}', 'success')
        return redirect(url_for('admin_bp.holidays', year=year))

    except Exception as e:
        calendar_db_session.rollback()
        logger.error(f"Error adding holiday: {e}")
        flash(f'Error adding holiday: {str(e)}', 'error')

    return redirect(url_for('admin_bp.holidays'))


@admin_bp.route('/holidays/delete/<int:id>', methods=['POST'])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def holiday_delete(id):
    """Delete a holiday"""
    try:
        holiday = Holiday.query.get(id)
        if holiday:
            year = holiday.year
            # Delete related exchange entries first
            HolidayExchange.query.filter_by(holiday_id=id).delete()
            calendar_db_session.delete(holiday)
            calendar_db_session.commit()
            clear_market_calendar_cache()
            flash(f'Deleted holiday: {holiday.description}', 'success')
            return redirect(url_for('admin_bp.holidays', year=year))
        else:
            flash('Holiday not found', 'error')
    except Exception as e:
        calendar_db_session.rollback()
        logger.error(f"Error deleting holiday: {e}")
        flash(f'Error deleting holiday: {str(e)}', 'error')

    return redirect(url_for('admin_bp.holidays'))


# ============================================================================
# Market Timings Routes
# ============================================================================

@admin_bp.route('/timings')
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def timings():
    """View market timings"""
    # Get timings from database (or defaults)
    timings_data = get_all_market_timings()

    # Get today's actual timings
    today = date.today()
    today_timings = get_market_timings_for_date(today)

    return render_template('admin/timings.html',
                          timings=timings_data,
                          today_timings=today_timings,
                          today=today.strftime('%Y-%m-%d'),
                          exchanges=SUPPORTED_EXCHANGES)


@admin_bp.route('/timings/edit/<exchange>', methods=['POST'])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def timings_edit(exchange):
    """Edit market timing for an exchange"""
    try:
        start_time = request.form.get('start_time', '').strip()
        end_time = request.form.get('end_time', '').strip()

        if not start_time or not end_time:
            flash('Start time and end time are required', 'error')
            return redirect(url_for('admin_bp.timings'))

        # Validate time format
        try:
            datetime.strptime(start_time, '%H:%M')
            datetime.strptime(end_time, '%H:%M')
        except ValueError:
            flash('Invalid time format. Use HH:MM', 'error')
            return redirect(url_for('admin_bp.timings'))

        if update_market_timing(exchange, start_time, end_time):
            flash(f'Updated timing for {exchange}: {start_time} - {end_time}', 'success')
        else:
            flash(f'Error updating timing for {exchange}', 'error')

    except Exception as e:
        logger.error(f"Error editing timing: {e}")
        flash(f'Error editing timing: {str(e)}', 'error')

    return redirect(url_for('admin_bp.timings'))


@admin_bp.route('/timings/check', methods=['POST'])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def timings_check():
    """Check market timings for a specific date"""
    date_str = request.form.get('date', '').strip()
    if not date_str:
        flash('Please select a date', 'error')
        return redirect(url_for('admin_bp.timings'))

    try:
        check_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        check_timings = get_market_timings_for_date(check_date)

        # Convert epoch to readable time
        result_timings = []
        for t in check_timings:
            start_dt = datetime.fromtimestamp(t['start_time'] / 1000)
            end_dt = datetime.fromtimestamp(t['end_time'] / 1000)
            result_timings.append({
                'exchange': t['exchange'],
                'start_time': start_dt.strftime('%H:%M'),
                'end_time': end_dt.strftime('%H:%M')
            })

        # Get current timings for the form
        timings_data = get_all_market_timings()

        return render_template('admin/timings.html',
                              timings=timings_data,
                              today_timings=None,
                              check_date=date_str,
                              check_timings=result_timings,
                              exchanges=SUPPORTED_EXCHANGES)
    except Exception as e:
        logger.error(f"Error checking timings: {e}")
        flash(f'Error checking timings: {str(e)}', 'error')

    return redirect(url_for('admin_bp.timings'))
