"""Slack and Discord webhooks: which URLs are accepted, and what gets posted.

A webhook URL is the credential for the trader's channel, so these tests pin
that only the provider's own webhook URLs are accepted, that one is stored
encrypted and checked again before every post, that it never appears in a log
line or in a reply, and that nothing in an alert can ping a whole channel.
"""

from __future__ import annotations

import logging
import threading
import time

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.orm import scoped_session, sessionmaker

import database.alert_channels_db as alert_channels_db
from database.engine_factory import create_db_engine
from events import OrderPlacedEvent
from services.alerts import router, settings
from services.alerts.channels import webhook
from services.alerts.channels.discord import DiscordChannel
from services.alerts.channels.slack import SlackChannel
from services.alerts.channels.webhook import InvalidWebhookUrl
from services.alerts.formatting import AlertMessage

# Obviously fake, so no secret scanner mistakes them for real webhooks.
SLACK_URL = "https://hooks.slack.com/services/TFAKE/BFAKE/notarealslacktoken"
DISCORD_URL = "https://discord.com/api/webhooks/1234/not-a-real-discord-token"
SECRETS = ("notarealslacktoken", "not-a-real-discord-token")


@pytest.fixture
def store(tmp_path, monkeypatch):
    """The alert settings table on a file of its own, and an empty cache."""
    engine = create_db_engine(f"sqlite:///{(tmp_path / 'openalgo.db').as_posix()}")
    session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
    monkeypatch.setattr(alert_channels_db, "engine", engine)
    monkeypatch.setattr(alert_channels_db, "db_session", session)
    previous = alert_channels_db.Base.__dict__["query"]
    alert_channels_db.Base.query = session.query_property()
    alert_channels_db.Base.metadata.create_all(engine)
    settings.clear_cache()
    try:
        yield engine
    finally:
        settings.clear_cache()
        alert_channels_db.Base.query = previous
        session.remove()
        engine.dispose()


@pytest.fixture
def provider(monkeypatch):
    """Stand in for Slack and Discord: record every request, answer as told."""
    state = {"status": 200, "body": "ok", "raise": None, "requests": []}

    def handle(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        if state["raise"] is not None:
            raise state["raise"]
        headers = {"Location": "http://127.0.0.1:5000/"} if state["status"] == 302 else {}
        return httpx.Response(state["status"], text=state["body"], headers=headers)

    client = httpx.Client(transport=httpx.MockTransport(handle))
    monkeypatch.setattr("utils.httpx_client.get_httpx_client", lambda: client)
    yield state
    client.close()


@pytest.fixture
def records():
    """The text of every log line the webhook module writes, as it wrote it.

    Rendered at emit time: the redaction filter on the app's own handlers
    rewrites each record in place as it propagates, so a record read later
    shows the redacted text and would hide a URL this module logged itself.
    """
    seen: list[str] = []

    class Keep(logging.Handler):
        def emit(self, record):
            seen.append(record.getMessage())

    handler = Keep(level=logging.DEBUG)
    webhook.logger.addHandler(handler)
    yield seen
    webhook.logger.removeHandler(handler)


# ---------------------------------------------------------------------------
# Which URLs are accepted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        SLACK_URL,
        SLACK_URL + "/",
        "  " + SLACK_URL + "  ",
        "https://hooks.slack.com:443/services/T1/B2/xyz",
        "https://HOOKS.SLACK.COM/services/T1/B2/xyz",
    ],
)
def test_slack_accepts_its_own_webhooks(url):
    assert SlackChannel().validate_url(url) == url.strip()


