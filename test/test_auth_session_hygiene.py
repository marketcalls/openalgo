"""Regression tests for session hygiene on successful password authentication.

``POST /auth/login`` clears the session before writing any authenticated
values, so leftovers from an abandoned earlier flow (a password-reset token, a
stale broker key, a half-finished TOTP park) cannot survive into the
authenticated session.

This is state hygiene, not a session-fixation fix: Flask signs the whole
session into the cookie, so there is no server-side session id to rotate.
"""

import atexit
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask, session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEST_DB = Path(__file__).resolve().parents[1] / "tmp" / "test_auth_session_hygiene.db"
TEST_DB.parent.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB.as_posix()}")
atexit.register(lambda: TEST_DB.unlink(missing_ok=True))

import blueprints.auth as auth_bp_module  # noqa: E402

# Keys a previous, abandoned flow could have left behind.
STALE_KEYS = {
    "reset_token": "hashed-reset-token",
    "reset_email": "someone@example.com",
    "reset_method": "email",
    "email_reset_token": "hashed-email-token",
    "broker": "staleboker",
    "totp_verified_at": "2026-01-01T00:00:00+00:00",
    "nubra_temp_token": "stale-temp-token",
}


@pytest.fixture()
def login_post_context():
    """Request context for POST /auth/login with valid credentials."""
    app = Flask(__name__)
    app.secret_key = "test-secret"
    with app.test_request_context(
        "/auth/login",
        method="POST",
        data={"username": "rajandran", "password": "correct-horse"},
        headers={"User-Agent": "pytest"},
    ):
        yield


def _patch_login_deps(monkeypatch, *, totp_required=False):
    """Stub out everything the login view touches except the session logic."""
    monkeypatch.setattr(auth_bp_module, "find_user_by_username", lambda *a, **k: object())
    monkeypatch.setattr(auth_bp_module, "authenticate_user", lambda u, p: True)
    monkeypatch.setattr(
        auth_bp_module,
        "find_user_by_exact_username",
        lambda u: SimpleNamespace(is_totp_required_for=lambda _scope: totp_required),
    )
    monkeypatch.setattr(auth_bp_module, "_try_resume_broker_session", lambda u: None)
    monkeypatch.setattr(auth_bp_module, "get_real_ip", lambda: "127.0.0.1")


def test_stale_keys_do_not_survive_password_login(monkeypatch, login_post_context):
    """An abandoned earlier flow must not leak into the authenticated session."""
    _patch_login_deps(monkeypatch)
    session.update(STALE_KEYS)

    auth_bp_module.login()

    for key in STALE_KEYS:
        assert key not in session, f"stale key {key!r} survived password login"
    assert session["user"] == "rajandran"


def test_stale_keys_do_not_survive_into_the_totp_park(monkeypatch, login_post_context):
    """The TOTP branch parks a username; it must not inherit stale state either."""
    _patch_login_deps(monkeypatch, totp_required=True)
    session.update(STALE_KEYS)

    auth_bp_module.login()

    for key in STALE_KEYS:
        assert key not in session, f"stale key {key!r} survived into the TOTP park"
    # Password alone must not authenticate when TOTP is required.
    assert "user" not in session
    assert session["pending_totp_user"] == "rajandran"


def test_login_still_authenticates_from_an_empty_session(monkeypatch, login_post_context):
    """Clearing an already-empty session is a no-op, not a regression."""
    _patch_login_deps(monkeypatch)

    auth_bp_module.login()

    assert session["user"] == "rajandran"


# --- Two-step login: 1) OpenAlgo password login  2) broker OAuth -> /dashboard ---
#
# Stage 1 must leave exactly what stage 2 consumes (session["user"]) and nothing
# that would make the app think stage 2 already happened.

# Deliberately no "logged_in"/"login_time" here: those trip the pre-existing
# expired-session clear at auth.py:307, so seeding them would make this test
# pass even without the clear on successful password auth.
STAGE_TWO_KEYS = {
    "broker": "zerodha",
    "user_session_key": "stale-key",
    "session_id": "stale-session-id",
    "FEED_TOKEN": "stale-feed-token",
    "USER_ID": "stale-client-id",
}


def test_stage_one_leaves_exactly_what_stage_two_needs(monkeypatch, login_post_context):
    """After OpenAlgo login, only "user" is set; broker auth has not happened."""
    _patch_login_deps(monkeypatch)

    auth_bp_module.login()

    # Stage 2 (brlogin) reads session["user"] to call handle_auth_success().
    assert session["user"] == "rajandran"
    # Nothing may claim broker auth is already complete.
    assert "logged_in" not in session
    assert "session_id" not in session


def test_stale_broker_auth_does_not_survive_into_a_new_login(monkeypatch, login_post_context):
    """A previous broker session must not carry into a fresh password login.

    Without the clear, a leftover broker/session_id would ride along until
    handle_auth_success() overwrote it, leaving the dashboard briefly reachable
    on a session that has not completed stage 2.
    """
    _patch_login_deps(monkeypatch)
    session.update(STAGE_TWO_KEYS)

    auth_bp_module.login()

    for key in STAGE_TWO_KEYS:
        assert key not in session, f"stale stage-2 key {key!r} survived a new login"
    assert session["user"] == "rajandran"
