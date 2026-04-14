# blueprints/logging.py

from flask import Blueprint, render_template

from limiter import limiter
from utils.session import check_session_validity

logging_bp = Blueprint("logging_bp", __name__, url_prefix="/logging")


@logging_bp.route("/")
@check_session_validity
@limiter.limit("60/minute")
def logging_dashboard():
    """
    Consolidated logging dashboard page.
    Provides access to all logging and monitoring sections:
    - Live Logs
    - Analyzer Logs
    - Traffic Monitor
    - Latency Monitor
    - Security Logs
    """
    return render_template("logging.html")
