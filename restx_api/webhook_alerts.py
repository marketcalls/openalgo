"""Slack and Discord send API: post a message to the saved webhook.

Mounted at ``/api/v1/slack`` and ``/api/v1/discord``. Like the WhatsApp
namespace, each exposes exactly one endpoint, ``POST /notify``, and it can
only post a message. Saving or removing a webhook, turning a channel on or
off and choosing its event groups are done on the session-authenticated
/alerts, /slack and /discord pages, so a leaked API key can never read or
replace a webhook URL.

Request::

    {"apikey": "...", "message": "Breakout on NIFTY", "wait_for_delivery": false}

The API key may also be sent in the ``X-API-KEY`` header. It is not accepted
in the query string, where proxies and access logs keep it.

A message posts only while the channel is switched on at /alerts and has a
webhook saved, the same rule automated order alerts follow. By default it is
queued and the call returns at once; ``"wait_for_delivery": true`` posts it
first and reports whether the provider accepted it.
"""

from __future__ import annotations

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource, fields

from database.auth_db import verify_api_key
from limiter import limiter
from services.alerts.channels.webhook import WebhookChannel
from services.alerts.notify import message_problem, notify
from services.alerts.registry import get_webhook_channel
from utils.logging import get_logger

logger = get_logger(__name__)

#: Both providers allow about 30 posts a minute per webhook; more would only
#: be refused upstream.
NOTIFY_RATE_LIMIT = "30 per minute"


def build_namespace(channel_name: str) -> Namespace:
    """The REST namespace for one webhook channel."""
    channel = get_webhook_channel(channel_name)
    if channel is None:
        raise ValueError(f"{channel_name} is not a webhook alert channel")

    api = Namespace(channel.name, description=f"{channel.label} send API")
    notify_model = api.model(
        f"{channel.label}Notification",
        {
            "apikey": fields.String(required=True, description="OpenAlgo API key"),
            "message": fields.String(
                required=True,
                description=f"Text to post, at most {channel.max_length} characters.",
            ),
            "wait_for_delivery": fields.Boolean(
                default=False,
                description="Post now and report whether it was accepted, instead of queueing.",
            ),
        },
    )

    class Notify(Resource):
        @limiter.limit(NOTIFY_RATE_LIMIT)
        @api.doc(security="apikey")
        @api.expect(notify_model)
        def post(self):
            """Post a message to the saved webhook."""
            return _notify(channel)

    Notify.__name__ = f"{channel.label}Notify"
    api.route("/notify", strict_slashes=False)(Notify)
    return api


def _notify(channel: WebhookChannel):
    """Handle one notify request for ``channel``."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _reply("error", "Send the request as a JSON object.", 400)

    api_key = data.get("apikey") or request.headers.get("X-API-KEY")
    if not isinstance(api_key, str) or not api_key or not verify_api_key(api_key):
        return _reply("error", "Invalid or missing API key", 401)

    message = data.get("message")
    problem = message_problem(channel, message)
    if problem:
        return _reply("error", problem, 400)
    wait = data.get("wait_for_delivery", False)
    if not isinstance(wait, bool):
        return _reply("error", "'wait_for_delivery' must be true or false.", 400)

    result = notify(channel, message, wait=wait)
    return _reply("success" if result.ok else "error", result.message, result.status_code)


def _reply(status: str, message: str, code: int):
    return make_response(jsonify({"status": status, "message": message}), code)


slack_ns = build_namespace("slack")
discord_ns = build_namespace("discord")
