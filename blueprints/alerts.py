# blueprints/alerts.py
"""
Chart alerts: the history of what fired.

Session-authenticated rather than API-key authenticated: these are the logged-in
user's own alerts, read from the browser they are already signed in to, and
there is nothing here an external platform needs.

**Nothing here evaluates an alert, and nothing here delivers one.** A chart
alert is the chart's: it is defined on the chart, stored with the chart's own
state, and it only fires while /trading is open. That is a deliberate limit and
it is the reason this file is small.

Delivery stays in the page, and that is the whole reason this does not send
anything. A trader chooses per alert whether it makes a sound, raises a desktop
notification, goes to Telegram, goes to WhatsApp or does several of those, and
that choice lives in the alert's own payload on the chart. A second sender here
knows none of it: it would broadcast every firing to every configured channel,
including the ones the trader deliberately left off, and the alerts that do ask
for Telegram would arrive twice.

So the page sends, and then reports what was accepted. This writes down the one
thing the browser cannot keep: the firing itself, after the tab is closed. The
``delivered`` list is that report, and it may be empty. A firing that happened
and reached nobody is a different thing from a firing that did not happen, and
the panel has to be able to tell them apart.

The store is database/alert_log_db.py. This layer is validation, ownership
and HTTP status codes, and nothing else.

No route, port or directive is added to the deployment's nginx configuration:
everything below is under ``location /``, which already proxies to the
application, so a hosted install upgrades without a config migration.
"""

from flask import Blueprint, jsonify, request, session

from database.alert_log_db import MAX_LOG_PAGE, clear_fires, list_fires, record_fire
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

alerts_bp = Blueprint("alerts_bp", __name__, url_prefix="/alerts")


def _user():
    """The signed-in username, or None."""
    return session.get("user")


@alerts_bp.route("/fired", methods=["POST"])
@check_session_validity
def fired():
    """One alert fired on the chart: write it down."""
    user = _user()
    if not user:
        return jsonify({"status": "error", "message": "Sign in to record alerts"}), 401

    fire = request.get_json(silent=True) or {}
    if not isinstance(fire, dict) or not str(fire.get("alertId") or "").strip():
        return jsonify({"status": "error", "message": "That alert could not be identified"}), 400

    # Reported by the page, which is what actually sent the message. A list of
    # names rather than a claim of success, so a channel the browser could not
    # reach is simply absent.
    delivered = fire.get("delivered")
    if not isinstance(delivered, (list, tuple)):
        delivered = ()

    row = record_fire(user, fire, delivered)
    if row is None:
        # The alert did fire and the trader may already have been told. Saying
        # "not recorded" rather than "failed" is the difference between somebody
        # checking their phone and somebody assuming nothing happened.
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "The alert fired but could not be added to the log",
                }
            ),
            500,
        )
    return jsonify({"status": "success", "fire": row})


@alerts_bp.route("/log", methods=["GET"])
@check_session_validity
def log():
    """This user's firings, newest first."""
    user = _user()
    if not user:
        return jsonify({"status": "error", "message": "Sign in to see your alerts"}), 401
    limit = request.args.get("limit", MAX_LOG_PAGE)
    return jsonify({"status": "success", "fires": list_fires(user, limit)})


@alerts_bp.route("/log", methods=["DELETE"])
@check_session_validity
def clear_log():
    """Clear the whole log, or one alert's rows with ``?alertId=``."""
    user = _user()
    if not user:
        return jsonify({"status": "error", "message": "Sign in to clear your alerts"}), 401
    removed = clear_fires(user, request.args.get("alertId"))
    return jsonify({"status": "success", "removed": removed})
