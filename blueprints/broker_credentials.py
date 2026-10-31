# blueprints/broker_credentials.py
"""
Broker credentials, as the Profile Broker tab shows and saves them.

The current broker is the active one (utils.broker_keys.active_broker), as in
OpenAlgo Desktop. Keys for the broker the .env file names are saved to .env,
which comes first and is read at startup; keys for any other broker are saved
in OpenAlgo (database/broker_keys_db.py) and apply at once. Choosing another
broker makes it the active one, and ends a live session of a different broker
first, as the desktop does. Reachable once signed in to OpenAlgo, before any
broker login: a new install adds its first broker here.
"""

import os
import re

from flask import Blueprint, jsonify, request, session

from limiter import limiter
from utils.env_check import update_env_values
from utils.logging import get_logger
from utils.session import check_session_validity, check_signed_in

logger = get_logger(__name__)

broker_credentials_bp = Blueprint("broker_credentials_bp", __name__, url_prefix="/api/broker")

#: Longest value accepted for one field. Real keys are well under 200 characters.
MAX_VALUE_LENGTH = 1024
MAX_REDIRECT_LENGTH = 500
WRITE_RATE_LIMIT = "20 per minute"

_REDIRECT_PATTERN = re.compile(r"^https?://[^\s/?#]+(/[^\s?#]*)?/([a-z0-9_]+)/callback$")

#: Each key field, its .env name, and how many characters its mask shows: an
#: API key is the app's public id at the broker, a secret shows none.
_KEY_FIELDS = (
    ("api_key", "BROKER_API_KEY", 6),
    ("api_secret", "BROKER_API_SECRET", 0),
    ("api_key_market", "BROKER_API_KEY_MARKET", 6),
    ("api_secret_market", "BROKER_API_SECRET_MARKET", 0),
)


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
    """The current broker's credentials, masked, for the Profile Broker tab.

    A value from .env also reports its length, as this page always has; a key
    saved in OpenAlgo reports only whether it is set.
    """
    try:
        from utils.broker_keys import active_broker, resolve

        current = active_broker() or ""
        keys = resolve(current) if current else None
        from_env = keys is not None and keys.source == "env"

        data = {}
        for field, _env_name, shown in _KEY_FIELDS:
            value = getattr(keys, field) if keys else ""
            data[f"broker_{field}"] = mask_secret(value, shown)
            data[f"broker_{field}_raw_length"] = len(value) if from_env else 0
            data[f"broker_{field}_set"] = bool(value)

        valid_brokers = get_env_value("VALID_BROKERS")
        data.update(
            {
                "redirect_url": keys.redirect_url if keys else "",
                "current_broker": current,
                "source": keys.source if keys else None,
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
            }
        )
        return jsonify({"status": "success", "data": data})
    except Exception:
        logger.exception("Error getting broker credentials")
        return _error("Could not read the broker settings. Try again.", 500)


@broker_credentials_bp.route("/configured", methods=["GET"])
@check_signed_in
def get_configured():
    """Every broker with keys, the .env broker first, and which one is active."""
    from utils.broker_keys import active_broker, configured_brokers

    active = active_broker()
    brokers = [{"name": b["broker"], "active": b["broker"] == active} for b in configured_brokers()]
    return jsonify({"status": "success", "data": {"brokers": brokers, "active": active}})


