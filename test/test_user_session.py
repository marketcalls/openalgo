"""Regression tests for brokerless (user-only) sessions on setup endpoints.

A fresh password login sets only session["user"]; "logged_in" appears only
after broker auth. Setup endpoints (credentials, profile data, permissions,
capabilities) must accept such sessions, otherwise a misconfigured broker
locks the user out of the screens that fix it.
"""

import os
import sys

import pytest
from flask import Flask, jsonify, session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.session as session_utils  # noqa: E402


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.secret_key = "test-secret"

    @app.route("/setup-endpoint")
    @session_utils.check_user_session
    def setup_endpoint():
        return jsonify({"status": "success"}), 200

    @app.route("/trading-endpoint")
    @session_utils.check_session_validity
    def trading_endpoint():
        return jsonify({"status": "success"}), 200

    return app


def test_user_session_passes_without_broker(app):
    """User-only session (no logged_in flag) reaches setup endpoints."""
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user"] = "nihal697"
        resp = client.get("/setup-endpoint")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"


def test_user_session_rejected_when_logged_out(app):
    """No user in session -> JSON 401 (never an HTML redirect)."""
    with app.test_client() as client:
        resp = client.get("/setup-endpoint")
        assert resp.status_code == 401
        body = resp.get_json()
        assert body["error"] == "session_expired"


def test_trading_gate_still_requires_broker_login(app):
    """check_session_validity keeps rejecting brokerless sessions."""
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user"] = "nihal697"
        resp = client.get("/trading-endpoint", headers={"Accept": "application/json"})
        assert resp.status_code == 401
