"""Regression tests: API-key responses carry no-store cache headers."""

import os
import sys
from unittest.mock import patch

from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAKE_USER = "test-user-not-real"
FAKE_KEY = "test-api-key-not-real-12345678"


class TestNoStoreResponseHelper:
    """no_store_response must set Cache-Control and Pragma headers."""

    def test_sets_no_store_headers(self):
        from utils.security_headers import no_store_response

        app = Flask(__name__)
        app.config["TESTING"] = True
        with app.test_request_context("/"):
            resp = no_store_response({"status": "ok"})
            assert resp.headers["Cache-Control"] == "no-store, max-age=0"
            assert resp.headers["Pragma"] == "no-cache"

    def test_wraps_jsonify(self):
        from utils.security_headers import no_store_response

        app = Flask(__name__)
        app.config["TESTING"] = True
        with app.test_request_context("/"):
            resp = no_store_response({"api_key": FAKE_KEY})
            assert resp.headers["Cache-Control"] == "no-store, max-age=0"
            assert resp.get_json()["api_key"] == FAKE_KEY


class TestApiKeyGetHeaders:
    """GET /apikey must return no-store headers when serving JSON."""

    def test_json_path_has_no_store(self):
        from blueprints.apikey import api_key_bp

        app = Flask(__name__)
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test"
        app.register_blueprint(api_key_bp)

        with (
            patch("utils.session.is_session_valid", return_value=True),
            patch("blueprints.apikey.get_api_key_for_tradingview", return_value=FAKE_KEY),
            patch("blueprints.apikey.get_order_mode", return_value="auto"),
        ):
            with app.test_client() as client:
                with client.session_transaction() as sess:
                    sess["user"] = FAKE_USER
                resp = client.get("/apikey", headers={"Accept": "application/json"})

            assert resp.status_code == 200
            assert resp.headers["Cache-Control"] == "no-store, max-age=0"
            assert resp.headers["Pragma"] == "no-cache"
            assert FAKE_KEY in resp.get_data(as_text=True)


class TestApiKeyPostHeaders:
    """POST /apikey must return no-store headers on key generation."""

    def test_post_generates_key_with_no_store(self):
        from blueprints.apikey import api_key_bp

        app = Flask(__name__)
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test"
        app.register_blueprint(api_key_bp)

        with (
            patch("utils.session.is_session_valid", return_value=True),
            patch("blueprints.apikey.upsert_api_key", return_value=1),
        ):
            with app.test_client() as client:
                with client.session_transaction() as sess:
                    sess["user"] = FAKE_USER
                resp = client.post(
                    "/apikey",
                    json={"user_id": FAKE_USER},
                    headers={"Accept": "application/json"},
                )

            assert resp.status_code == 200
            assert resp.headers["Cache-Control"] == "no-store, max-age=0"
            assert resp.headers["Pragma"] == "no-cache"
            body = resp.get_json()
            assert "api_key" in body


class TestPlaygroundApiKeyHeaders:
    """GET /playground/api-key must return no-store headers."""

    def test_playground_key_has_no_store(self):
        from blueprints.playground import playground_bp

        app = Flask(__name__)
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test"
        app.register_blueprint(playground_bp)

        with (
            patch("utils.session.is_session_valid", return_value=True),
            patch("blueprints.playground.get_api_key_for_tradingview", return_value=FAKE_KEY),
        ):
            with app.test_client() as client:
                with client.session_transaction() as sess:
                    sess["user"] = FAKE_USER
                resp = client.get("/playground/api-key")

            assert resp.status_code == 200
            assert resp.headers["Cache-Control"] == "no-store, max-age=0"
            assert resp.headers["Pragma"] == "no-cache"
            assert resp.get_json()["api_key"] == FAKE_KEY


class TestWebsocketApiKeyHeaders:
    """GET /api/websocket/apikey must return no-store headers."""

    def test_websocket_key_has_no_store(self):
        from blueprints.websocket_example import websocket_bp

        app = Flask(__name__)
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test"
        app.register_blueprint(websocket_bp)

        with (
            patch(
                "blueprints.websocket_example.get_username_from_session",
                return_value=FAKE_USER,
            ),
            patch(
                "database.auth_db.get_api_key_for_tradingview",
                return_value=FAKE_KEY,
            ),
        ):
            with app.test_client() as client:
                resp = client.get("/api/websocket/apikey")

            assert resp.status_code == 200
            assert resp.headers["Cache-Control"] == "no-store, max-age=0"
            assert resp.headers["Pragma"] == "no-cache"
            assert resp.get_json()["api_key"] == FAKE_KEY