@broker_credentials_bp.route("/credentials", methods=["POST"])
@check_signed_in
@limiter.limit(WRITE_RATE_LIMIT)
def update_credentials():
    """Save broker keys and settings, and switch the active broker.

    Keys go to .env for the broker .env names, which comes first and is read
    at startup, and to OpenAlgo for any other broker, where they apply at
    once. A redirect_url naming another broker makes it the active one,
    ending a live session of a different broker first, as OpenAlgo Desktop
    does. Every value is checked before anything is written.
    """
    from database.broker_keys_db import save_broker_keys, set_active_broker
    from utils.broker_keys import (
        active_broker,
        broker_from_redirect_url,
        broker_title,
        default_redirect_url,
        enabled_brokers,
        env_broker,
        key_format_error,
        live_broker,
        login_slot_broker,
        resolve,
    )

    try:
        data = (request.get_json(silent=True) or {}) if request.is_json else request.form

        values = {}
        for field, env_name, _shown in _KEY_FIELDS:
            value = _clean(data.get(f"broker_{field}"))
            if value is None:
                return _error(
                    f"The value for {env_name} contains a line break. "
                    "Paste it again as a single line."
                )
            if len(value) > MAX_VALUE_LENGTH:
                return _error(
                    f"The value for {env_name} is longer than any broker issues. "
                    "Check what was pasted."
                )
            values[field] = value

        redirect_url = _clean(data.get("redirect_url"))
        host_server = _clean(data.get("host_server"))
        websocket_url = _clean(data.get("websocket_url"))
        if redirect_url is None or host_server is None or websocket_url is None:
            return _error("A value contains a line break. Paste it again as a single line.")

        current = active_broker()
        target = current
        if redirect_url:
            if len(redirect_url) > MAX_REDIRECT_LENGTH or not _REDIRECT_PATTERN.match(redirect_url):
                return _error("Invalid redirect URL format. Must end with /<broker>/callback")
            target = broker_from_redirect_url(redirect_url)
            valid = enabled_brokers()
            if target not in valid:
                return _error(
                    f"Invalid broker '{target}'. Valid brokers: {', '.join(sorted(valid))}"
                )

        has_keys = any(values.values())
        if has_keys and not target:
            return _error("Choose your broker before saving its API key.")
        if has_keys:
            format_error = key_format_error(target, values["api_key"])
            if format_error:
                return _error(format_error)

        switching = bool(redirect_url) and target != current
        keys_to_env = has_keys and target == env_broker()
        keys_to_store = has_keys and not keys_to_env

        env_updates = {}
        if keys_to_env:
            for field, env_name, _shown in _KEY_FIELDS:
                if values[field]:
                    env_updates[env_name] = values[field]

        # ngrok_allow by key presence, not value truthiness, so it can be set
        # to FALSE.
        if "ngrok_allow" in data:
            ngrok_value = str(data.get("ngrok_allow")).strip().upper()
            env_updates["NGROK_ALLOW"] = "TRUE" if ngrok_value == "TRUE" else "FALSE"
        if host_server:
            if not re.match(r"^https?://.+", host_server):
                return _error("Invalid HOST_SERVER format. Must start with http:// or https://")
            env_updates["HOST_SERVER"] = host_server
        if websocket_url:
            if not re.match(r"^wss?://.+", websocket_url):
                return _error("Invalid WEBSOCKET_URL format. Must start with ws:// or wss://")
            env_updates["WEBSOCKET_URL"] = websocket_url

        if not (env_updates or keys_to_store or switching):
            return _error("No credentials provided to update")

        # The keys a login is putting in place, and the keys of the broker
        # whose orders are reading them, stay as they are.
        pending = login_slot_broker()
        if pending and (switching or keys_to_store):
            return _error(
                f"A login to {broker_title(pending)} is under way. "
                "Wait for it to finish, then try again.",
                409,
            )
        if keys_to_store and live_broker() == target:
            return _error(
                f"OpenAlgo is logged in to {broker_title(target)}. Log out of OpenAlgo, "
                f"then save new keys for {broker_title(target)}.",
                409,
            )
        if switching and not has_keys and resolve(target) is None:
            return _error(f"Enter the API key for {broker_title(target)}, then save.")

        env_path = get_env_path()
        if env_updates and not os.path.exists(env_path):
            return _error("Failed to read .env file: Environment file not found", 500)

        updated = []
        if env_updates:
            # One read-modify-write under the lock every .env writer shares,
            # through an atomic replace, so two saves at once keep both.
            try:
                update_env_values(env_path, env_updates)
            except Exception:
                logger.exception("Error writing .env file")
                return _error(
                    "Could not write the .env file. Check that OpenAlgo can write to it, "
                    "then try again.",
                    500,
                )
            updated += list(env_updates)

        if keys_to_store:
            stored_redirect = None
            if redirect_url:
                # The default address is stored as "", so it follows HOST_SERVER.
                stored_redirect = (
                    "" if redirect_url == default_redirect_url(target) else redirect_url
                )
            ok, message = save_broker_keys(target, values, stored_redirect)
            if not ok:
                return _error(message, 400 if "Enter the API key" in message else 500)
            updated += [env_name for field, env_name, _shown in _KEY_FIELDS if values[field]]

        signed_out_of = None
        if switching:
            live = live_broker()
            if live and live != target and session.get("user"):
                from blueprints.auth import end_broker_session_for_switch

                end_broker_session_for_switch(session["user"], live, target)
                signed_out_of = live
            if not set_active_broker(target):
                return _error("Could not switch the broker. Try again.", 500)
            updated.append("REDIRECT_URL")

        logger.info(f"Updated broker credentials: {', '.join(updated)}")
        return jsonify(
            {
                "status": "success",
                "message": f"Credentials updated successfully. Updated: {', '.join(updated)}",
                "updated_fields": updated,
                "restart_required": bool(env_updates),
                "broker_switched": switching,
                "signed_out_of": signed_out_of,
            }
        )

    except Exception:
        logger.exception("Error updating broker credentials")
        return _error("Could not save the broker settings. Try again.", 500)


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
