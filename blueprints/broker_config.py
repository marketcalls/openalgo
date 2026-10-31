# blueprints/broker_config.py
"""Broker Configuration and Select Broker, as OpenAlgo Desktop has them.

One key set per broker, for as many brokers as the trader likes, and one
broker logged in at a time. The pages keep no broker list of their own:
``GET /api/broker/list`` serves every broker in VALID_BROKERS with how it
signs in, its exchanges, the keys it needs (utils/broker_setup_guide.py) and a
masked view of what is saved. Nothing saved is ever returned in full: an API
key shows its first characters, a secret none.

The .env file still comes first. The broker it names keeps its keys there: a
save for it writes .env, and it cannot be forgotten here. Keys for any other
broker are saved in OpenAlgo (database/broker_keys_db.py).

There is no route that ends a session for a switch: logging in to another
broker ends the old session when the new login completes
(utils.auth_utils._hand_over_from_live_broker). New keys for the logged-in
broker, and forgetting it, end its session only with ``sign_out=true``, which
the page sends after the trader confirms. Every route needs a sign-in to
OpenAlgo and works before any broker login; writes are CSRF-checked by the
app.
"""

import re

from flask import Blueprint, jsonify, request, session

from blueprints.broker_credentials import get_env_path, mask_secret
from limiter import limiter
from utils.env_check import update_env_values
from utils.logging import get_logger
from utils.session import check_signed_in

logger = get_logger(__name__)

broker_config_bp = Blueprint("broker_config_bp", __name__, url_prefix="/api/broker")

#: Longest value accepted for one field. Real keys are well under 200 characters.
MAX_VALUE_LENGTH = 1024
MAX_REDIRECT_LENGTH = 500
WRITE_RATE_LIMIT = "20 per minute"

_KEY_FIELDS = ("api_key", "api_secret", "api_key_market", "api_secret_market")
_URL = re.compile(r"^https?://[^\s/?#]+(/[^\s?#]*)?$")


def _error(message, status=400):
    response = jsonify({"status": "error", "message": message})
    response.headers["Cache-Control"] = "no-store"
    return response, status


def _ok(payload):
    response = jsonify({"status": "success", **payload})
    response.headers["Cache-Control"] = "no-store"
    return response


def _clean(value):
    """A submitted value, stripped; None when it has a line break or control character."""
    value = str(value if value is not None else "").strip()
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return None
    return value


def _confirmed():
    return str(request.args.get("sign_out", "")).lower() == "true"


def _mask(field, value):
    if not value:
        return None
    return mask_secret(value, 6 if field in ("api_key", "api_key_market") else 0)


def _entry(broker, env_values, env_name, live, saved):
    """One broker as Select Broker and Broker Configuration show it."""
    from utils.broker_keys import broker_exchanges, default_redirect_url
    from utils.broker_setup_guide import guide

    entry = guide(broker)
    if broker == env_name:
        values, source, stored_redirect = env_values, "env", env_values["redirect_url"]
    elif broker in saved:
        row = saved[broker]
        values = {field: getattr(row, field) for field in _KEY_FIELDS}
        source, stored_redirect = "saved", row.redirect_url
    else:
        values, source, stored_redirect = {}, None, ""
    configured = bool(values.get("api_key"))

    redirect_url = automatic = hint = None
    if entry["sign_in"] == "redirect":
        automatic = default_redirect_url(broker)
        redirect_url = stored_redirect or automatic
        hint = entry["redirect_hint"] or None
    return {
        "id": broker,
        "name": entry["name"],
        "configured": configured,
        "active": broker == live,
        "sign_in": entry["sign_in"],
        "exchanges": list(broker_exchanges(broker)),
        "banner": entry["banner"],
        "fields": [
            {**f, "saved": _mask(f["key"], values.get(f["key"], ""))} for f in entry["fields"]
        ],
        "redirect_url": redirect_url,
        "redirect_url_automatic": automatic,
        "redirect_url_is_default": redirect_url == automatic,
        "redirect_hint": hint,
        "source": source if configured else None,
    }


@broker_config_bp.route("/list", methods=["GET"])
@check_signed_in
def list_brokers():
    """Every broker, what is saved for it (masked), and which one is logged in."""
    from database.broker_keys_db import list_broker_keys
    from utils.broker_keys import enabled_brokers, env_broker, env_file_values, live_broker
    from utils.broker_switch import switch_refusal

    env_values = env_file_values()
    env_name = env_broker(env_values)
    live = live_broker()
    saved = {row.broker: row for row in list_broker_keys()}
    brokers = [_entry(b, env_values, env_name, live, saved) for b in enabled_brokers()]
    return _ok(
        {
            "data": {
                "logged_in": live,
                "switch_refusal": switch_refusal(live, session["user"]) if live else None,
                "brokers": brokers,
            }
        }
    )


def _known_broker(broker):
    from utils.broker_keys import enabled_brokers

    broker = (broker or "").strip().lower()
    return broker if broker in enabled_brokers() else None


