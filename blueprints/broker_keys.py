# blueprints/broker_keys.py
"""Broker keys saved in OpenAlgo: list, save, remove, and copy from .env.

Reachable once the trader has signed in to OpenAlgo, before any broker login,
because a new install may have no broker in .env at all and has to add one here
first. Keys and secrets go in and never come back out: a read returns a masked
prefix and the length only.

The .env file stays first. A broker it sets keys for is shown as such, and keys
saved here for that same broker are kept but not used until the .env lines are
removed. "Copy from .env" saves the .env broker's keys here, which is how an
install moves off .env.
"""

import re
from datetime import UTC

from flask import Blueprint, jsonify, request, session

from blueprints.broker_credentials import mask_secret
from database.broker_keys_db import (
    clear_broker_key_fields,
    delete_broker_keys,
    list_broker_keys,
    save_broker_keys,
)
from limiter import limiter
from utils.broker_keys import (
    broker_from_redirect_url,
    broker_title,
    default_redirect_url,
    enabled_brokers,
    env_broker,
    env_file_values,
    key_format_error,
    live_broker,
)
from utils.logging import get_logger

logger = get_logger(__name__)

broker_keys_bp = Blueprint("broker_keys_bp", __name__, url_prefix="/api/broker/keys")

#: Longest value accepted for one field. Real keys are well under 200 characters.
MAX_VALUE_LENGTH = 1024
MAX_REDIRECT_LENGTH = 500
WRITE_RATE_LIMIT = "20 per minute"

_REDIRECT_PATTERN = re.compile(r"^https?://[^\s/?#]+(/[^\s?#]*)?/([a-z0-9_]+)/callback$")
_FIELDS = ("api_key", "api_secret", "api_key_market", "api_secret_market")


def _error(message, status=400):
    return jsonify({"status": "error", "message": message}), status


def _signed_in():
    return "user" in session


def _masked(prefix, value):
    """A field as the page shows it, never the value.

    An API key is the app's public client id at the broker, so a short prefix
    helps tell two apart. A secret shows no character at all, and not even its
    length: whether it is set is all the page needs.
    """
    return {
        prefix: mask_secret(value, 6 if prefix.startswith("api_key") else 0),
        f"{prefix}_set": bool(value),
    }


def _describe(source, broker, values, redirect_url):
    out = {"broker": broker, "name": broker_title(broker), "source": source}
    for field in _FIELDS:
        out.update(_masked(field, values.get(field, "")))
    out["redirect_url"] = redirect_url
    return out


def _redirect_to_store(broker, redirect_url):
    """What to store for a redirect URL: "" for this host's default address.

    An empty column follows HOST_SERVER, so a broker saved with the default
    address keeps working after the domain changes; only an address the
    trader set themselves is stored.
    """
    return "" if redirect_url == default_redirect_url(broker) else redirect_url


def _clean(value):
    """A submitted value, stripped; None when it has a line break or control character."""
    value = (value or "").strip()
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return None
    return value


@broker_keys_bp.route("", methods=["GET"])
def list_keys():
    """The saved keys, the .env broker and the brokers keys can be saved for."""
    if not _signed_in():
        return _error("Sign in to OpenAlgo first.", 401)

    enabled = enabled_brokers()
    env = env_file_values()
    env_name = env_broker(env)
    saved = []
    for stored in list_broker_keys():
        item = _describe(
            "saved",
            stored.broker,
            {field: getattr(stored, field) for field in _FIELDS},
            stored.redirect_url or default_redirect_url(stored.broker),
        )
        item["enabled"] = stored.broker in enabled
        item["overridden_by_env"] = stored.broker == env_name
        # Stored as naive UTC; sent with its offset so the page shows local time.
        item["updated_at"] = (
            stored.updated_at.replace(tzinfo=UTC).isoformat() if stored.updated_at else None
        )
        saved.append(item)

    return jsonify(
        {
            "status": "success",
            "data": {
                "brokers": saved,
                "env": _describe("env", env_name, env, env["redirect_url"]) if env_name else None,
                "enabled_brokers": [{"broker": b, "name": broker_title(b)} for b in enabled],
                "live_broker": live_broker(),
                "default_redirect_urls": {b: default_redirect_url(b) for b in enabled},
            },
        }
    )


