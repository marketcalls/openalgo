"""Regression tests for the active-session heartbeat (audit #2).

`update_session_last_seen` was dead code, so active_sessions.last_seen stayed
frozen at login_time and the active-session list could not distinguish live
devices from closed ones. These tests lock in (a) the throttled heartbeat wired
into /session-status and (b) that update_session_last_seen actually advances the
row.
"""

import atexit
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from flask import Flask, session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Env must be set before importing auth_db / blueprints.auth.
TEST_DB = Path(__file__).resolve().parents[1] / "tmp" / "test_session_heartbeat.db"
TEST_DB.parent.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB.as_posix()}")
os.environ.setdefault("API_KEY_PEPPER", "a" * 64)
atexit.register(lambda: TEST_DB.unlink(missing_ok=True))

import blueprints.auth as auth_module  # noqa: E402
import database.auth_db as auth_db  # noqa: E402


@pytest.fixture()
def app_ctx():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    return app


def test_heartbeat_updates_on_first_poll(monkeypatch, app_ctx):
    calls = []
    monkeypatch.setattr("database.auth_db.update_session_last_seen", lambda sid: calls.append(sid))
    with app_ctx.test_request_context("/"):
        session["user"] = "rajandran"
        session["logged_in"] = True
        session["session_id"] = "device-A"
        auth_module._touch_session_heartbeat()
    assert calls == ["device-A"]


def test_heartbeat_throttled_within_window(monkeypatch, app_ctx):
    calls = []
    monkeypatch.setattr("database.auth_db.update_session_last_seen", lambda sid: calls.append(sid))
    with app_ctx.test_request_context("/"):
        session["user"] = "rajandran"
        session["logged_in"] = True
        session["session_id"] = "device-A"
        auth_module._touch_session_heartbeat()  # first write
        auth_module._touch_session_heartbeat()  # within throttle window — skipped
    assert calls == ["device-A"]


def test_heartbeat_fires_again_after_window(monkeypatch, app_ctx):
    calls = []
    monkeypatch.setattr("database.auth_db.update_session_last_seen", lambda sid: calls.append(sid))
    with app_ctx.test_request_context("/"):
        session["user"] = "rajandran"
        session["logged_in"] = True
        session["session_id"] = "device-A"
        old = datetime.now(UTC) - timedelta(
            seconds=auth_module.HEARTBEAT_THROTTLE_SECONDS + 10
        )
        session["last_heartbeat"] = old.isoformat()
        auth_module._touch_session_heartbeat()
    assert calls == ["device-A"]


def test_heartbeat_noop_without_session_id(monkeypatch, app_ctx):
    calls = []
    monkeypatch.setattr("database.auth_db.update_session_last_seen", lambda sid: calls.append(sid))
    with app_ctx.test_request_context("/"):
        session["user"] = "rajandran"
        session["logged_in"] = True  # no session_id
        auth_module._touch_session_heartbeat()
    assert calls == []


def test_update_session_last_seen_advances_row():
    """The previously-dead update_session_last_seen must actually move last_seen."""
    auth_db.init_db()
    auth_db.ActiveSession.query.filter_by(session_id="hb-sid").delete()
    auth_db.db_session.commit()

    auth_db.register_session("rajandran", "hb-sid", ip_address="10.0.0.1")
    row = auth_db.ActiveSession.query.filter_by(session_id="hb-sid").first()
    before = row.last_seen

    auth_db.update_session_last_seen("hb-sid")
    auth_db.db_session.expire_all()
    after = auth_db.ActiveSession.query.filter_by(session_id="hb-sid").first().last_seen

    assert after >= before

    auth_db.ActiveSession.query.filter_by(session_id="hb-sid").delete()
    auth_db.db_session.commit()
