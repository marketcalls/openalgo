"""Order alerts to a Slack channel, through a Slack incoming webhook.

Slack reads ``&``, ``<`` and ``>`` as control characters: ``<!channel>``
notifies everybody in the channel and ``<url|text>`` makes a link. Every value
in an alert, and every message an API caller sends, has those three escaped,
so nothing in an order (a broker's rejection text, a strategy name) can ping a
channel or hide a link behind other text. A bare URL is still made a link by
Slack itself. Bold text uses Slack's single asterisks.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from services.alerts.channels.webhook import WebhookChannel
from services.alerts.formatting import SEPARATOR, AlertMessage


class SlackChannel(WebhookChannel):
    """Slack, through an incoming webhook."""

    name = "slack"
    label = "Slack"
    setup_path = "/slack"

    hosts = frozenset({"hooks.slack.com"})
    path_pattern = re.compile(r"/services/[A-Za-z0-9]+/[A-Za-z0-9]+/[A-Za-z0-9]+/?")
    #: Slack accepts up to 40,000 characters but truncates long messages in
    #: the client; an alert is never near this.
    max_length = 4000
    url_prefix = "https://hooks.slack.com/services/"

    def render(self, message: AlertMessage) -> str:
        parts = [f"*{escape(message.title)}*"]
        if message.strategy:
            parts.append(f"Strategy: {escape(message.strategy)}")
        if message.banner:
            parts.extend([f"*{escape(message.banner)}*", SEPARATOR])
        parts.extend(escape(line) for line in message.lines)
        return "\n".join(parts)

    def render_text(self, text: str) -> str:
        return escape(text)

    def payload(self, text: str) -> dict[str, Any]:
        return {"text": text}

    def accepted(self, response: httpx.Response) -> bool:
        return response.status_code == 200


def escape(text: str) -> str:
    """Escape Slack's three control characters. ``&`` first, or it escapes the others."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
