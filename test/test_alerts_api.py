"""The /alerts page API, the Slack and Discord notify endpoints, and storage.

The page API changes settings and saves webhooks, so it needs a signed-in
session and a CSRF token, and it never returns a webhook URL. The notify
endpoints need an API key and can only post. The table reaches existing
installs by migration, and its encrypted column survives a key rotation.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import httpx
import pytest
import pytz
from flask import Flask
from flask_restx import Api
from sqlalchemy import text
from sqlalchemy.orm import scoped_session, sessionmaker

import database.alert_channels_db as alert_channels_db
import database.auth_db as auth_db
import utils.session as session_utils
from database.engine_factory import create_db_engine
from services.alerts import settings
from services.alerts.registry import get_channel
from utils.url_redaction import redact_url_credentials

REPO_ROOT = Path(__file__).resolve().parent.parent
# Obviously fake, so no secret scanner mistakes them for real webhooks.
SLACK_URL = "https://hooks.slack.com/services/TFAKE/BFAKE/notarealslacktoken"
DISCORD_URL = "https://discord.com/api/webhooks/1234/not-a-real-discord-token"


@pytest.fixture(autouse=True)
def _limiter_left_as_found():
    """Put the shared limiter's on/off flag back after each test.

    ``limiter.init_app`` keeps the last app's RATELIMIT_ENABLED for the next
    app that sets none, so the apps here that switch it off would switch it
    off for every later file in the run (the Flow webhook rate-limit tests
    then saw 200 where they expect 429).
    """
    from limiter import limiter

    enabled = limiter.enabled
    yield
    limiter.enabled = enabled


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
    """Stand in for Slack and Discord."""
    state = {"status": 200, "requests": []}

    def handle(request):
        state["requests"].append(request)
        return httpx.Response(state["status"], text="ok")

    client = httpx.Client(transport=httpx.MockTransport(handle))
    monkeypatch.setattr("utils.httpx_client.get_httpx_client", lambda: client)
    yield state
    client.close()


@pytest.fixture
def quiet_channels(monkeypatch):
    """Telegram and WhatsApp report a fixed status instead of reading their bots."""
    from services.alerts.channels.base import ChannelStatus

    for name in ("telegram", "whatsapp"):
        monkeypatch.setattr(
            type(get_channel(name)),
            "status",
            lambda self: ChannelStatus(configured=False, ready=False, detail="not set up"),
        )


def _page_app(csrf: bool = False) -> Flask:
    from blueprints.alert_channels import alert_channels_bp
    from limiter import limiter

    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["WTF_CSRF_ENABLED"] = csrf
    app.config["RATELIMIT_ENABLED"] = False
    limiter.init_app(app)
    if csrf:
        from flask_wtf.csrf import CSRFProtect

        CSRFProtect(app)
    app.register_blueprint(alert_channels_bp)
    return app


@pytest.fixture
def page(store, quiet_channels, monkeypatch):
    """A signed-in client for the /alerts page API."""
    monkeypatch.setattr(session_utils, "is_session_expiry_disabled", lambda: True)
    monkeypatch.setattr(auth_db, "get_sessions_revoked_at", lambda username: None)
    monkeypatch.setattr(auth_db, "get_pre_broker_revoked_at", lambda username: None)
    client = _page_app().test_client()
    stamp = datetime.now(pytz.timezone("Asia/Kolkata")).isoformat()
    with client.session_transaction() as cookie:
        cookie.update({"user": "trader", "logged_in": True, "login_time": stamp, "auth_at": stamp})
    return client


# ---------------------------------------------------------------------------
# The /alerts page API
# ---------------------------------------------------------------------------


def _channel(body: dict, name: str) -> dict:
    return next(c for c in body["data"]["channels"] if c["name"] == name)


def test_the_page_lists_every_channel_and_group(page):
    body = page.get("/alerts/channels").get_json()

    assert [c["name"] for c in body["data"]["channels"]] == [
        "telegram",
        "whatsapp",
        "slack",
        "discord",
    ]
    assert [g["id"] for g in body["data"]["categories"]][0] == "orders_placed"
    assert _channel(body, "telegram")["enabled"] is True
    assert _channel(body, "slack")["enabled"] is False
    assert _channel(body, "slack")["setup_path"] == "/slack"


def test_the_page_api_needs_a_signed_in_session(store, quiet_channels):
    client = _page_app().test_client()

    response = client.get("/alerts/channels", headers={"Accept": "application/json"})

    assert response.status_code == 401


def test_a_change_needs_the_csrf_token(page, monkeypatch):
    client = _page_app(csrf=True).test_client()
    stamp = datetime.now(pytz.timezone("Asia/Kolkata")).isoformat()
    with client.session_transaction() as cookie:
        cookie.update({"user": "trader", "logged_in": True, "login_time": stamp, "auth_at": stamp})

    response = client.put("/alerts/channels/slack/webhook", json={"url": SLACK_URL})

    assert response.status_code == 400
    assert get_channel("slack").saved_url() is None


def test_a_channel_can_be_switched_off_and_rerouted(page):
    response = page.post(
        "/alerts/channels/telegram", json={"enabled": False, "categories": ["gtt_orders"]}
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["enabled"] is False
    assert settings.settings_for(get_channel("telegram")).categories == {"gtt_orders"}


@pytest.mark.parametrize(
    ("body", "says"),
    [
        ({"enabled": "yes"}, "true or false"),
        ({"categories": "orders_placed"}, "list"),
        ({"categories": ["orders_placed", "bogus"]}, "Unknown event group"),
    ],
)
def test_a_bad_change_is_refused(page, body, says):
    response = page.post("/alerts/channels/telegram", json=body)

    assert response.status_code == 400
    assert says in response.get_json()["message"]


def test_an_unknown_channel_is_404(page):
    assert page.post("/alerts/channels/sms", json={"enabled": True}).status_code == 404
    assert page.put("/alerts/channels/telegram/webhook", json={"url": SLACK_URL}).status_code == 404


def test_slack_cannot_be_switched_on_without_a_webhook(page):
    response = page.post("/alerts/channels/slack", json={"enabled": True})

    assert response.status_code == 409
    assert not settings.settings_for(get_channel("slack")).enabled


def test_a_saved_webhook_is_never_sent_back(page):
    saved = page.put("/alerts/channels/slack/webhook", json={"url": SLACK_URL})
    listed = page.get("/alerts/channels")

    assert saved.status_code == 200
    assert saved.get_json()["data"]["enabled"] is True
    for response in (saved, listed):
        assert "notarealslacktoken" not in response.get_data(as_text=True)
        assert "hooks.slack.com" not in response.get_data(as_text=True)


def test_a_webhook_for_the_wrong_provider_is_refused(page):
    response = page.put("/alerts/channels/slack/webhook", json={"url": DISCORD_URL})

    assert response.status_code == 400
    assert "not a Slack webhook URL" in response.get_json()["message"]
    assert get_channel("slack").saved_url() is None


def test_forgetting_a_webhook_turns_the_channel_off(page):
    page.put("/alerts/channels/discord/webhook", json={"url": DISCORD_URL})

    response = page.delete("/alerts/channels/discord/webhook")

    assert response.get_json()["data"]["enabled"] is False
    assert get_channel("discord").saved_url() is None


def test_two_changes_to_one_channel_at_once_both_land(store):
    """Staged at the write: a second change arrives while the first is inside
    its save. Without the per-channel lock the second read the row before the
    first wrote it, and whichever wrote last undid the other."""
    telegram = get_channel("telegram")
    original = alert_channels_db.save_channel
    first_is_writing, release = threading.Event(), threading.Event()
    calls = []

    def held(channel, **fields):
        calls.append(fields)
        if len(calls) == 1:
            first_is_writing.set()
            release.wait(2)
        return original(channel, **fields)

    alert_channels_db.save_channel = held
    try:
        switch = threading.Thread(target=lambda: settings.update_settings(telegram, enabled=False))
        switch.start()
        assert first_is_writing.wait(5)
        route = threading.Thread(
            target=lambda: settings.update_settings(telegram, categories=["gtt_orders"])
        )
        route.start()
        time.sleep(0.3)  # long enough for an unserialised second change to finish
        release.set()
        switch.join(5)
        route.join(5)
    finally:
        alert_channels_db.save_channel = original

    stored = alert_channels_db.load_channel("telegram")
    assert stored.enabled is False
    assert stored.categories == ("gtt_orders",)


def test_a_change_never_starts_from_the_defaults_when_the_row_cannot_be_read(store, monkeypatch):
    """Telegram switched off must not be switched back on by a failed read."""
    telegram = get_channel("telegram")
    settings.update_settings(telegram, enabled=False)
    settings.clear_cache()

    def unreadable(channel):
        raise RuntimeError("database is locked")

    original = alert_channels_db.load_channel
    alert_channels_db.load_channel = unreadable
    try:
        with pytest.raises(RuntimeError):
            settings.update_settings(telegram, categories=["gtt_orders"])
    finally:
        alert_channels_db.load_channel = original

    stored = alert_channels_db.load_channel("telegram")
    assert stored.enabled is False
    assert set(stored.categories) != {"gtt_orders"}


def test_a_webhook_removed_while_slack_is_switched_on_never_leaves_it_on(page):
    """Staged at the write: the webhook is removed after the switch-on checked
    for one and before it saved. The check used to run before the channel's
    lock, so the removal landed in between and Slack was saved as on with no
    webhook."""
    slack = get_channel("slack")
    settings.save_webhook(slack, SLACK_URL)
    settings.update_settings(slack, enabled=False)
    status = type(slack).status
    checked, release = threading.Event(), threading.Event()

    def held(self):
        state = status(self)
        checked.set()
        release.wait(2)
        return state

    type(slack).status = held
    try:
        switch_on = threading.Thread(
            target=lambda: page.post("/alerts/channels/slack", json={"enabled": True})
        )
        switch_on.start()
        assert checked.wait(5)
        remove = threading.Thread(target=lambda: settings.forget_webhook(slack))
        remove.start()
        time.sleep(0.3)  # long enough for an unserialised removal to finish
        release.set()
        switch_on.join(5)
        remove.join(5)
    finally:
        type(slack).status = status

    stored = alert_channels_db.load_channel("slack")
    assert not (stored.enabled and not stored.webhook_saved), stored


@pytest.mark.parametrize(
    ("method", "path", "target"),
    [
        ("put", "/alerts/channels/slack/webhook", "save_webhook"),
        ("delete", "/alerts/channels/slack/webhook", "forget_webhook"),
    ],
)
def test_a_webhook_change_waiting_too_long_is_refused_not_failed(
    page, monkeypatch, method, path, target
):
    from utils.keyed_locks import LockBusy

    def busy(*args, **kwargs):
        raise LockBusy("slack", "alert channel settings", 10)

    monkeypatch.setattr(settings, target, busy)

    response = getattr(page, method)(path, json={"url": SLACK_URL})

    assert response.status_code == 409
    assert "still being saved" in response.get_json()["message"]


def test_a_status_that_cannot_be_read_is_a_controlled_error(page, monkeypatch):
    monkeypatch.setattr(
        type(get_channel("slack")), "status", lambda self: (_ for _ in ()).throw(OSError("x"))
    )

    response = page.post("/alerts/channels/slack", json={"enabled": True})

    assert response.status_code == 500
    assert response.get_json()["message"] == "The settings could not be saved. Try again."


def test_a_change_waiting_too_long_for_another_is_refused(page, monkeypatch):
    from utils.keyed_locks import LockBusy

    def busy(channel, **change):
        raise LockBusy("telegram", "alert channel settings", 10)

    monkeypatch.setattr(settings, "update_settings", busy)

    response = page.post("/alerts/channels/telegram", json={"enabled": False})

    assert response.status_code == 409
    assert "still being saved" in response.get_json()["message"]


def test_a_test_message_reports_what_happened(page, provider):
    page.put("/alerts/channels/slack/webhook", json={"url": SLACK_URL})

    sent = page.post("/alerts/channels/slack/test")
    provider["status"] = 404
    refused = page.post("/alerts/channels/slack/test")

    assert sent.status_code == 200
    assert refused.status_code == 409
    assert "Create a new webhook" in refused.get_json()["message"]


# ---------------------------------------------------------------------------
# /api/v1/slack/notify and /api/v1/discord/notify
# ---------------------------------------------------------------------------


@pytest.fixture
def api(store, provider, monkeypatch):
    """The two notify namespaces on an app of their own, with one valid key."""
    from limiter import limiter
    from restx_api import webhook_alerts

    monkeypatch.setattr(
        webhook_alerts, "verify_api_key", lambda key: "trader" if key == "good" else None
    )
    app = Flask(__name__)
    app.config["RATELIMIT_ENABLED"] = False
    limiter.init_app(app)
    rest = Api(app, prefix="/api/v1")
    rest.add_namespace(webhook_alerts.slack_ns, path="/slack")
    rest.add_namespace(webhook_alerts.discord_ns, path="/discord")
    return app.test_client()


def _notify(client, channel: str, **body):
    return client.post(
        f"/api/v1/{channel}/notify", json={"apikey": "good", "message": "hi", **body}
    )


def test_notify_needs_a_valid_api_key(api):
    assert _notify(api, "slack", apikey="bad").status_code == 401
    assert api.post("/api/v1/slack/notify", json={"message": "hi"}).status_code == 401


def test_notify_does_not_take_the_key_from_the_query_string(api):
    """Proxies and access logs keep query strings."""
    response = api.post("/api/v1/slack/notify?apikey=good", json={"message": "hi"})

    assert response.status_code == 401


def test_slack_and_discord_each_have_their_own_rate_limit(store, provider, monkeypatch):
    """One factory builds both namespaces; their limits must not share a bucket."""
    from limiter import limiter
    from restx_api import webhook_alerts

    monkeypatch.setattr(webhook_alerts, "verify_api_key", lambda key: "trader")
    app = Flask(__name__)
    app.config["RATELIMIT_ENABLED"] = True
    limiter.init_app(app)
    limiter.reset()
    rest = Api(app, prefix="/api/v1")
    rest.add_namespace(webhook_alerts.slack_ns, path="/slack")
    rest.add_namespace(webhook_alerts.discord_ns, path="/discord")
    client = app.test_client()
    allowance = int(webhook_alerts.NOTIFY_RATE_LIMIT.split()[0])
    try:
        slack = [_notify(client, "slack").status_code for _ in range(allowance + 1)]
        discord = _notify(client, "discord").status_code
    finally:
        limiter.reset()

    assert 429 not in slack[:allowance]
    assert slack[-1] == 429
    assert discord != 429


def test_notify_takes_the_key_from_the_header(api):
    settings.save_webhook(get_channel("slack"), SLACK_URL)

    response = api.post(
        "/api/v1/slack/notify", json={"message": "hi"}, headers={"X-API-KEY": "good"}
    )

    assert response.status_code == 200


def test_notify_needs_the_channel_switched_on(api):
    settings.save_webhook(get_channel("slack"), SLACK_URL)
    settings.update_settings(get_channel("slack"), enabled=False)

    response = _notify(api, "slack")

    assert response.status_code == 409
    assert "turned off" in response.get_json()["message"]


def test_notify_without_a_usable_webhook_says_so(api, store):
    """Switched on, but the saved webhook no longer decrypts (a key rotated
    without the rotation script, say). Switching on with no webhook at all is
    refused earlier, by update_settings."""
    settings.save_webhook(get_channel("discord"), DISCORD_URL)
    with store.begin() as conn:
        conn.execute(text("UPDATE alert_channels SET webhook_url = 'not-a-ciphertext'"))

    response = _notify(api, "discord")

    assert response.status_code == 409
    assert "No Discord webhook is saved" in response.get_json()["message"]


@pytest.mark.parametrize(
    ("body", "says"),
    [
        ({"message": ""}, "'message' is required"),
        ({"message": 7}, "'message' is required"),
        ({"message": "x" * 2001}, "at most 2000"),
        ({"wait_for_delivery": "yes"}, "true or false"),
    ],
)
def test_notify_checks_its_input(api, body, says):
    settings.save_webhook(get_channel("discord"), DISCORD_URL)

    response = _notify(api, "discord", **body)

    assert response.status_code == 400
    assert says in response.get_json()["message"]


def test_notify_waits_for_delivery_when_asked(api, provider):
    settings.save_webhook(get_channel("discord"), DISCORD_URL)
    provider["status"] = 204

    response = _notify(api, "discord", message="@everyone buy", wait_for_delivery=True)

    assert response.status_code == 200
    payload = json.loads(provider["requests"][0].read())
    assert payload == {"content": "@everyone buy", "allowed_mentions": {"parse": []}}


def test_notify_reports_a_refused_delivery(api, provider):
    settings.save_webhook(get_channel("slack"), SLACK_URL)
    provider["status"] = 404

    response = _notify(api, "slack", wait_for_delivery=True)

    assert response.status_code == 502
    assert "no longer accepts this webhook" in response.get_json()["message"]


def test_slack_notify_escapes_mentions(api, provider):
    settings.save_webhook(get_channel("slack"), SLACK_URL)

    _notify(api, "slack", message="<!channel> stop", wait_for_delivery=True)

    assert json.loads(provider["requests"][0].read()) == {"text": "&lt;!channel&gt; stop"}


# ---------------------------------------------------------------------------
# Storage: migration, key rotation, log redaction
# ---------------------------------------------------------------------------


def _run_migration(monkeypatch, db_file: Path, *args: str) -> int:
    sys.path.insert(0, str(REPO_ROOT / "upgrade"))
    try:
        import migrate_alert_channels as migration
    finally:
        sys.path.remove(str(REPO_ROOT / "upgrade"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setattr(sys, "argv", ["migrate_alert_channels.py", *args])
    return migration.main()


def test_the_migration_adds_the_table_and_no_rows(tmp_path, monkeypatch, capsys):
    import sqlite3

    db_file = tmp_path / "old.db"
    with sqlite3.connect(db_file) as old:
        old.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")

    assert _run_migration(monkeypatch, db_file, "--status") == 0
    assert "Would create 1 table." in capsys.readouterr().out
    assert _run_migration(monkeypatch, db_file) == 0
    assert _run_migration(monkeypatch, db_file) == 0
    assert "[SKIP]" in capsys.readouterr().out
    with sqlite3.connect(db_file) as db:
        assert db.execute("SELECT count(*) FROM alert_channels").fetchone() == (0,)


def test_the_migration_is_registered_and_required():
    """A required migration's failure reaches migrate_all's exit code instead
    of being reported as a warning."""
    import ast

    # Read, not imported: migrate_all replaces sys.stdout at import on Windows.
    tree = ast.parse((REPO_ROOT / "upgrade" / "migrate_all.py").read_text(encoding="utf-8"))
    assigned = {
        node.targets[0].id: node.value
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
    }
    names = [script for script, _ in ast.literal_eval(assigned["MIGRATIONS"])]
    required = ast.literal_eval(assigned["REQUIRED_MIGRATIONS"].args[0])

    assert "migrate_alert_channels.py" in names
    assert "migrate_alert_channels.py" in required
    assert "migrate_password_reset_grants.py" in required


def _fernet(pepper: str, salt: bytes):
    import base64

    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(pepper.encode())))


def _table_with_webhook(db_file: Path, ciphertext: str) -> None:
    engine = create_db_engine(f"sqlite:///{db_file.as_posix()}")
    alert_channels_db.Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO alert_channels (channel, enabled, categories, webhook_url, updated_at) "
                "VALUES ('slack', 1, '', :ct, '2026-11-11 00:00:00')"
            ),
            {"ct": ciphertext},
        )
    engine.dispose()


def _stored_webhook(db_file: Path) -> str:
    engine = create_db_engine(f"sqlite:///{db_file.as_posix()}")
    with engine.connect() as conn:
        value = conn.execute(text("SELECT webhook_url FROM alert_channels")).scalar_one()
    engine.dispose()
    return value


def test_the_salt_migration_re_encrypts_saved_webhooks(tmp_path, monkeypatch):
    import utils.env_check as env_check

    pepper, new_salt = "p" * 64, os.urandom(16).hex()
    db_file = tmp_path / "openalgo.db"
    _table_with_webhook(
        db_file, _fernet(pepper, b"openalgo_static_salt").encrypt(SLACK_URL.encode()).decode()
    )
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")

    env_check._migrate_fernet_db(str(tmp_path / ".env"), pepper, new_salt)

    stored = _stored_webhook(db_file)
    assert _fernet(pepper, bytes.fromhex(new_salt)).decrypt(stored.encode()).decode() == SLACK_URL


def test_the_lost_salt_check_reads_saved_webhooks(tmp_path):
    """env_check samples every auth_db ciphertext to tell a lost salt from a new one."""
    import utils.env_check as env_check

    db_file = tmp_path / "openalgo.db"
    _table_with_webhook(db_file, "gAAAA-a-webhook-ciphertext")

    assert env_check._sample_ciphertexts(str(db_file)) == ["gAAAA-a-webhook-ciphertext"]


def test_the_pepper_rotation_uses_the_installs_own_salt(tmp_path, monkeypatch):
    """An install with FERNET_SALT encrypts with that salt; a rotation that
    used the static salt could decrypt none of it and then wrote the new
    pepper anyway, leaving every secret unreadable."""
    import sqlite3

    sys.path.insert(0, str(REPO_ROOT / "upgrade"))
    try:
        import rotate_pepper
    finally:
        sys.path.remove(str(REPO_ROOT / "upgrade"))

    salt = os.urandom(16)
    monkeypatch.setenv("FERNET_SALT", salt.hex())
    old_pepper, new_pepper = "c" * 64, "d" * 64
    db_file = tmp_path / "openalgo.db"
    _table_with_webhook(db_file, _fernet(old_pepper, salt).encrypt(SLACK_URL.encode()).decode())

    with sqlite3.connect(db_file) as conn:
        rotator = rotate_pepper.Rotator(conn, old_pepper, new_pepper)
        rotator.rotate_all()
        conn.commit()

    assert rotator.stats["alert_channels.webhook_url"] == 1
    assert (
        _fernet(new_pepper, salt).decrypt(_stored_webhook(db_file).encode()).decode() == SLACK_URL
    )


def test_the_pepper_rotation_re_encrypts_saved_webhooks(tmp_path, monkeypatch):
    """An install with no FERNET_SALT of its own uses the static salt."""
    import sqlite3

    monkeypatch.delenv("FERNET_SALT", raising=False)

    sys.path.insert(0, str(REPO_ROOT / "upgrade"))
    try:
        import rotate_pepper
    finally:
        sys.path.remove(str(REPO_ROOT / "upgrade"))

    old_pepper, new_pepper = "a" * 64, "b" * 64
    db_file = tmp_path / "openalgo.db"
    _table_with_webhook(
        db_file, rotate_pepper._auth_db_fernet(old_pepper).encrypt(SLACK_URL.encode()).decode()
    )

    with sqlite3.connect(db_file) as conn:
        rotator = rotate_pepper.Rotator(conn, old_pepper, new_pepper)
        rotator.rotate_all()
        conn.commit()

    stored = _stored_webhook(db_file)
    assert rotate_pepper._auth_db_fernet(new_pepper).decrypt(stored.encode()).decode() == SLACK_URL
    assert rotator.stats["alert_channels.webhook_url"] == 1


@pytest.mark.parametrize(
    "url",
    [
        SLACK_URL,
        DISCORD_URL,
        "https://discordapp.com/api/v10/webhooks/1/secret-token",
        "https://canary.discord.com/api/webhooks/1/secret-token?thread_id=5",
        "https://hooks.slack.com:443/services/T1/B2/secret-token",
        "https://discord.com:443/api/webhooks/1/secret-token",
    ],
)
def test_a_webhook_url_is_redacted_from_logs(url):
    line = redact_url_credentials(f"POST {url} failed")

    assert "<redacted>" in line
    assert url.split("/")[-1].split("?")[0] not in line
