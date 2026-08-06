"""Regression tests for /auth/logout session cleanup."""

import os
import sys

import pytest
from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import blueprints.auth as auth_bp_module  # noqa: E402
import database.auth_db as auth_db  # noqa: E402


def _app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(auth_bp_module.auth_bp)
    return app


def test_logout_clears_half_logged_in_session():
    """A password-only session (broker OAuth unfinished) must still be cleared."""
    app = _app()
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "rajandran"

        response = client.get("/auth/logout")

        assert response.status_code == 302
        with client.session_transaction() as session:
            assert "user" not in session


def test_logout_clears_full_session(monkeypatch):
    """A fully logged-in session is also cleared."""
    monkeypatch.setattr(auth_bp_module, "upsert_auth", lambda *args, **kwargs: None)
    monkeypatch.setattr(auth_db, "clear_user_sessions", lambda *args, **kwargs: None)
    monkeypatch.setattr(auth_bp_module.socketio, "emit", lambda *args, **kwargs: None)

    app = _app()
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "rajandran"
            session["logged_in"] = True
            session["broker"] = "dhan"

        response = client.post("/auth/logout")

        assert response.status_code == 200
        with client.session_transaction() as session:
            assert "user" not in session
            assert "logged_in" not in session