@broker_config_bp.route("/credentials/<broker>", methods=["PUT"])
@check_signed_in
@limiter.limit(WRITE_RATE_LIMIT)
def save_broker(broker):
    """Save a broker's keys and redirect URL. A key left blank keeps its value.

    ``redirect_url`` empty means the automatic address. New keys for the
    logged-in broker end its session, and only with ``sign_out=true``.
    """
    from database.broker_keys_db import save_broker_keys
    from utils.broker_keys import (
        default_redirect_url,
        env_broker,
        key_format_error,
        live_broker,
        login_slot_broker,
        resolve,
    )
    from utils.broker_setup_guide import FIELD_ENV_VARS, guide
    from utils.broker_switch import switch_refusal

    broker = _known_broker(broker)
    if broker is None:
        return _error("Choose a broker from the list.", 404)
    entry = guide(broker)
    name = entry["name"]
    data = (request.get_json(silent=True) or {}) if request.is_json else request.form
    used = {f["key"] for f in entry["fields"]}

    values = {}
    for field in _KEY_FIELDS:
        value = _clean(data.get(field))
        if value is None:
            return _error("A key contains a line break. Paste it again as a single line.")
        if len(value) > MAX_VALUE_LENGTH:
            return _error("A key is longer than any broker issues. Check what was pasted.")
        # Only the keys this broker uses are saved.
        values[field] = value if field in used else ""
    has_keys = any(values.values())

    redirect_url = None
    if "redirect_url" in data:
        redirect_url = _clean(data.get("redirect_url"))
        if redirect_url is None:
            return _error("A value contains a line break. Paste it again as a single line.")
        if entry["sign_in"] != "redirect":
            return _error(f"{name} does not use a redirect URL.")
        redirect_url = redirect_url.rstrip("/")
        suffix = f"/{broker}/callback"
        if redirect_url and (
            len(redirect_url) > MAX_REDIRECT_LENGTH
            or not _URL.match(redirect_url)
            or not redirect_url.endswith(suffix)
        ):
            return _error(
                f"Enter the redirect URL as a full address ending in {suffix}, "
                "or use the automatic one."
            )

    if not has_keys and redirect_url is None:
        return _error("Nothing to save. Enter a new value to replace a saved one.")
    if resolve(broker) is None:
        missing = next(
            (f for f in entry["fields"] if f["required"] and not values.get(f["key"])), None
        )
        if missing:
            return _error(f"Enter the {missing['label']} to save {name}.")
    format_error = key_format_error(broker, values["api_key"])
    if format_error:
        return _error(format_error)
    if login_slot_broker() == broker:
        return _error(
            f"A login to {name} is under way. Wait for it to finish, then try again.", 409
        )

    signed_out = False
    if has_keys and live_broker() == broker:
        # A session belongs to the keys it signed in with.
        if not _confirmed():
            return _error(
                f"You are logged in to {name} now. New keys end that session; confirm to save them.",
                409,
            )
        refusal = switch_refusal(broker, session["user"])
        if refusal:
            return _error(refusal, 409)

    if broker == env_broker():
        updates = {FIELD_ENV_VARS[f]: v for f, v in values.items() if v}
        if redirect_url is not None:
            updates["REDIRECT_URL"] = redirect_url or default_redirect_url(broker)
        env_path = get_env_path()
        try:
            update_env_values(env_path, updates)
        except Exception:
            logger.exception("Could not write the .env broker keys")
            return _error(
                "Could not write the .env file. Check that OpenAlgo can write to it, then try again.",
                500,
            )
    else:
        stored_redirect = None
        if redirect_url is not None:
            # The automatic address is stored as "", so it follows HOST_SERVER.
            stored_redirect = (
                "" if redirect_url in ("", default_redirect_url(broker)) else redirect_url
            )
        ok, message = save_broker_keys(broker, values, stored_redirect)
        if not ok:
            return _error(message, 400 if "Enter the API key" in message else 500)

    if has_keys and live_broker() == broker:
        from blueprints.auth import end_broker_session_keeping_this_browser

        end_broker_session_keeping_this_browser(
            session["user"], f"OpenAlgo was logged out of {name}: new keys were saved for it."
        )
        signed_out = True

    logger.info(f"Saved the {broker} broker settings")
    return _ok(
        {
            "message": (
                f"Saved your {name} keys and ended its session. Log in again to use them."
                if signed_out
                else f"Saved your {name} settings."
            ),
            "signed_out": signed_out,
        }
    )


@broker_config_bp.route("/credentials/<broker>", methods=["DELETE"])
@check_signed_in
@limiter.limit(WRITE_RATE_LIMIT)
def forget_broker(broker):
    """Remove a broker's saved keys; the logged-in one only with ``sign_out=true``."""
    from database.broker_keys_db import delete_broker_keys, get_broker_keys
    from utils.broker_keys import env_broker, live_broker, login_slot_broker
    from utils.broker_setup_guide import guide
    from utils.broker_switch import switch_refusal

    broker = _known_broker(broker)
    if broker is None:
        return _error("Choose a broker from the list.", 404)
    name = guide(broker)["name"]
    if broker == env_broker():
        return _error(
            f"Your {name} keys are in the .env file. Remove the broker lines there to forget them."
        )
    if get_broker_keys(broker) is None:
        return _error(f"No keys are saved for {name}.", 404)
    if login_slot_broker() == broker:
        return _error(
            f"A login to {name} is under way. Wait for it to finish, then try again.", 409
        )

    signed_out = False
    if live_broker() == broker:
        if not _confirmed():
            return _error(
                f"You are logged in to {name} now. Confirm to sign out of {name} and forget its keys.",
                409,
            )
        refusal = switch_refusal(broker, session["user"])
        if refusal:
            return _error(refusal, 409)
        from blueprints.auth import end_broker_session_keeping_this_browser

        end_broker_session_keeping_this_browser(
            session["user"], f"OpenAlgo was logged out of {name}: its keys were forgotten."
        )
        signed_out = True

    if not delete_broker_keys(broker):
        return _error(f"Your {name} keys were not forgotten. Try again.", 500)
    logger.info(f"Forgot the saved {broker} broker keys")
    return _ok(
        {
            "message": (
                f"Signed out of {name} and forgot its keys."
                if signed_out
                else f"Forgot your {name} keys."
            ),
            "signed_out": signed_out,
        }
    )
