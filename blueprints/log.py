# blueprints/log.py

from flask import Blueprint, render_template, session, redirect, url_for
from database.apilog_db import OrderLog
from sqlalchemy import func
import pytz
from datetime import datetime

log_bp = Blueprint('log_bp', __name__, url_prefix='/logs')

@log_bp.route('/')
def view_logs():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    # Set timezone to IST
    ist = pytz.timezone('Asia/Kolkata')
    
    # Get the current date in IST
    today_ist = datetime.now(ist).date()

    # Filter logs by today's date in IST
    logs = OrderLog.query.filter(func.date(OrderLog.created_at) == today_ist).order_by(OrderLog.created_at.desc()).all()

    return render_template('logs.html', logs=logs)