@broker_keys_bp.route("", methods=["POST"])
@limiter.limit(WRITE_RATE_LIMIT)
def save_keys():
    """Save one broker's keys. A field left empty keeps the saved value."""
    if not _signed_in():
        return _error("Sign in to OpenAlgo first.", 401)

    data = request.get_json(silent=True) or request.form
    broker = str(data.get("broker") or "").strip().lower()
    if broker not in enabled_brokers():
        return _error("Choose a broker from the list.")

    live = live_broker()
    if live == broker:
        return _error(
            f"OpenAlgo is logged in to {broker_title(broker)}. Log out of OpenAlgo, or end that "
            "session on the broker login page, then change its keys.",
            409,
        )

    values = {}
    for field in _FIELDS:
        value = _clean(data.get(field))
        if value is None:
            return _error("A key contains a line break. Paste it again as a single line.")
        if len(value) > MAX_VALUE_LENGTH:
            return _error("A key is longer than any broker issues. Check what was pasted.")
        values[field] = value

    format_error = key_format_error(broker, values["api_key"])
    if format_error:
        return _error(format_error)

    redirect_url = _clean(data.get("redirect_url"))
    if redirect_url is None or len(redirect_url) > MAX_REDIRECT_LENGTH:
        return _error("The redirect URL is not valid.")
    if redirect_url:
        match = _REDIRECT_PATTERN.match(redirect_url)
        if not match or broker_from_redirect_url(redirect_url) != broker:
            return _error(
                f"The redirect URL must start with http:// or https:// and end with /{broker}/callback."
            )
        redirect_url = _redirect_to_store(broker, redirect_url)
    else:
        # Left empty: keep the saved address (a new broker gets the default).
        redirect_url = None

    ok, message = save_broker_keys(broker, values, redirect_url)
    if not ok:
        return _error(message, 400 if "Enter the API key" in message else 500)

    # Clearing the market data keys never removes one sent in this request.
    if str(data.get("clear_market_keys")).lower() in ("1", "true", "yes", "on"):
        to_clear = [f for f in ("api_key_market", "api_secret_market") if not values[f]]
        if to_clear:
            clear_broker_key_fields(broker, to_clear)

    changed = [field for field in _FIELDS if values[field]]
    logger.info(f"Saved the {broker} broker keys (fields: {', '.join(changed) or 'none'})")
    note = ""
    if broker == env_broker():
        note = (
            " The .env file also sets keys for this broker, and those are used until "
            "you remove them from .env."
        )
    return jsonify(
        {"status": "success", "message": f"Saved the {broker_title(broker)} keys.{note}"}
    )


@broker_keys_bp.route("/<broker>", methods=["DELETE"])
@limiter.limit(WRITE_RATE_LIMIT)
def remove_keys(broker):
    """Remove one broker's saved keys."""
    if not _signed_in():
        return _error("Sign in to OpenAlgo first.", 401)

    broker = (broker or "").strip().lower()
    if live_broker() == broker:
        return _error(
            f"OpenAlgo is logged in to {broker_title(broker)}. Log out of OpenAlgo, or end that "
            "session on the broker login page, then remove its keys.",
            409,
        )
    if not delete_broker_keys(broker):
        return _error("No keys are saved for that broker.", 404)
    logger.info(f"Removed the saved {broker} broker keys")
    return jsonify({"status": "success", "message": f"Removed the {broker_title(broker)} keys."})


@broker_keys_bp.route("/import-env", methods=["POST"])
@limiter.limit(WRITE_RATE_LIMIT)
def import_env_keys():
    """Save the .env broker's keys in OpenAlgo, the first step off .env."""
    if not _signed_in():
        return _error("Sign in to OpenAlgo first.", 401)

    env = env_file_values()
    broker = env_broker(env)
    if not broker:
        return _error("The .env file does not set keys for a broker.")
    if broker not in enabled_brokers():
        return _error(f"{broker_title(broker)} is not in VALID_BROKERS in the .env file.")

    redirect_url = env["redirect_url"]
    ok, message = save_broker_keys(
        broker,
        {field: env[field] for field in _FIELDS},
        _redirect_to_store(broker, redirect_url) if redirect_url else None,
    )
    if not ok:
        return _error(message, 500)
    logger.info(f"Copied the .env keys for {broker} into OpenAlgo")
    return jsonify(
        {
            "status": "success",
            "message": (
                f"Copied the {broker_title(broker)} keys from .env. OpenAlgo keeps using the "
                ".env keys until you remove them from .env, then uses these."
            ),
        }
    )
