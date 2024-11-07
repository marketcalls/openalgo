# blueprints/log.py

from flask import Blueprint, render_template, session, redirect, url_for
from database.apilog_db import OrderLog
from utils.session import check_session_validity
from sqlalchemy import func
import pytz
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

log_bp = Blueprint('log_bp', __name__, url_prefix='/logs')

@log_bp.route('/')
@check_session_validity
def view_logs():
    # Set timezone to IST
    ist = pytz.timezone('Asia/Kolkata')
    
    # Get the current date in IST
    today_ist = datetime.now(ist).date()

    logger.info(f"Fetching logs for date: {today_ist}")

    try:
        # Filter logs by today's date in IST
        logs = OrderLog.query.filter(
            func.date(OrderLog.created_at) == today_ist
        ).order_by(OrderLog.created_at.desc()).all()
        
        logger.info(f"Found {len(logs)} log entries for today")
        return render_template('logs.html', logs=logs)
        
    except Exception as e:
        logger.error(f"Error fetching logs: {str(e)}")
        return render_template('logs.html', logs=[])
