"""Post a caller's own text to a webhook alert channel.

The one set of rules for text a trader writes, wherever it is sent from: the
``/api/v1/slack/notify`` and ``/api/v1/discord/notify`` endpoints, the Flow
Slack and Discord nodes, and the MCP tools (which call the endpoints). Keeping
them here is what stops a Flow node posting while the REST call with the same
message would be refused, or the other way round.

A message posts only while the channel is switched on at /alerts and has a
usable webhook saved, the same rule automated order alerts follow.
"""

from __future__ import annotations

from dataclasses import dataclass

from services.alerts.channels.webhook import WebhookChannel
from services.alerts.settings import settings_for


@dataclass(frozen=True)
class NotifyResult:
    """What happened to one message.

    Attributes:
        ok: The message was posted, or queued to be posted.
        message: A sentence for the trader.
        status_code: The HTTP status the REST endpoint answers with.
    """

    ok: bool
    message: str
    status_code: int


def message_problem(channel: WebhookChannel, message: object) -> str | None:
    """Why ``message`` cannot be posted to ``channel``, or None when it can."""
    if not isinstance(message, str) or not message.strip():
        return "'message' is required."
    if len(message) > channel.max_length:
        return f"'message' must be at most {channel.max_length} characters."
    return None


def notify(
    channel: WebhookChannel, message: object, *, wait: bool = False, shorten: bool = False
) -> NotifyResult:
    """Post ``message`` to the channel's saved webhook, or say why not.

    Args:
        channel: Slack or Discord.
        message: The text to post.
        wait: Post now and report whether the provider accepted it, instead
            of queueing it on the channel's own lane.
        shorten: Cut a message over the channel's limit to fit, instead of
            refusing it. For callers nobody is watching, such as a running
            Flow, where a refused alert is simply lost.

    Returns:
        The outcome. Never raises for a refusal. A settings table that cannot
        be read gives the channel's defaults (``settings_for``), under which
        Slack and Discord are off, so the answer is "turned off" and nothing
        is posted.
    """
    if shorten and isinstance(message, str) and len(message) > channel.max_length:
        message = message[: channel.max_length - 3] + "..."
    problem = message_problem(channel, message)
    if problem:
        return NotifyResult(False, problem, 400)

    if not settings_for(channel).enabled:
        return NotifyResult(
            False,
            f"{channel.label} alerts are turned off. Turn them on from the Alerts page in OpenAlgo.",
            409,
        )

    result = channel.send_text(message, wait=wait)
    if result.delivered:
        return NotifyResult(True, result.message, 200)
    if channel.saved_url() is None:
        return NotifyResult(False, result.message, 409)
    return NotifyResult(False, result.message, 502 if wait else 503)
