"""Alert channels that post to an incoming webhook: Slack and Discord.

A trader creates an incoming webhook in Slack or Discord and pastes its URL on
the channel's page. OpenAlgo then posts each alert to that URL. Nothing is
hosted, no bot token is needed, and the channel works from any server.

**The URL is the credential.** Anybody holding it can post into that channel,
so it is treated like a password:

- It is accepted only for the provider's own webhook host and path
  (``validate_url``). The host is matched exactly, so a lookalike such as
  ``hooks.slack.com.example.net`` is refused, and because the request can only
  ever go to Slack's or Discord's public servers it cannot be turned against
  this server's own network. The saved URL is checked again before every send.
- It is stored encrypted (``database/alert_channels_db.py``), never sent back
  to the browser, and redacted from logs (``utils/url_redaction.py``).
- Errors name the provider and the next step, never the URL. An ``httpx``
  exception's text carries the URL, so it is never logged as such.
- Redirects are not followed, so a send always reaches the host that was
  checked.

**Sends never block an order.** ``deliver`` runs on an event-bus thread and
only queues the post on a small worker pool shared by every webhook channel.
The queue is bounded: past ``MAX_PENDING`` waiting posts an alert is dropped
and logged, because a provider that has stopped answering must not grow
memory in a worker that never restarts. A failed post is logged and not
retried; an alert retried a minute later describes a market that has moved.
"""

from __future__ import annotations

import re
import threading
from abc import abstractmethod
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, ClassVar
from urllib.parse import urlsplit

import httpx

from database.alert_channels_db import load_channel, read_webhook_url
from events.alert_events import AlertRaisedEvent
from services.alerts.channels.base import TEST_MESSAGE, AlertChannel, ChannelStatus, DeliveryResult
from services.alerts.formatting import AlertMessage, build_message
from utils.logging import get_logger

logger = get_logger(__name__)

#: How long one post may take. Both providers answer in well under a second;
#: this only bounds a stalled connection.
TIMEOUT_SECONDS = 10.0

#: Longest URL accepted. Real webhook URLs are around 120 characters.
MAX_URL_LENGTH = 500

#: Posts waiting or running at once, across every webhook channel.
MAX_PENDING = 200

#: One small pool for every webhook channel, created once (FD hygiene: never a
#: pool per call). Its threads only make HTTP requests through the shared
#: client and touch no database, so they need no session cleanup.
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="alert_webhook")
_pending_lock = threading.Lock()
_pending = 0


class InvalidWebhookUrl(ValueError):
    """A URL that is not this channel's webhook. The message is for the trader."""


