"""The /alerts page's API: every alert channel, its switch and its routing.

Session-authenticated and CSRF-protected like every other page API. External
callers send through ``/api/v1/slack/notify`` and ``/api/v1/discord/notify``
instead, which can only post a message, never change a setting.

Routes, all under ``/alerts/channels``:

- ``GET    /alerts/channels``                     every channel and event group
- ``POST   /alerts/channels/<name>``              switch on or off, choose groups
- ``PUT    /alerts/channels/<name>/webhook``      save a Slack or Discord webhook
- ``DELETE /alerts/channels/<name>/webhook``      forget it
- ``POST   /alerts/channels/<name>/test``         send a test message now

A webhook URL is accepted here and never returned: a channel reports only
whether one is saved.
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, jsonify, request

from limiter import limiter
from services.alerts import settings as alert_settings
from services.alerts.categories import CATEGORIES
from services.alerts.channels.base import AlertChannel
from services.alerts.channels.webhook import InvalidWebhookUrl
from services.alerts.registry import CHANNELS, get_channel, get_webhook_channel
from utils.keyed_locks import LockBusy
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

alert_channels_bp = Blueprint("alert_channels_bp", __name__, url_prefix="/alerts/channels")

#: A test message is a real send to a real account; a few a minute is plenty.
TEST_RATE_LIMIT = "5 per minute"


@alert_channels_bp.route("", methods=["GET"])
@check_session_validity
def list_channels():
    """Every channel with its status and settings, and every event group."""
    return jsonify(
        {
            "status": "success",
            "data": {
                "categories": [
                    {"id": c.id, "label": c.label, "description": c.description} for c in CATEGORIES
                ],
                "channels": [_describe(channel) for channel in CHANNELS],
            },
        }
    )


@alert_channels_bp.route("/<name>", methods=["POST"])
@check_session_validity
def update_channel(name: str):
    """Turn a channel on or off, or choose the event groups it receives."""
    channel = get_channel(name)
    if channel is None:
        return _error("There is no such alert channel.", 404)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error("Send the settings as a JSON object.", 400)

    enabled = body.get("enabled")
    categories = body.get("categories")
    if enabled is not None and not isinstance(enabled, bool):
        return _error("'enabled' must be true or false.", 400)
    if categories is not None and not (
        isinstance(categories, list) and all(isinstance(c, str) for c in categories)
    ):
        return _error("'categories' must be a list of event group names.", 400)
    try:
        alert_settings.update_settings(channel, enabled=enabled, categories=categories)
    except alert_settings.UnknownCategory as error:
        return _error(str(error), 400)
    except alert_settings.WebhookRequired as error:
        return _error(str(error), 409)
    except LockBusy:
        return _busy()
    except Exception:
        logger.exception(f"Could not save the {channel.label} alert settings")
        return _error("The settings could not be saved. Try again.", 500)
    return jsonify({"status": "success", "data": _describe(channel)})


@alert_channels_bp.route("/<name>/webhook", methods=["PUT"])
@check_session_validity
def save_webhook(name: str):
    """Save a Slack or Discord webhook URL. The channel is turned on."""
    channel = get_webhook_channel(name)
    if channel is None:
        return _error("Only Slack and Discord use a webhook.", 404)
    body = request.get_json(silent=True)
    url = body.get("url") if isinstance(body, dict) else None
    try:
        valid = channel.validate_url(url)
    except InvalidWebhookUrl as error:
        return _error(str(error), 400)
    try:
        alert_settings.save_webhook(channel, valid)
    except LockBusy:
        return _busy()
    except Exception:
        logger.exception(f"Could not save the {channel.label} webhook")
        return _error("The webhook could not be saved. Try again.", 500)
    logger.info(f"{channel.label} webhook saved")
    return jsonify({"status": "success", "data": _describe(channel)})


@alert_channels_bp.route("/<name>/webhook", methods=["DELETE"])
@check_session_validity
def forget_webhook(name: str):
    """Forget a Slack or Discord webhook URL. The channel is turned off."""
    channel = get_webhook_channel(name)
    if channel is None:
        return _error("Only Slack and Discord use a webhook.", 404)
    try:
        alert_settings.forget_webhook(channel)
    except LockBusy:
        return _busy()
    except Exception:
        logger.exception(f"Could not remove the {channel.label} webhook")
        return _error("The webhook could not be removed. Try again.", 500)
    logger.info(f"{channel.label} webhook removed")
    return jsonify({"status": "success", "data": _describe(channel)})


@alert_channels_bp.route("/<name>/test", methods=["POST"])
@check_session_validity
@limiter.limit(TEST_RATE_LIMIT)
def send_test(name: str):
    """Send a test message through one channel, and say whether it arrived."""
    channel = get_channel(name)
    if channel is None:
        return _error("There is no such alert channel.", 404)
    try:
        result = channel.send_test()
    except Exception:
        logger.exception(f"The {channel.label} test message failed")
        return _error(f"The {channel.label} test message could not be sent.", 500)
    if not result.delivered:
        return _error(result.message, 409)
    return jsonify({"status": "success", "message": result.message})


def _describe(channel: AlertChannel) -> dict[str, Any]:
    """One channel as the page shows it. Never includes a webhook URL."""
    settings = alert_settings.settings_for(channel)
    try:
        state = channel.status()
        status = {"configured": state.configured, "ready": state.ready, "detail": state.detail}
    except Exception:
        logger.exception(f"Could not read the {channel.label} channel status")
        status = {
            "configured": False,
            "ready": False,
            "detail": f"OpenAlgo could not check {channel.label}. Open its page for details.",
        }
    return {
        "name": channel.name,
        "label": channel.label,
        "setup_path": channel.setup_path,
        "uses_webhook": channel.uses_webhook,
        "enabled": settings.enabled,
        "categories": sorted(settings.categories),
        "status": status,
    }


def _busy():
    """Another change to the same channel held it too long."""
    return _error("Another change to this channel is still being saved. Try again.", 409)


def _error(message: str, status_code: int):
    return jsonify({"status": "error", "message": message}), status_code
