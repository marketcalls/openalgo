# blueprints/broker_credentials.py
"""
Server settings the Profile Broker tab saves to .env: the ngrok tunnel, the
Host Server URL and the WebSocket URL, and the server status it shows.

Broker keys are kept on the Broker Configuration page instead
(blueprints/broker_config.py), as in OpenAlgo Desktop. Reachable once signed
in to OpenAlgo, before any broker login.
"""

import os
import re

from flask import Blueprint, jsonify, request

from limiter import limiter
from utils.env_check import update_env_values
from utils.logging import get_logger
from utils.session import check_session_validity, check_signed_in

logger = get_logger(__name__)

broker_credentials_bp = Blueprint("broker_credentials_bp", __name__, url_prefix="/api/broker")

WRITE_RATE_LIMIT = "20 per minute"


def get_env_path():
    """The .env file this install reads, the same one utils.broker_keys reads."""
    from utils.broker_keys import env_file_path

    return str(env_file_path())


def get_env_value(key: str) -> str:
    """Get a value from the .env file."""
    return os.getenv(key, "")


def mask_secret(value: str, show_chars: int = 4) -> str:
    """Mask a secret value, showing only the first few characters.

    Returns a FIXED-length output (``prefix + '*' * 8``) regardless of the
    original secret's length. This intentionally hides the secret's true
    length so an over-the-shoulder viewer (or a screenshot) cannot infer
    "this is a 64-char Zerodha API secret" vs "this is a 32-char Fyers
    secret" from the asterisk count.

    The fixed-length mask also keeps the rendered value bounded so a long
    secret (some brokers issue 80+ char tokens) cannot overflow the
    Profile UI's column layout — the bug originally reported in the
    Current Configuration card where the asterisks ran past the right
    edge of the card.

    For empty values, returns "" so the frontend can detect "not set" and
    show its placeholder copy.
    """
    if not value:
        return ""
    if len(value) <= show_chars:
        # Edge case: secret shorter than the prefix budget. Show only the
        # mask suffix to avoid revealing the entire short value.
        return "*" * 8
    return value[:show_chars] + "*" * 8


def _error(message, status=400):
    return jsonify({"status": "error", "message": message}), status


def _clean(value):
    """A submitted value, stripped; None when it has a line break or control character."""
    value = str(value if value is not None else "").strip()
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return None
    return value


@broker_credentials_bp.route("/credentials", methods=["GET"])
@check_signed_in
def get_credentials():
    """The server settings, for the Profile Broker tab."""
    try:
        valid_brokers = get_env_value("VALID_BROKERS")
        return jsonify(
            {
                "status": "success",
                "data": {
                    "valid_brokers": [b.strip() for b in valid_brokers.split(",") if b.strip()],
                    "ngrok_allow": get_env_value("NGROK_ALLOW").upper() == "TRUE",
                    "host_server": get_env_value("HOST_SERVER"),
                    "websocket_url": get_env_value("WEBSOCKET_URL"),
                    "server_status": {
                        "flask": {
                            "host": get_env_value("FLASK_HOST_IP") or "127.0.0.1",
                            "port": get_env_value("FLASK_PORT") or "5000",
                        },
                        "websocket": {
                            "host": get_env_value("WEBSOCKET_HOST") or "127.0.0.1",
                            "port": get_env_value("WEBSOCKET_PORT") or "8765",
                        },
                        "zmq": {
                            "host": get_env_value("ZMQ_HOST") or "127.0.0.1",
                            "port": get_env_value("ZMQ_PORT") or "5555",
                        },
                    },
                },
            }
        )
    except Exception:
        logger.exception("Error getting the server settings")
        return _error("Could not read the server settings. Try again.", 500)


@broker_credentials_bp.route("/credentials", methods=["POST"])
@check_signed_in
@limiter.limit(WRITE_RATE_LIMIT)
def update_credentials():
    """Save the ngrok tunnel, Host Server URL and WebSocket URL to .env.

    Read at startup, so a restart applies them. Every value is checked before
    anything is written.
    """
    try:
        data = (request.get_json(silent=True) or {}) if request.is_json else request.form
        host_server = _clean(data.get("host_server"))
        websocket_url = _clean(data.get("websocket_url"))
        if host_server is None or websocket_url is None:
            return _error("A value contains a line break. Paste it again as a single line.")

        updates = {}
        # ngrok_allow by key presence, not value truthiness, so it can be set
        # to FALSE.
        if "ngrok_allow" in data:
            ngrok_value = str(data.get("ngrok_allow")).strip().upper()
            updates["NGROK_ALLOW"] = "TRUE" if ngrok_value == "TRUE" else "FALSE"
        if host_server:
            if not re.match(r"^https?://.+", host_server):
                return _error("Invalid HOST_SERVER format. Must start with http:// or https://")
            updates["HOST_SERVER"] = host_server
        if websocket_url:
            if not re.match(r"^wss?://.+", websocket_url):
                return _error("Invalid WEBSOCKET_URL format. Must start with ws:// or wss://")
            updates["WEBSOCKET_URL"] = websocket_url
        if not updates:
            return _error("No settings provided to update")

        env_path = get_env_path()
        if not os.path.exists(env_path):
            return _error("Failed to read .env file: Environment file not found", 500)
        # One read-modify-write under the lock every .env writer shares,
        # through an atomic replace, so two saves at once keep both.
        try:
            update_env_values(env_path, updates)
        except Exception:
            logger.exception("Error writing .env file")
            return _error(
                "Could not write the .env file. Check that OpenAlgo can write to it, "
                "then try again.",
                500,
            )
        updated = list(updates)
        logger.info(f"Updated server settings: {', '.join(updated)}")
        return jsonify(
            {
                "status": "success",
                "message": f"Settings updated successfully. Updated: {', '.join(updated)}",
                "updated_fields": updated,
                "restart_required": True,
            }
        )
    except Exception:
        logger.exception("Error updating the server settings")
        return _error("Could not save the settings. Try again.", 500)


@broker_credentials_bp.route("/capabilities", methods=["GET"])
@check_session_validity
def get_capabilities():
    """Return broker capabilities (supported exchanges, type, features) from cached plugin.json."""
    from flask import session

    from utils.plugin_loader import get_broker_capabilities

    broker = session.get("broker")
    if not broker:
        return jsonify({"status": "error", "message": "No broker in session"}), 400

    capabilities = get_broker_capabilities(broker)
    if not capabilities:
        # Fallback for brokers without plugin.json capabilities
        return jsonify(
            {
                "status": "success",
                "data": {
                    "broker_name": broker,
                    "broker_type": "IN_stock",
                    "supported_exchanges": [],
                    "leverage_config": False,
                },
            }
        )

    return jsonify({"status": "success", "data": capabilities})