@pytest.mark.parametrize(
    "url",
    [
        DISCORD_URL,
        "https://discordapp.com/api/webhooks/1/token_-1",
        "https://discord.com/api/v10/webhooks/1/token",
        "https://ptb.discord.com/api/webhooks/1/token",
        "https://canary.discord.com/api/webhooks/1/token",
        "https://discord.com/api/webhooks/1/token?thread_id=987654321",
    ],
)
def test_discord_accepts_its_own_webhooks(url):
    assert DiscordChannel().validate_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "   ",
        42,
        "http://hooks.slack.com/services/T1/B2/xyz",  # not https
        "https://hooks.slack.com.example.net/services/T1/B2/xyz",  # lookalike host
        "https://example.net/hooks.slack.com/services/T1/B2/xyz",
        "https://evil@hooks.slack.com/services/T1/B2/xyz",  # credentials in the URL
        "https://user:pw@hooks.slack.com/services/T1/B2/xyz",
        "https://hooks.slack.com:8443/services/T1/B2/xyz",  # another port
        "https://hooks.slack.com/services/T1/B2/xyz#frag",
        "https://hooks.slack.com/services/T1/B2/xyz?redirect=1",
        "https://hooks.slack.com/triggers/T1/B2/xyz",  # a workflow, not a webhook
        "https://hooks.slack.com/services/T1/B2/../../../admin",
        "https://hooks.slack.com/services/T1/B2/xyz\\@127.0.0.1",
        "https://hooks.slack.com/services/T1/B2/x yz",
        "https://hooks.slack.com/services/T1/B2/xyz",  # a control character urlsplit drops
        "https://hooks.slack.com/services/T1/B2/xyz",
        "https://127.0.0.1/services/T1/B2/xyz",
        "https://hooks.slack.com/services/T1/B2/" + "x" * 600,
        DISCORD_URL,  # the other provider's webhook
    ],
)
def test_slack_refuses_anything_else(url):
    with pytest.raises(InvalidWebhookUrl):
        SlackChannel().validate_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://discord.com.example.net/api/webhooks/1/token",
        "https://evil-discord.com/api/webhooks/1/token",
        "https://discord.com/api/webhooks/notanumber/token",
        "https://discord.com/api/webhooks/1/token?thread_id=1&wait=true",
        "https://discord.com/api/webhooks/1/token?thread_id=abc",
        "https://discord.com/api/channels/1/messages",
        "https://cdn.discordapp.com/api/webhooks/1/token",
        "https://discord.gg/api/webhooks/1/token",
        SLACK_URL,
    ],
)
def test_discord_refuses_anything_else(url):
    with pytest.raises(InvalidWebhookUrl):
        DiscordChannel().validate_url(url)


def test_the_refusal_says_what_a_webhook_url_looks_like():
    with pytest.raises(InvalidWebhookUrl, match="https://hooks.slack.com/services/"):
        SlackChannel().validate_url("https://example.com/hook")


# ---------------------------------------------------------------------------
# What gets posted
# ---------------------------------------------------------------------------

MESSAGE = AlertMessage(
    title="Order Placed",
    banner="LIVE MODE - Real Order",
    strategy="mean_reversion <!channel>",
    lines=("Symbol: SBIN", "Error: Rejected <!here> & *bold* @everyone", "Time: 09:15:30"),
)


def test_slack_escapes_every_value_and_bolds_the_title():
    rendered = SlackChannel().render(MESSAGE)

    assert rendered.splitlines()[0] == "*Order Placed*"
    assert "<!channel>" not in rendered and "<!here>" not in rendered
    assert "&lt;!here&gt; &amp; *bold*" in rendered
    assert "<" not in rendered and ">" not in rendered


def test_slack_escapes_text_an_api_caller_sends():
    assert SlackChannel().render_text("<!channel> a & b") == "&lt;!channel&gt; a &amp; b"


def test_discord_shows_values_literally_and_bolds_the_title():
    rendered = DiscordChannel().render(MESSAGE)

    assert rendered.splitlines()[0] == "**Order Placed**"
    assert "Strategy: mean\\_reversion" in rendered
    assert "\\*bold\\*" in rendered


def test_nothing_posted_to_discord_can_mention_anyone():
    payload = DiscordChannel().payload("@everyone look")

    assert payload["allowed_mentions"] == {"parse": []}


def test_an_alert_too_long_for_discord_is_cut_to_fit():
    long = DiscordChannel()._fit("x" * 5000)

    assert len(long) == DiscordChannel.max_length and long.endswith("...")


# ---------------------------------------------------------------------------
# Posting, and what a failure tells the trader
# ---------------------------------------------------------------------------


def test_slack_takes_a_200(provider):
    result = SlackChannel().post(SLACK_URL, "hello")

    assert result.delivered
    assert provider["requests"][0].url == SLACK_URL
    assert provider["requests"][0].read() == b'{"text":"hello"}'


