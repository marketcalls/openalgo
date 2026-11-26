"""Order alerts to a Discord channel, through a Discord webhook.

Every message is posted with ``allowed_mentions`` empty, so nothing in it can
ping ``@everyone``, ``@here``, a user or a role, whoever wrote the text. In an
order alert every value is also escaped as Discord markdown, so a symbol or a
broker's rejection text shows exactly as it was sent. Text an API caller sends
keeps its markdown: they wrote it on purpose. Bold text uses Discord's double
asterisks.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from services.alerts.channels.webhook import WebhookChannel
from services.alerts.formatting import SEPARATOR, AlertMessage

#: Characters Discord markdown gives a meaning to. A backslash before each
#: shows it literally.
_MARKDOWN = re.compile(r"([\\*_~`|>#\[\]()-])")


class DiscordChannel(WebhookChannel):
    """Discord, through a channel webhook."""

    name = "discord"
    label = "Discord"
    setup_path = "/discord"

    hosts = frozenset({"discord.com", "discordapp.com", "ptb.discord.com", "canary.discord.com"})
    path_pattern = re.compile(r"/api(?:/v\d{1,2})?/webhooks/\d{1,20}/[A-Za-z0-9_-]+/?")
    #: A webhook into a forum or thread names the thread.
    query_pattern = re.compile(r"thread_id=\d{1,20}")
    max_length = 2000
    url_prefix = "https://discord.com/api/webhooks/"

    def render(self, message: AlertMessage) -> str:
        parts = [f"**{escape(message.title)}**"]
        if message.strategy:
            parts.append(f"Strategy: {escape(message.strategy)}")
        if message.banner:
            parts.extend([f"**{escape(message.banner)}**", SEPARATOR])
        parts.extend(escape(line) for line in message.lines)
        return "\n".join(parts)

    def render_text(self, text: str) -> str:
        return text

    def payload(self, text: str) -> dict[str, Any]:
        return {"content": text, "allowed_mentions": {"parse": []}}

    def accepted(self, response: httpx.Response) -> bool:
        return response.status_code in (200, 204)


def escape(text: str) -> str:
    """Show ``text`` literally in Discord markdown."""
    return _MARKDOWN.sub(r"\\\1", text)
