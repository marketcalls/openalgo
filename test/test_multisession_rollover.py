"""Regression tests for the multi-device daily-rollover revoke guard (audit #1).

A stale browser cookie crossing the ~3 AM IST boundary must NOT revoke the
single shared broker token when another device has already re-authenticated
after the boundary — otherwise the fresh device gets kicked daily.
"""

import os
import sys
from datetime import timedelta

import pytest
from flask import Flask, session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database.auth_db as auth_db  # noqa: E402
import extensions  # noqa: E402
import utils.session as session_utils  # noqa: E402


def _patch_common(monkeypatch, emitted):
    class FakeSocketIO:
        def emit(self, event, payload):
            emitted.append((event, payload))

    monkeypatch.setattr(extensions, "socketio", FakeSocketIO())
    monkeypatch.setattr(
        "database.cache_invalidation.publish_all_cache_invalidation", lambda u: None
    )
    monkeypatch.setattr("database.master_contract_cache_hook.clear_cache_on_logout", lambda: None)
    monkeypatch.setattr("database.settings_db.clear_settings_cache", lambda: None)
    monkeypatch.setattr("database.strategy_db.clear_strategy_cache", lambda: None)
    monkeypatch.setattr("database.telegram_db.clear_telegram_cache", lambda: None)


def test_stale_cookie_does_not_revoke_when_fresher_session_exists(monkeypatch):
    """Device A (stale, logged in yesterday) must not revoke device B's fresh token."""
    app = Flask(__name__)
    app.secret_key = "test-secret"
    emitted = []
    _patch_common(monkeypatch, emitted)

    revoked, cleared, removed = [], [], []
    monkeypatch.setattr(auth_db, "upsert_auth", lambda *a, **k: revoked.append((a, k)) or 1)
    monkeypatch.setattr(auth_db, "clear_user_sessions", lambda u: cleared.append(u))
    monkeypatch.setattr(auth_db, "remove_session", lambda sid: removed.append(sid))

    boundary = session_utils._todays_rollover_boundary()
    fresher_login = (boundary + timedelta(hours=1)).replace(tzinfo=None).isoformat()
    monkeypatch.setattr(
        auth_db,
        "get_active_sessions",
        lambda u: [{"session_id": "device-B", "login_time": fresher_login}],
    )

    with app.test_request_context("/"):
        session["user"] = "rajandran"
        session["session_id"] = "device-A-stale"
        session_utils.revoke_user_tokens(revoke_db_tokens=True)

    assert revoked == [], "shared broker token must NOT be revoked"
    assert cleared == [], "other devices must NOT be cleared"
    assert removed == ["device-A-stale"], "only the stale device's row is removed"
    assert not any(event == "force_logout" for event, _ in emitted)


def test_stale_cookie_revokes_when_no_fresher_session(monkeypatch):
    """Normal daily rollover (all sessions stale) must still revoke + force logout."""
    app = Flask(__name__)
    app.secret_key = "test-secret"
    emitted = []
    _patch_common(monkeypatch, emitted)

    revoked, cleared = [], []
    monkeypatch.setattr(auth_db, "upsert_auth", lambda *a, **k: revoked.append((a, k)) or 1)
    monkeypatch.setattr(auth_db, "clear_user_sessions", lambda u: cleared.append(u))
    monkeypatch.setattr(auth_db, "remove_session", lambda sid: None)

    boundary = session_utils._todays_rollover_boundary()
    stale_login = (boundary - timedelta(hours=1)).replace(tzinfo=None).isoformat()
    monkeypatch.setattr(
        auth_db,
        "get_active_sessions",
        lambda u: [{"session_id": "device-A-stale", "login_time": stale_login}],
    )

    with app.test_request_context("/"):
        session["user"] = "rajandran"
        session["session_id"] = "device-A-stale"
        session_utils.revoke_user_tokens(revoke_db_tokens=True)

    assert len(revoked) == 1, "stale shared token must be revoked"
    assert cleared == ["rajandran"], "all sessions cleared on a real rollover"
    assert any(event == "force_logout" for event, _ in emitted)


def test_no_active_sessions_falls_back_to_revoke(monkeypatch):
    """Empty active-session table is the safe default: behave as today (revoke)."""
    app = Flask(__name__)
    app.secret_key = "test-secret"
    emitted = []
    _patch_common(monkeypatch, emitted)

    revoked = []
    monkeypatch.setattr(auth_db, "upsert_auth", lambda *a, **k: revoked.append((a, k)) or 1)
    monkeypatch.setattr(auth_db, "clear_user_sessions", lambda u: None)
    monkeypatch.setattr(auth_db, "remove_session", lambda sid: None)
    monkeypatch.setattr(auth_db, "get_active_sessions", lambda u: [])

    with app.test_request_context("/"):
        session["user"] = "rajandran"
        session["session_id"] = "device-A-stale"
        session_utils.revoke_user_tokens(revoke_db_tokens=True)

    assert len(revoked) == 1