def test_discord_takes_a_204(provider):
    provider["status"] = 204

    assert DiscordChannel().post(DISCORD_URL, "hello").delivered


@pytest.mark.parametrize(
    ("status", "says"),
    [
        (404, "no longer accepts this webhook"),
        (403, "no longer accepts this webhook"),
        (410, "no longer accepts this webhook"),
        (429, "Try again in a minute"),
        (500, "having trouble"),
        (400, "refused the message"),
    ],
)
def test_a_refusal_names_the_cause_and_the_next_step(provider, status, says):
    provider["status"] = status

    result = SlackChannel().post(SLACK_URL, "hello")

    assert not result.delivered
    assert says in result.message
    assert str(status) not in result.message


def test_a_redirect_is_not_followed(provider):
    """A post goes only to the host that was checked."""
    provider["status"] = 302

    result = SlackChannel().post(SLACK_URL, "hello")

    assert not result.delivered
    assert len(provider["requests"]) == 1


@pytest.mark.parametrize(
    ("error", "says"),
    [
        (httpx.ConnectTimeout("timed out"), "did not answer in time"),
        (httpx.ConnectError("refused"), "could not reach Slack"),
    ],
)
def test_a_network_failure_is_explained(provider, error, says):
    provider["raise"] = error

    result = SlackChannel().post(SLACK_URL, "hello")

    assert not result.delivered and says in result.message


def test_a_url_httpx_cannot_send_to_is_reported_not_raised(provider):
    """httpx.InvalidURL is not an httpx.HTTPError; post() must still not raise."""
    result = SlackChannel().post("https://hooks.slack.com/services/T1/B2/", "hello")

    assert not result.delivered
    assert "Save it again on the Slack page" in result.message
    assert provider["requests"] == []


def test_an_unexpected_failure_is_reported_not_raised(provider, monkeypatch):
    def broken(self, text):
        raise RuntimeError("a bug")

    monkeypatch.setattr(SlackChannel, "payload", broken)

    result = SlackChannel().post(SLACK_URL, "hello")

    assert not result.delivered and "could not be sent" in result.message


@pytest.mark.parametrize("status", [404, 500])
def test_the_url_never_reaches_a_log_line_or_a_reply(provider, records, status):
    """An httpx exception's text carries the URL; it must not be logged as such."""
    provider["status"] = status
    replies = [SlackChannel().post(SLACK_URL, "hello").message]
    provider["raise"] = httpx.ConnectError(f"cannot connect to {SLACK_URL}")
    replies.append(SlackChannel().post(SLACK_URL, "hello").message)

    written = records + replies
    assert written
    assert not any(secret in line for line in written for secret in SECRETS)


# ---------------------------------------------------------------------------
# The saved URL
# ---------------------------------------------------------------------------


def test_a_saved_webhook_is_encrypted_and_reads_back(store):
    settings.save_webhook(SlackChannel(), SLACK_URL)

    with store.connect() as conn:
        raw = conn.execute(text("SELECT webhook_url FROM alert_channels")).scalar_one()
    assert SECRETS[0] not in raw
    assert SlackChannel().saved_url() == SLACK_URL


def test_saving_a_webhook_turns_the_channel_on_and_forgetting_it_turns_it_off(store):
    channel = DiscordChannel()

    assert settings.save_webhook(channel, DISCORD_URL).enabled
    assert channel.status().configured

    assert not settings.forget_webhook(channel).enabled
    assert channel.saved_url() is None
    assert not channel.status().configured


def test_a_stored_url_that_is_not_the_channels_is_never_posted_to(store, provider):
    """The saved URL is checked again before every post."""
    from database.auth_db import encrypt_token

    settings.save_webhook(SlackChannel(), SLACK_URL)
    with store.begin() as conn:
        conn.execute(
            text("UPDATE alert_channels SET webhook_url = :v"),
            {"v": encrypt_token("http://127.0.0.1:5000/admin")},
        )

    result = SlackChannel().send_test()

    assert not result.delivered
    assert provider["requests"] == []


def test_a_test_without_a_webhook_asks_for_one(store, provider):
    result = SlackChannel().send_test()

    assert not result.delivered and "Save a Slack webhook" in result.message
    assert provider["requests"] == []


# ---------------------------------------------------------------------------
# Order alerts are queued, and the queue is bounded
# ---------------------------------------------------------------------------


