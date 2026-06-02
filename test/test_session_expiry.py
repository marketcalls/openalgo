"""Regression tests for session expiry side effects."""

import os
import sys

import pytest
from flask import Flask, session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database.auth_db as auth_db  # noqa: E402
import extensions  # noqa: E402
import utils.session as session_utils  # noqa: E402


def test_auto_expiry_broadcasts_force_logout_to_all_devices(monkeypatch):
    """3 AM auto-expiry should notify other browser sessions immediately."""
    app = Flask(__name__)
    app.secret_key = "test-secret"
    emitted = []

    class FakeSocketIO:
        def emit(self, event, payload):
            emitted.append((event, payload))

    monkeypatch.setattr(auth_db, "upsert_auth", lambda *args, **kwargs: 1)
    monkeypatch.setattr(auth_db, "clear_user_sessions", lambda username: None)
    monkeypatch.setattr(extensions, "socketio", FakeSocketIO())
    monkeypatch.setattr(
        "database.cache_invalidation.publish_all_cache_invalidation",
        lambda username: None,
    )
    monkeypatch.setattr("database.master_contract_cache_hook.clear_cache_on_logout", lambda: None)
    monkeypatch.setattr("database.settings_db.clear_settings_cache", lambda: None)
    monkeypatch.setattr("database.strategy_db.clear_strategy_cache", lambda: None)
    monkeypatch.setattr("database.telegram_db.clear_telegram_cache", lambda: None)

    with app.test_request_context("/"):
        session["user"] = "rajandran"
        session_utils.revoke_user_tokens(revoke_db_tokens=True)

    assert ("active_sessions_update", {"count": 0, "sessions": []}) in emitted
    force_logout_events = [payload for event, payload in emitted if event == "force_logout"]
    assert force_logout_events
    assert "Session expired" in force_logout_events[0]["message"]
