# blueprints/platforms.py

import logging

from flask import Blueprint, render_template

from utils.session import check_session_validity

logger = logging.getLogger(__name__)

platforms_bp = Blueprint("platforms_bp", __name__, url_prefix="/platforms")


@platforms_bp.route("/", methods=["GET"])
@check_session_validity
def index():
    """Display all trading platforms"""
    logger.info("Accessing platforms page")
    return render_template("platforms.html")