def test_an_order_alert_is_posted_in_the_background(store, provider):
    settings.save_webhook(DiscordChannel(), DISCORD_URL)
    provider["status"] = 204
    posted = threading.Event()
    original = DiscordChannel.post

    def post_and_signal(self, url, rendered):
        try:
            return original(self, url, rendered)
        finally:
            posted.set()

    alert = router.alert_for(
        OrderPlacedEvent(
            api_type="placeorder",
            request_data={"symbol": "SBIN", "action": "BUY"},
            response_data={"status": "success", "orderid": "42"},
        )
    )
    DiscordChannel.post = post_and_signal
    try:
        router.deliver(DiscordChannel(), alert)
        assert posted.wait(5)
    finally:
        DiscordChannel.post = original

    body = provider["requests"][0].read().decode()
    assert "**Order Placed**" in body and "Order ID: 42" in body
    assert '"allowed_mentions":{"parse":[]}' in body


def test_a_full_lane_drops_rather_than_grows():
    lane = webhook._Lane("probe", capacity=1)
    release = threading.Event()

    first = lane.submit(lambda: release.wait(5))
    second = lane.submit(lambda: None)
    release.set()

    assert first is True
    assert second is False


def test_a_stalled_provider_does_not_hold_up_the_other(store, provider):
    """Slack and Discord each have their own lane: Slack's full queue and busy
    threads must not delay or drop a Discord alert."""
    stalled = threading.Event()
    slack_lane = webhook._lane("slack")
    for _ in range(slack_lane.capacity):
        slack_lane.submit(lambda: stalled.wait(5))
    try:
        assert slack_lane.submit(lambda: None) is False  # Slack is full
        settings.save_webhook(DiscordChannel(), DISCORD_URL)
        provider["status"] = 204

        assert DiscordChannel().send_text("hi", wait=False).delivered
        deadline = time.monotonic() + 5
        while not provider["requests"] and time.monotonic() < deadline:
            time.sleep(0.01)
        assert [r.url.host for r in provider["requests"]] == ["discord.com"]
    finally:
        stalled.set()


def test_a_queued_post_is_never_sent_to_a_webhook_removed_meanwhile(store, provider):
    """A queued send reads the saved webhook when it runs, not when it was queued."""
    channel = SlackChannel()
    settings.save_webhook(channel, SLACK_URL)
    held = threading.Event()
    lane = webhook._lane("slack")
    lane.submit(lambda: held.wait(5))  # the lane's first thread is busy
    lane.submit(lambda: held.wait(5))  # and its second

    assert channel.send_text("hi", wait=False).delivered  # queued behind them
    settings.forget_webhook(channel)
    held.set()
    deadline = time.monotonic() + 5
    while lane.pending and time.monotonic() < deadline:
        time.sleep(0.01)

    # The queued send ran; it is not merely still waiting.
    assert lane.pending == 0
    assert provider["requests"] == []


def test_a_queued_post_is_never_sent_once_the_channel_is_switched_off(store, provider):
    """A trader who switches Slack off expects nothing more to arrive there,
    including a message that was already waiting its turn."""
    channel = SlackChannel()
    settings.save_webhook(channel, SLACK_URL)
    held = threading.Event()
    lane = webhook._lane("slack")
    lane.submit(lambda: held.wait(5))  # the lane's first thread is busy
    lane.submit(lambda: held.wait(5))  # and its second

    assert channel.send_text("hi", wait=False).delivered  # queued behind them
    settings.update_settings(channel, enabled=False)
    held.set()
    deadline = time.monotonic() + 5
    while lane.pending and time.monotonic() < deadline:
        time.sleep(0.01)

    # The queued send ran; it is not merely still waiting.
    assert lane.pending == 0
    assert provider["requests"] == []


def test_an_unusable_saved_webhook_reads_as_not_set_up(store):
    """A ciphertext that no longer decrypts must not show the channel ready."""
    settings.save_webhook(SlackChannel(), SLACK_URL)
    with store.begin() as conn:
        conn.execute(text("UPDATE alert_channels SET webhook_url = 'not-a-ciphertext'"))

    state = SlackChannel().status()

    assert not state.configured and not state.ready
    assert "Save it again" in state.detail