class WebhookChannel(AlertChannel):
    """A channel that posts to an incoming webhook URL.

    Subclasses say which URLs are theirs and how a message looks:

    Attributes:
        hosts: The exact host names the webhook may live on.
        path_pattern: What the URL's path must match, in full.
        query_pattern: What its query string must match, in full. None means
            the URL may not have one.
        max_length: The longest message the provider accepts.
        url_prefix: How a valid URL begins, to show in error messages.
    """

    uses_webhook = True
    enabled_by_default = False

    hosts: ClassVar[frozenset[str]]
    path_pattern: ClassVar[re.Pattern[str]]
    query_pattern: ClassVar[re.Pattern[str] | None] = None
    max_length: ClassVar[int]
    url_prefix: ClassVar[str]

    # -- What the provider needs ------------------------------------------

    @abstractmethod
    def render(self, message: AlertMessage) -> str:
        """An order alert as this provider's text, with every value escaped."""

    @abstractmethod
    def render_text(self, text: str) -> str:
        """Text written by an API caller, made safe to post."""

    @abstractmethod
    def payload(self, text: str) -> dict[str, Any]:
        """The JSON body that posts ``text``."""

    @abstractmethod
    def accepted(self, response: httpx.Response) -> bool:
        """Whether the provider took the message."""

    # -- The webhook URL ----------------------------------------------------

    def validate_url(self, url: object) -> str:
        """Return ``url`` if it is this channel's webhook, else raise.

        Raises:
            InvalidWebhookUrl: With a sentence the trader can act on.
        """
        if not isinstance(url, str) or not url.strip():
            raise InvalidWebhookUrl(f"Paste the {self.label} webhook URL.")
        url = url.strip()
        if len(url) > MAX_URL_LENGTH or any(_unsafe(ch) for ch in url):
            raise self._not_ours()
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            raise self._not_ours() from None
        query_ok = (
            not parts.query
            if self.query_pattern is None
            else not parts.query or bool(self.query_pattern.fullmatch(parts.query))
        )
        if (
            parts.scheme != "https"
            or parts.hostname not in self.hosts
            or parts.username is not None
            or parts.password is not None
            or port not in (None, 443)
            or parts.fragment
            or not self.path_pattern.fullmatch(parts.path)
            or not query_ok
        ):
            raise self._not_ours()
        return url

    def saved_url(self) -> str | None:
        """The saved webhook URL, if there is one and it is still this channel's."""
        url = read_webhook_url(self.name)
        if url is None:
            return None
        try:
            return self.validate_url(url)
        except InvalidWebhookUrl:
            logger.warning(f"The saved {self.label} webhook is not a {self.label} URL; ignoring it")
            return None

    def _not_ours(self) -> InvalidWebhookUrl:
        return InvalidWebhookUrl(
            f"That is not a {self.label} webhook URL. It should begin with {self.url_prefix}"
        )

    # -- AlertChannel -------------------------------------------------------

    def status(self) -> ChannelStatus:
        stored = load_channel(self.name)
        if stored is None or not stored.webhook_saved:
            return ChannelStatus(
                configured=False,
                ready=False,
                detail=f"No webhook is saved yet. Add one on the {self.label} page.",
            )
        return ChannelStatus(
            configured=True,
            ready=True,
            detail=f"Webhook saved. Alerts post to your {self.label} channel.",
        )

    def deliver(self, alert: AlertRaisedEvent) -> None:
        url = self.saved_url()
        if url is None:
            return
        message = build_message(alert.api_type, alert.request_data, alert.response_data)
        _queue(self.post, url, self._fit(self.render(message)))

    def send_test(self) -> DeliveryResult:
        url = self.saved_url()
        if url is None:
            return DeliveryResult(
                delivered=False, message=f"Save a {self.label} webhook first, then send a test."
            )
        return self.post(url, self._fit(self.render_text(TEST_MESSAGE)))

    # -- Sending ------------------------------------------------------------

    def send_text(self, text: str, *, wait: bool) -> DeliveryResult:
        """Post text written by an API caller, now or in the background.

        Args:
            text: The message, already checked against ``max_length``.
            wait: Post now and report the outcome, rather than queue it.
        """
        url = self.saved_url()
        if url is None:
            return DeliveryResult(
                delivered=False,
                message=f"No {self.label} webhook is saved. Add one on the {self.label} "
                "page in OpenAlgo.",
            )
        rendered = self.render_text(text)
        if wait:
            return self.post(url, rendered)
        if _queue(self.post, url, rendered):
            return DeliveryResult(delivered=True, message="Notification queued.")
        return DeliveryResult(
            delivered=False,
            message=f"Too many {self.label} messages are waiting to be sent. Try again shortly.",
        )

    def post(self, url: str, text: str) -> DeliveryResult:
        """Post one message and report what happened. Never raises."""
        from utils.httpx_client import get_httpx_client

        try:
            response = get_httpx_client().post(
                url,
                json=self.payload(text),
                timeout=TIMEOUT_SECONDS,
                follow_redirects=False,
            )
        except httpx.TimeoutException:
            logger.warning(f"{self.label} alert not delivered: no answer within {TIMEOUT_SECONDS}s")
            return DeliveryResult(
                delivered=False, message=f"{self.label} did not answer in time. Try again shortly."
            )
        except httpx.InvalidURL:
            # validate_url should never let one through. The text names the URL.
            logger.warning(f"{self.label} alert not delivered: the webhook URL is malformed")
            return DeliveryResult(
                delivered=False,
                message=f"The saved {self.label} webhook URL cannot be used. Save it again on "
                f"the {self.label} page.",
            )
        except httpx.HTTPError as error:
            # The exception's text includes the URL, so only its type is logged.
            logger.warning(f"{self.label} alert not delivered: {type(error).__name__}")
            return DeliveryResult(
                delivered=False,
                message=f"OpenAlgo could not reach {self.label}. Check this server's internet "
                "connection.",
            )
        except Exception:
            # A bug, not a network failure. The log filter redacts the URL from
            # the traceback; the trader is told only that it failed.
            logger.exception(f"{self.label} alert could not be sent")
            return DeliveryResult(
                delivered=False, message=f"The {self.label} message could not be sent."
            )
        if self.accepted(response):
            return DeliveryResult(delivered=True, message=f"Message sent to {self.label}.")
        logger.warning(
            f"{self.label} refused an alert: HTTP {response.status_code} {response.text[:200]!r}"
        )
        return DeliveryResult(delivered=False, message=self._refusal(response.status_code))

    def _refusal(self, status_code: int) -> str:
        """What a refusal means for the trader."""
        if status_code in (401, 403, 404, 410):
            return (
                f"{self.label} no longer accepts this webhook. It may have been deleted, or "
                f"its channel archived. Create a new webhook and save it on the {self.label} page."
            )
        if status_code == 429:
            return f"{self.label} is limiting how fast messages are posted. Try again in a minute."
        if status_code >= 500:
            return f"{self.label} is having trouble right now. Try again later."
        return f"{self.label} refused the message. The OpenAlgo log has the details."

    def _fit(self, text: str) -> str:
        """Cut an alert to the provider's length limit. Only alerts ever reach it."""
        if len(text) <= self.max_length:
            return text
        return text[: self.max_length - 3] + "..."


def _unsafe(ch: str) -> bool:
    """A character no webhook URL contains: whitespace, a backslash, or a control."""
    return ch.isspace() or ch == "\\" or ord(ch) < 0x20 or ord(ch) == 0x7F


def _queue(send: Callable[..., DeliveryResult], *args: Any) -> bool:
    """Run ``send(*args)`` on the webhook pool. False when the queue is full."""
    global _pending
    with _pending_lock:
        if _pending >= MAX_PENDING:
            full = True
        else:
            _pending += 1
            full = False
    if full:
        logger.warning(f"Webhook alert queue is full ({MAX_PENDING} waiting); an alert was dropped")
        return False

    def run() -> None:
        global _pending
        try:
            send(*args)
        except Exception:
            logger.exception("Webhook alert send failed")
        finally:
            with _pending_lock:
                _pending -= 1

    try:
        _EXECUTOR.submit(run)
    except RuntimeError:
        # The pool is shut down: the process is exiting.
        with _pending_lock:
            _pending -= 1
        return False
    return True
